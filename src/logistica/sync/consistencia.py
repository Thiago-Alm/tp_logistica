"""Chequeo de consistencia entre PostgreSQL y el grafo.

El Outbox garantiza que ningun cambio se pierda, pero no alcanza por si solo.
Hay tres formas de que el grafo quede distinto de PostgreSQL:

1. Un evento agoto sus reintentos y nunca llego (el destino estuvo caido mas
   tiempo que la politica de reintentos).
2. Alguien escribio en PostgreSQL sin pasar por los servicios: un INSERT a
   mano, una carga masiva, o los propios datos semilla del proyecto. Esos
   cambios no generan eventos, asi que el grafo no se entera.
3. Un nodo quedo en el grafo despues de que su fila se borrara en PostgreSQL.

Por eso la sincronizacion por eventos se complementa con dos herramientas:
`verificar()`, que compara y reporta, y `reconstruir()`, que rearma el grafo
entero desde PostgreSQL. La segunda es posible porque el grafo es **redundante
por diseno**: no contiene ningun dato original, solo una proyeccion.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from logistica.domain.evento_outbox import (
    REINTENTOS_MAXIMOS,
    TipoAgregado,
    TipoEvento,
    nuevo_evento,
)
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.sync.proyector_neo4j import ProyectorNeo4j

log = logging.getLogger(__name__)

# Que etiqueta del grafo corresponde a cada agregado.
ETIQUETAS = {
    TipoAgregado.CLIENTE: "Cliente",
    TipoAgregado.OPERADOR: "Operador",
    TipoAgregado.UBICACION: "Ubicacion",
    TipoAgregado.VEHICULO: "Vehiculo",
    TipoAgregado.CONTENEDOR: "Contenedor",
    TipoAgregado.ENVIO: "Envio",
    TipoAgregado.TRAMO: "Tramo",
}

# Orden de reconstruccion: los maestros primero, para que cuando se proyecten
# los envios y tramos sus nodos ya tengan propiedades y no queden como nodos
# vacios creados por un MERGE.
ORDEN_DE_RECONSTRUCCION = [
    TipoAgregado.UBICACION,
    TipoAgregado.OPERADOR,
    TipoAgregado.VEHICULO,
    TipoAgregado.CLIENTE,
    TipoAgregado.CONTENEDOR,
    TipoAgregado.ENVIO,
    TipoAgregado.TRAMO,
]


@dataclass(frozen=True)
class DiferenciaPorTipo:
    agregado: TipoAgregado
    en_postgres: int
    en_grafo: int
    faltan_en_grafo: set[str]
    sobran_en_grafo: set[str]

    @property
    def coincide(self) -> bool:
        return not self.faltan_en_grafo and not self.sobran_en_grafo

    def __str__(self) -> str:
        estado = "OK" if self.coincide else "DIFIERE"
        detalle = ""
        if not self.coincide:
            detalle = f"  (faltan {len(self.faltan_en_grafo)}, sobran {len(self.sobran_en_grafo)})"
        return (
            f"[{estado:7}] {self.agregado.value:11} "
            f"postgres={self.en_postgres:4}  grafo={self.en_grafo:4}{detalle}"
        )


@dataclass
class ReporteDeConsistencia:
    momento: datetime
    eventos_pendientes: int = 0
    eventos_vencidos: list[str] = field(default_factory=list)
    diferencias: list[DiferenciaPorTipo] = field(default_factory=list)

    @property
    def hay_problemas(self) -> bool:
        return bool(self.eventos_vencidos) or any(
            not d.coincide for d in self.diferencias
        )

    def resumen(self) -> list[str]:
        lineas = [f"Chequeo de consistencia - {self.momento:%Y-%m-%d %H:%M:%S}"]
        lineas.append(f"Eventos pendientes de propagar: {self.eventos_pendientes}")
        if self.eventos_vencidos:
            lineas.append(
                f"Eventos VENCIDOS (agotaron reintentos): {len(self.eventos_vencidos)}"
            )
            lineas.extend(f"  - {e}" for e in self.eventos_vencidos[:10])
        else:
            lineas.append("Eventos vencidos: ninguno")
        lineas.append("")
        lineas.extend(str(d) for d in self.diferencias)
        lineas.append("")
        veredicto = "HAY DIFERENCIAS" if self.hay_problemas else "TODO CONSISTENTE"
        lineas.append(f"Resultado: {veredicto}")
        return lineas


class ChequeoDeConsistencia:
    def __init__(
        self,
        unidad_de_trabajo: UnidadDeTrabajo,
        proyector: ProyectorNeo4j,
        reintentos_maximos: int = REINTENTOS_MAXIMOS,
    ) -> None:
        self._uow = unidad_de_trabajo
        self._proyector = proyector
        self._reintentos_maximos = reintentos_maximos

    def verificar(self) -> ReporteDeConsistencia:
        """Compara PostgreSQL contra el grafo, sin modificar nada."""
        reporte = ReporteDeConsistencia(momento=datetime.now(timezone.utc))

        with self._uow as uow:
            reporte.eventos_pendientes = uow.outbox.contar_pendientes()
            reporte.eventos_vencidos = [
                f"{e.agregado_tipo.value}/{e.evento_tipo.value} {e.agregado_id} "
                f"({e.reintentos} reintentos): {e.error_mensaje}"
                for e in uow.outbox.listar_vencidos(self._reintentos_maximos)
            ]
            for agregado, etiqueta in ETIQUETAS.items():
                en_postgres = {str(i) for i in uow.consistencia.ids_de(agregado)}
                en_grafo = self._proyector.ids_de_etiqueta(etiqueta)
                reporte.diferencias.append(
                    DiferenciaPorTipo(
                        agregado=agregado,
                        en_postgres=len(en_postgres),
                        en_grafo=len(en_grafo),
                        faltan_en_grafo=en_postgres - en_grafo,
                        sobran_en_grafo=en_grafo - en_postgres,
                    )
                )

        if reporte.hay_problemas:
            log.warning("El chequeo de consistencia encontro diferencias")
        return reporte

    def reconstruir(self, borrar_antes: bool = False) -> dict[TipoAgregado, int]:
        """Rearma el grafo desde PostgreSQL, sin pasar por el Outbox.

        Es posible porque el grafo no contiene ningun dato original: si se
        perdiera entero, se puede reconstruir. Esa propiedad es la que permite
        tratar su sincronizacion como eventual sin comprometer la correccion
        del sistema.

        `borrar_antes` vacia el grafo primero. Sin eso, la reconstruccion
        agrega y corrige lo que falta pero no elimina los nodos sobrantes,
        porque MERGE no borra.
        """
        if borrar_antes:
            log.info("Vaciando el grafo antes de reconstruirlo")
            self._proyector.borrar_todo()

        proyectados: dict[TipoAgregado, int] = {}
        momento = datetime.now(timezone.utc)
        with self._uow as uow:
            for agregado in ORDEN_DE_RECONSTRUCCION:
                filas = uow.consistencia.filas_para_proyectar(agregado)
                for fila in filas:
                    # Se arma un evento equivalente al que habria emitido el
                    # servicio y se lo aplica directamente: el proyector es el
                    # mismo, asi que el resultado tambien.
                    evento = nuevo_evento(
                        agregado, UUID(fila["id"]), TipoEvento.CREADO, fila, momento
                    )
                    self._proyector.aplicar(evento)
                proyectados[agregado] = len(filas)
                log.info("Reconstruidos %s nodos de %s", len(filas), agregado.value)

            # La relacion envio-contenedor no es una entidad con id propio, asi
            # que se proyecta aparte, como la relacion INCLUYE del grafo.
            asignaciones = uow.consistencia.asignaciones_de_contenedores()
            for fila in asignaciones:
                self._proyector.aplicar(
                    nuevo_evento(
                        TipoAgregado.ENVIO,
                        UUID(fila["envio_id"]),
                        TipoEvento.CONTENEDOR_ASIGNADO,
                        fila,
                        momento,
                    )
                )
            log.info("Reconstruidas %s relaciones envio-contenedor", len(asignaciones))
        return proyectados
