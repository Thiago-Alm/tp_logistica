"""Incidentes de los envios: alta, cambio de estado y los reportes de D12.

Es la pieza mas poliglota del sistema: el incidente vive en MongoDB, pero su
contexto y el denominador de los promedios estan en PostgreSQL.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from logistica.domain.incidente import (
    ContextoEnvio,
    EstadoIncidente,
    Incidente,
    SeveridadIncidente,
    TipoIncidente,
)
from logistica.domain.reportes import ConteoIncidentes, RutaConIncidentes
from logistica.exceptions import NoEncontrado, ValidacionError
from logistica.repositories.incidente_repository import (
    AgrupacionIncidentes,
    IncidenteRepository,
)
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

log = logging.getLogger(__name__)

LIMITE_RANKING_POR_DEFECTO = 10

# Ejes para los que el promedio significa algo: hacen falta un numerador y un
# denominador que hablen de la misma poblacion. Quedan afuera:
#
# - ESTADO: agrupa por el estado del INCIDENTE (ABIERTO, RESUELTO...), que no
#   es un estado de envio. "Incidentes ABIERTO / envios ABIERTO" no existe.
# - RUTA: no hay "envios de la ruta ARBUE->NLRTM"; la ruta sale de los tramos.
# - PAIS_ORIGEN: EnvioRepository resuelve el pais por la ubicacion de DESTINO.
EJES_CON_PROMEDIO = (
    AgrupacionIncidentes.CLIENTE,
    AgrupacionIncidentes.PAIS_DESTINO,
)


@dataclass(frozen=True)
class PromedioIncidentes:
    """Incidentes por envio de un grupo. `grupo` ya viene resuelto a texto
    legible: si el eje es el cliente, es su razon social y no su UUID."""

    grupo: str
    incidentes: int
    envios: int

    @property
    def promedio(self) -> float:
        """Incidentes por envio. Cero envios da 0 y no una division por cero:
        puede haber incidentes de envios que ya no estan (supuesto del grupo)."""
        return self.incidentes / self.envios if self.envios else 0.0


class IncidenteService:
    def __init__(
        self, incidentes: IncidenteRepository, unidad_de_trabajo: UnidadDeTrabajo
    ) -> None:
        self._incidentes = incidentes
        self._uow = unidad_de_trabajo

    # -- Alta y cambio de estado ---------------------------------------------

    def registrar(
        self,
        envio_id: UUID,
        tipo: TipoIncidente,
        severidad: SeveridadIncidente,
        descripcion: str,
        contenedor_id: UUID | None = None,
        fecha: datetime | None = None,
    ) -> Incidente:
        """Da de alta un incidente con el snapshot del envio al momento (D12).

        El contexto se arma leyendo PostgreSQL y se congela en el documento: si
        despues cambia la ruta del envio, el incidente sigue diciendo donde
        estaba cuando ocurrio. Es lo que permite rankear rutas sin salir de
        MongoDB.
        """
        contexto = self._armar_contexto(envio_id, contenedor_id)
        incidente = Incidente(
            id=uuid4(),
            envio_id=envio_id,
            tipo=tipo,
            severidad=severidad,
            descripcion=descripcion,
            contexto_envio=contexto,
            fecha=fecha or datetime.now(timezone.utc),
            contenedor_id=contenedor_id,
        )
        self._incidentes.guardar(incidente)
        log.info("Incidente %s registrado en el envio %s", incidente.id, envio_id)
        return incidente

    def _armar_contexto(
        self, envio_id: UUID, contenedor_id: UUID | None
    ) -> ContextoEnvio:
        """Las cuatro lecturas van en la misma transaccion (D28): el snapshot
        tiene que ser coherente entre si, no una mezcla de dos momentos."""
        with self._uow as uow:
            envio = uow.envios.obtener(envio_id)
            if envio is None:
                raise NoEncontrado(f"No existe el envio {envio_id}")
            if contenedor_id is not None and uow.contenedores.obtener(contenedor_id) is None:
                raise NoEncontrado(f"No existe el contenedor {contenedor_id}")
            origen = uow.ubicaciones.obtener(envio.origen_id)
            destino = uow.ubicaciones.obtener(envio.destino_id)

        if origen is None or destino is None:
            # No deberia pasar: hay FK. Si pasa, mejor fallar que guardar un
            # snapshot a medias que despues ensucie el ranking de rutas.
            raise NoEncontrado(
                f"El envio {envio_id} apunta a una ubicacion que no existe"
            )

        return ContextoEnvio(
            cliente_id=envio.cliente_id,
            origen=origen.etiqueta,
            destino=destino.etiqueta,
            pais_origen=origen.pais,
            pais_destino=destino.pais,
        )

    def cambiar_estado(
        self,
        incidente_id: UUID,
        destino: EstadoIncidente,
        usuario_id: UUID | None = None,
    ) -> Incidente:
        """Trae el incidente, le pide la transicion al dominio y lo persiste.

        No existe un `cambiar_estado(id, estado)` en el repositorio (D18): la
        validacion de la transicion vive en la entidad y el historial queda
        completo.
        """
        incidente = self._incidentes.obtener(incidente_id)
        if incidente is None:
            raise NoEncontrado(f"No existe el incidente {incidente_id}")
        incidente.pasar_a(destino, usuario_id)
        self._incidentes.actualizar(incidente)
        return incidente

    # -- Consultas y reportes -------------------------------------------------

    def listar_abiertos(self) -> list[Incidente]:
        """Reporte "Incidentes abiertos": ABIERTO y EN_ANALISIS."""
        return self._incidentes.listar_abiertos()

    def listar_por_envio(self, envio_id: UUID) -> list[Incidente]:
        return self._incidentes.listar_por_envio(envio_id)

    def ranking_de_rutas(
        self, limite: int = LIMITE_RANKING_POR_DEFECTO
    ) -> list[RutaConIncidentes]:
        """Rutas con mas incidentes. Se resuelve entero en MongoDB gracias al
        snapshot embebido: no hace falta reconstruir la ruta desde el grafo
        (D12)."""
        if limite <= 0:
            raise ValidacionError("El limite del ranking tiene que ser positivo")
        return self._incidentes.ranking_de_rutas(limite)

    def contar_por(
        self, agrupacion: AgrupacionIncidentes, limite: int | None = None
    ) -> list[ConteoIncidentes]:
        """Cantidad de incidentes por grupo, de mayor a menor."""
        conteos = self._incidentes.contar_agrupado(agrupacion, limite)
        if agrupacion is AgrupacionIncidentes.CLIENTE:
            conteos = self._resolver_clientes(conteos)
        return conteos

    def promedio_por(
        self, agrupacion: AgrupacionIncidentes
    ) -> list[PromedioIncidentes]:
        """Incidentes por envio de cada grupo.

        El numerador lo cuenta MongoDB con una agregacion; el denominador sale
        de PostgreSQL, que es el que sabe cuantos envios hay. Ninguna de las dos
        bases puede responder esto sola: por eso el promedio lo arma el
        servicio y no una consulta.
        """
        if agrupacion not in EJES_CON_PROMEDIO:
            ejes = ", ".join(e.value for e in EJES_CON_PROMEDIO)
            raise ValidacionError(
                f"No se puede promediar por {agrupacion.value}: PostgreSQL no "
                f"cuenta envios por ese eje. Ejes disponibles: {ejes}"
            )

        conteos = self._incidentes.contar_agrupado(agrupacion)
        etiquetas = {}
        if agrupacion is AgrupacionIncidentes.CLIENTE:
            etiquetas = self._razones_sociales()

        resultado = []
        with self._uow as uow:
            for conteo in conteos:
                envios = self._contar_envios(uow, agrupacion, conteo.grupo)
                resultado.append(
                    PromedioIncidentes(
                        grupo=etiquetas.get(conteo.grupo, conteo.grupo),
                        incidentes=conteo.cantidad,
                        envios=envios,
                    )
                )
        return sorted(resultado, key=lambda p: p.promedio, reverse=True)

    @staticmethod
    def _contar_envios(
        uow: UnidadDeTrabajo, agrupacion: AgrupacionIncidentes, grupo: str
    ) -> int:
        """Una consulta por grupo. Son pocos grupos (cuatro clientes, cinco
        estados), asi que no se arma un conteo agrupado en PostgreSQL solo para
        esto."""
        if agrupacion is AgrupacionIncidentes.CLIENTE:
            try:
                cliente_id = UUID(grupo)
            except ValueError as error:
                # MongoDB guarda el cliente como UUID: si llego otra cosa, el
                # documento esta mal y es mejor decirlo que promediar fruta.
                raise ValidacionError(
                    f"Un incidente tiene guardado {grupo!r} como cliente, que no "
                    "es un identificador valido"
                ) from error
            return len(uow.envios.listar_por_cliente(cliente_id))
        return len(uow.envios.listar_por_pais_destino(grupo))

    def _razones_sociales(self) -> dict[str, str]:
        """MongoDB guarda el cliente como UUID: la razon social vive en
        PostgreSQL y resolverla es tarea del servicio."""
        with self._uow as uow:
            return {str(c.id): c.razon_social for c in uow.clientes.listar()}

    def _resolver_clientes(
        self, conteos: list[ConteoIncidentes]
    ) -> list[ConteoIncidentes]:
        etiquetas = self._razones_sociales()
        return [
            ConteoIncidentes(
                grupo=etiquetas.get(c.grupo, c.grupo), cantidad=c.cantidad
            )
            for c in conteos
        ]
