"""Procesos periodicos de la aplicacion.

El enunciado pide cuatro: generacion automatica de facturas, deteccion de
sensores inactivos, cierre mensual de cuentas corrientes y prediccion diaria de
riesgos. A esos se suma la propagacion del Outbox, que es lo que mantiene
sincronizados los motores.

Cada proceso corre bajo un lock de Redis (D14): dos ejecuciones simultaneas de
la facturacion generarian facturas duplicadas. El lock se toma por nombre de
proceso, de modo que procesos distintos no se bloquean entre si.

Se arranca con:

    python -m logistica.jobs.planificador
"""
import logging
import signal
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler

from logistica.container import Contenedor
from logistica.exceptions import LogisticaError
from logistica.infrastructure.redis.lock import LockNoDisponible, lock_de_proceso
from logistica.logging_config import setup_logging

log = logging.getLogger(__name__)

# Cada cuanto corre cada proceso. El de sincronizacion va seguido porque es el
# que determina cuanto tarda el grafo en ponerse al dia.
SEGUNDOS_ENTRE_SINCRONIZACIONES = 10
MINUTOS_ENTRE_CHEQUEOS = 30
# La facturacion automatica corre de madrugada, cuando no hay operacion.
HORA_DE_FACTURACION = 2
# El cierre mensual, el primer dia de cada mes.
HORA_DE_CIERRE = 3


class Planificador:
    def __init__(self, contenedor: Contenedor) -> None:
        self._contenedor = contenedor
        self._scheduler = BlockingScheduler(timezone="UTC")
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            from logistica.infrastructure.redis.lock import conectar

            self._redis = conectar(self._contenedor.settings)
        return self._redis

    def _con_lock(self, nombre: str, segundos: int, tarea) -> None:
        """Corre la tarea solo si consigue el lock, y nunca deja escapar una
        excepcion: si un proceso periodico lanza, APScheduler lo descarta y no
        vuelve a ejecutarlo."""
        try:
            with lock_de_proceso(self.redis, nombre, segundos):
                tarea()
        except LockNoDisponible:
            log.debug("'%s' ya se esta ejecutando en otra instancia", nombre)
        except LogisticaError as error:
            log.error("El proceso '%s' fallo: %s", nombre, error)
        except Exception:
            log.exception("Error inesperado en el proceso '%s'", nombre)

    # --- Procesos ---------------------------------------------------------

    def sincronizar(self) -> None:
        """Vacia el Outbox hacia los demas motores."""

        def tarea() -> None:
            resultado = self._contenedor.worker_de_sincronizacion.procesar_tanda()
            if resultado.hubo_trabajo:
                log.info("Sincronizacion: %s", resultado)

        self._con_lock("sincronizacion", SEGUNDOS_ENTRE_SINCRONIZACIONES * 6, tarea)

    def chequear_consistencia(self) -> None:
        """Compara PostgreSQL contra el grafo y avisa si difieren."""

        def tarea() -> None:
            reporte = self._contenedor.chequeo_de_consistencia.verificar()
            if reporte.hay_problemas:
                for linea in reporte.resumen():
                    log.warning("  %s", linea)
            else:
                log.info(
                    "Consistencia OK (%s eventos pendientes)", reporte.eventos_pendientes
                )

        self._con_lock("chequeo_consistencia", MINUTOS_ENTRE_CHEQUEOS * 60, tarea)

    def facturar_entregados(self) -> None:
        """Proceso periodico: genera las facturas de los envios entregados.

        El lock es imprescindible, no una precaucion: dos ejecuciones
        simultaneas podrian leer la lista de entregados antes de que la otra
        escriba su factura, y emitir dos por el mismo envio (D14).
        """

        def tarea() -> None:
            emitidas = self._contenedor.facturacion.facturar_entregados()
            if emitidas:
                log.info("Facturacion automatica: %s facturas", len(emitidas))

        self._con_lock("facturacion_automatica", 3600, tarea)

    def cerrar_mes(self) -> None:
        """Proceso periodico: marca las facturas vencidas y resume las cuentas."""

        def tarea() -> None:
            log.info("Cierre mensual: %s", self._contenedor.facturacion.cerrar_mes())

        self._con_lock("cierre_mensual", 3600, tarea)

    def verificar_saldos(self) -> None:
        """Control de integridad: el saldo guardado contra la suma de los
        movimientos. Si difieren, hubo una escritura fuera de la transaccion."""

        def tarea() -> None:
            diferencias = self._contenedor.facturacion.verificar_saldos()
            for cuenta, calculado in diferencias:
                log.error(
                    "Cuenta %s descuadrada: guardado=%s calculado=%s",
                    cuenta.id, cuenta.saldo, calculado,
                )

        self._con_lock("verificacion_saldos", MINUTOS_ENTRE_CHEQUEOS * 60, tarea)
    def detectar_sensores_inactivos(self) -> None:
        """Revisa las señales de los sensores bajo un lock de Redis."""

        def tarea() -> None:
            resultados = self._contenedor.deteccion_inactividad.verificar()
            inactivos = 0

            for resultado in resultados:
                if resultado.estado == "INACTIVO":
                    inactivos += 1
                    log.warning(
                        "Sensor %s inactivo: %.1f segundos sin reportar",
                        resultado.sensor_id,
                        resultado.segundos_sin_reportar,
                    )
                elif resultado.estado in ("SIN_DATOS", "RELOJ_INVALIDO"):
                    log.warning(
                        "Sensor %s: no se puede evaluar (%s)",
                        resultado.sensor_id,
                        resultado.estado,
                    )

            log.info(
                "Monitoreo: %s sensores revisados, %s inactivos",
                len(resultados),
                inactivos,
            )

        self._con_lock("deteccion_sensores_inactivos", 120, tarea)
    # --- Arranque ---------------------------------------------------------

    def registrar(self) -> None:
        self._scheduler.add_job(
            self.sincronizar,
            "interval",
            seconds=SEGUNDOS_ENTRE_SINCRONIZACIONES,
            id="sincronizacion",
            # Si una corrida se atrasa, no se acumulan varias esperando turno:
            # se ejecuta una sola y se descartan las perdidas.
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.now(timezone.utc),
        )
        self._scheduler.add_job(
            self.chequear_consistencia,
            "interval",
            minutes=MINUTOS_ENTRE_CHEQUEOS,
            id="chequeo_consistencia",
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self.facturar_entregados,
            "cron",
            hour=HORA_DE_FACTURACION,
            id="facturacion_automatica",
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self.cerrar_mes,
            "cron",
            day=1,
            hour=HORA_DE_CIERRE,
            id="cierre_mensual",
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self.verificar_saldos,
            "interval",
            minutes=MINUTOS_ENTRE_CHEQUEOS,
            id="verificacion_saldos",
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self.detectar_sensores_inactivos,
            "interval",
            seconds=30,
            id="deteccion_sensores_inactivos",
            coalesce=True,
            max_instances=1,
        )
        # Pendientes de esta semana, a cargo de los demas:
        #   - prediccion diaria de riesgos (Mati, cron diario)

    def arrancar(self) -> None:
        self.registrar()
        tareas = ", ".join(j.id for j in self._scheduler.get_jobs())
        log.info("Planificador arrancado. Procesos: %s", tareas)
        print(f"Procesos periodicos activos: {tareas}")
        print("Ctrl+C para detener.")
        try:
            self._scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            log.info("Planificador detenido")

    def detener(self, *_: object) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)


def main() -> int:
    setup_logging()
    contenedor = Contenedor(configurar_logging=False)
    planificador = Planificador(contenedor)
    signal.signal(signal.SIGINT, planificador.detener)
    planificador.arrancar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
