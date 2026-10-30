"""Menu de monitoreo IoT: sensores, lecturas, umbrales y alertas."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from logistica.cli import consola
from logistica.cli.permisos import (
    NIVEL_ADMINISTRADOR,
    NIVEL_AUDITOR,
    NIVEL_OPERADOR,
    opciones_para,
)
from logistica.domain.alerta import Alerta, EstadoAlerta
from logistica.domain.lectura import Lectura
from logistica.domain.umbral import MagnitudUmbral, Umbral
from logistica.exceptions import LogisticaError
from logistica.services.monitoreo_service import MonitoreoService

DIAS_POR_DEFECTO = 7


def _mostrar_lecturas(lecturas: list[Lectura]) -> None:
    consola.tabla(
        # No va columna de envio: `lecturas_por_sensor` no guarda `envio_id`
        # (solo lo hace `recorrido_por_contenedor`), asi que saldria siempre "-".
        ["MOMENTO", "TEMP", "HUMEDAD", "VIBRACION", "BATERIA", "CONTENEDOR"],
        [
            [
                f"{le.momento.astimezone():%d/%m %H:%M:%S}",
                f"{le.temperatura:.1f}",
                f"{le.humedad:.1f}",
                f"{le.vibracion:.2f}",
                str(le.bateria),
                str(le.contenedor_id)[:8],
            ]
            for le in lecturas
        ],
    )


def _mostrar_alertas(alertas: list[Alerta]) -> None:
    consola.tabla(
        ["ID", "FECHA", "TIPO", "SEVERIDAD", "ESTADO", "VALOR", "LIMITE"],
        [
            [
                str(a.id),
                f"{a.fecha.astimezone():%d/%m %H:%M}",
                a.tipo.value,
                a.severidad.value,
                a.estado.value,
                f"{a.detalle.valor:.2f}" if a.detalle else "-",
                f"{a.detalle.umbral:.2f}" if a.detalle else "-",
            ]
            for a in alertas
        ],
    )


def construir(servicio: MonitoreoService, rol_nivel: int = NIVEL_ADMINISTRADOR) -> None:
    def listar_sensores() -> None:
        consola.titulo("Sensores")
        try:
            sensores = servicio.listar_sensores()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not sensores:
            consola.aviso("No hay sensores cargados.")
            return
        consola.tabla(
            ["N. SERIE", "TIPO", "MODELO", "CADA", "ESTADO", "CONTENEDOR"],
            [
                [
                    s.numero_serie,
                    s.tipo.value,
                    s.modelo,
                    f"{s.intervalo_reporte_segundos}s",
                    s.estado.value,
                    str(s.contenedor_id)[:8] if s.contenedor_id else "sin instalar",
                ]
                for s in sensores
            ],
        )

    def sensores_de_contenedor() -> None:
        consola.titulo("Sensores de un contenedor")
        texto = consola.pedir("ID del contenedor").strip()
        try:
            contenedor_id = UUID(texto)
        except ValueError:
            consola.error("El ID del contenedor no es valido.")
            return
        try:
            sensores = servicio.listar_sensores_de_contenedor(contenedor_id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not sensores:
            consola.aviso("Ese contenedor no tiene sensores instalados.")
            return
        consola.tabla(
            ["N. SERIE", "TIPO", "MODELO", "CADA", "ESTADO"],
            [
                [s.numero_serie, s.tipo.value, s.modelo,
                 f"{s.intervalo_reporte_segundos}s", s.estado.value]
                for s in sensores
            ],
        )

    def historico() -> None:
        consola.titulo("Consulta historica de lecturas")
        consola.aviso("Se acepta el numero de serie del sensor o su UUID.")
        consola.aviso(f"Enter en las fechas usa los ultimos {DIAS_POR_DEFECTO} dias.")
        try:
            sensor = servicio.buscar_sensor(consola.pedir("Sensor"))
        except LogisticaError as error:
            consola.error(str(error))
            return

        hasta_defecto = datetime.now(timezone.utc)
        desde_defecto = hasta_defecto - timedelta(days=DIAS_POR_DEFECTO - 1)
        texto_desde = consola.pedir("Desde (Enter para el valor por defecto)").strip()
        texto_hasta = consola.pedir("Hasta (Enter para ahora)").strip()
        try:
            desde = datetime.fromisoformat(texto_desde) if texto_desde else desde_defecto
            hasta = datetime.fromisoformat(texto_hasta) if texto_hasta else hasta_defecto
        except ValueError:
            consola.error("Fecha invalida. Usa 2026-10-29T08:00:00-03:00, o Enter.")
            return

        try:
            lecturas = servicio.historico(sensor.id, desde, hasta)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not lecturas:
            consola.aviso("El sensor no reporto en ese intervalo.")
            return
        consola.aviso(f"{sensor.numero_serie} ({sensor.tipo.value})")
        _mostrar_lecturas(lecturas)

    def ultimas() -> None:
        consola.titulo("Ultimas lecturas de un sensor")
        try:
            sensor = servicio.buscar_sensor(consola.pedir("Sensor"))
        except LogisticaError as error:
            consola.error(str(error))
            return
        try:
            lecturas = servicio.ultimas_lecturas(sensor.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not lecturas:
            consola.aviso("El sensor no tiene lecturas recientes.")
            return
        consola.aviso(f"{sensor.numero_serie} ({sensor.tipo.value})")
        _mostrar_lecturas(lecturas)

    def listar_umbrales() -> None:
        consola.titulo("Umbrales configurados")
        consola.aviso("El umbral es por tipo de contenedor: un REEFER y un DRY no "
                      "toleran la misma temperatura (D25).")
        try:
            umbrales = servicio.listar_umbrales()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not umbrales:
            consola.aviso("No hay umbrales configurados.")
            return
        consola.tabla(
            ["TIPO CONTENEDOR", "MAGNITUD", "MINIMO", "MAXIMO", "UNIDAD"],
            [
                [u.tipo_contenedor, u.magnitud.value, f"{u.minimo:.1f}",
                 f"{u.maximo:.1f}", u.unidad]
                for u in umbrales
            ],
        )

    def cobertura() -> None:
        consola.titulo("Cobertura de umbrales")
        consola.aviso(
            "Control de integridad: un tipo de contenedor con sensores pero sin "
            "umbral no se evalua, y la deteccion lo saltea en silencio."
        )
        try:
            cobertura = servicio.cobertura_de_umbrales()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not cobertura:
            consola.aviso("No hay sensores activos instalados en contenedores.")
            return
        consola.tabla(
            ["TIPO CONTENEDOR", "SENSORES", "CUBIERTAS", "FALTANTES"],
            [
                [
                    c.tipo_contenedor,
                    str(c.sensores),
                    ", ".join(c.magnitudes_cubiertas) or "ninguna",
                    ", ".join(c.magnitudes_faltantes) or "-",
                ]
                for c in cobertura
            ],
        )
        sin_cubrir = [c for c in cobertura if not c.esta_cubierto]
        if sin_cubrir:
            consola.error(
                f"{len(sin_cubrir)} tipo(s) de contenedor con magnitudes sin umbral."
            )
        else:
            consola.exito("Todos los tipos en uso tienen sus umbrales.")

    def configurar_umbral() -> None:
        consola.titulo("Configurar un umbral")
        tipo_contenedor = consola.pedir("Tipo de contenedor (REEFER_40, DRY_20...)")
        consola.aviso(
            "Magnitud: " + ", ".join(f"{i}={m.value}" for i, m in enumerate(MagnitudUmbral, 1))
        )
        texto = consola.pedir("Magnitud").strip()
        valores = list(MagnitudUmbral)
        if texto.isdigit() and 1 <= int(texto) <= len(valores):
            magnitud = valores[int(texto) - 1]
        else:
            try:
                magnitud = MagnitudUmbral(texto.upper())
            except ValueError:
                consola.error("Magnitud invalida.")
                return
        try:
            minimo = float(consola.pedir("Minimo"))
            maximo = float(consola.pedir("Maximo"))
        except ValueError:
            consola.error("El minimo y el maximo tienen que ser numeros.")
            return
        unidad = consola.pedir("Unidad (C, %, g)")

        try:
            umbral = Umbral(
                id=uuid4(),
                tipo_contenedor=tipo_contenedor.strip().upper(),
                magnitud=magnitud,
                minimo=minimo,
                maximo=maximo,
                unidad=unidad.strip(),
            )
            servicio.configurar_umbral(umbral)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(
            f"Umbral de {magnitud.value} para {umbral.tipo_contenedor}: "
            f"[{minimo}, {maximo}] {umbral.unidad}"
        )

    def alertas_abiertas() -> None:
        consola.titulo("Alertas abiertas")
        consola.aviso("Cuentan como abiertas las ABIERTA y las RECONOCIDA.")
        try:
            alertas = servicio.listar_alertas_abiertas()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not alertas:
            consola.aviso("No hay alertas abiertas.")
            return
        _mostrar_alertas(alertas)

    def alertas_de_sensor() -> None:
        consola.titulo("Alertas de un sensor")
        try:
            sensor = servicio.buscar_sensor(consola.pedir("Sensor"))
            alertas = servicio.listar_alertas_de_sensor(sensor.id)
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not alertas:
            consola.aviso("Ese sensor no genero alertas.")
            return
        consola.aviso(f"{sensor.numero_serie} ({sensor.tipo.value})")
        _mostrar_alertas(alertas)

    def cambiar_estado_alerta() -> None:
        consola.titulo("Reconocer o cerrar una alerta")
        texto = consola.pedir("ID de la alerta").strip()
        try:
            alerta_id = UUID(texto)
        except ValueError:
            consola.error("El ID de la alerta no es valido.")
            return
        consola.aviso(
            "Nuevo estado: " + ", ".join(f"{i}={e.value}" for i, e in enumerate(EstadoAlerta, 1))
        )
        eleccion = consola.pedir("Nuevo estado").strip()
        valores = list(EstadoAlerta)
        if eleccion.isdigit() and 1 <= int(eleccion) <= len(valores):
            destino = valores[int(eleccion) - 1]
        else:
            try:
                destino = EstadoAlerta(eleccion.upper())
            except ValueError:
                consola.error("Estado invalido.")
                return
        try:
            alerta = servicio.cambiar_estado_alerta(alerta_id, destino)
        except LogisticaError as error:
            consola.error(str(error))
            return
        consola.exito(f"La alerta quedo {alerta.estado.value}.")

    # Configurar un umbral cambia lo que TODO el sistema considera una anomalia,
    # asi que es de administrador. Consultar y reconocer alertas es del dia a
    # dia del operador, y mirar lecturas alcanza al auditor.
    secciones = [
        (NIVEL_AUDITOR, "Listar sensores", listar_sensores),
        (NIVEL_AUDITOR, "Sensores de un contenedor", sensores_de_contenedor),
        (NIVEL_AUDITOR, "Consulta historica de lecturas", historico),
        (NIVEL_AUDITOR, "Ultimas lecturas de un sensor", ultimas),
        (NIVEL_AUDITOR, "Umbrales configurados", listar_umbrales),
        (NIVEL_OPERADOR, "Cobertura de umbrales", cobertura),
        (NIVEL_ADMINISTRADOR, "Configurar un umbral", configurar_umbral),
        (NIVEL_OPERADOR, "Alertas abiertas", alertas_abiertas),
        (NIVEL_OPERADOR, "Alertas de un sensor", alertas_de_sensor),
        (NIVEL_OPERADOR, "Reconocer o cerrar una alerta", cambiar_estado_alerta),
    ]
    consola.menu("Monitoreo IoT y alertas", opciones_para(rol_nivel, secciones))
