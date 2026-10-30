"""Casos de uso de Contenedor: alta, baja, modificacion y cambio de estado.

El contenedor ya se usaba desde el envio (asignarlo, sacarlo) y desde el
monitoreo (sus sensores, su recorrido GPS), pero no tenia su propio ABM: solo
existian los de la semilla.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from logistica.domain.contenedor import Contenedor, EstadoContenedor
from logistica.exceptions import ConflictoDeDatos, NoEncontrado, ValidacionError
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo
from logistica.sync import eventos

log = logging.getLogger(__name__)

# Tipos de la semilla. No es un enum porque el catalogo de tipos lo define el
# negocio y cambia sin tocar codigo: el CHECK de la base tampoco los limita.
TIPOS_CONOCIDOS = (
    "DRY_20", "DRY_40", "REEFER_20", "REEFER_40",
    "OPEN_TOP_40", "FLAT_RACK_40", "TANK_20",
)


class ContenedorService:
    def __init__(self, unidad_de_trabajo: UnidadDeTrabajo) -> None:
        self._uow = unidad_de_trabajo

    def alta(
        self,
        codigo_iso: str,
        tipo: str,
        capacidad: float,
        estado: EstadoContenedor = EstadoContenedor.DISPONIBLE,
    ) -> Contenedor:
        contenedor = Contenedor(
            id=uuid4(),
            codigo_iso=codigo_iso.strip().upper(),
            tipo=tipo.strip().upper(),
            capacidad=capacidad,
            estado=estado,
        )
        with self._uow as uow:
            if uow.contenedores.obtener_por_codigo(contenedor.codigo_iso) is not None:
                raise ConflictoDeDatos(
                    f"Ya existe un contenedor con codigo {contenedor.codigo_iso}"
                )
            uow.contenedores.guardar(contenedor)
            # El contenedor es un nodo del grafo: el evento viaja en la misma
            # transaccion que el dato (D34).
            uow.outbox.guardar(eventos.contenedor_creado(contenedor, datetime.now(timezone.utc)))
            uow.commit()
        log.info("Contenedor dado de alta: %s (%s)", contenedor.codigo_iso, contenedor.id)
        return contenedor

    def obtener(self, id: UUID) -> Contenedor:
        with self._uow as uow:
            contenedor = uow.contenedores.obtener(id)
        if contenedor is None:
            raise NoEncontrado(f"No existe el contenedor {id}")
        return contenedor

    def buscar(self, texto: str) -> Contenedor:
        """Por codigo ISO o por UUID, igual que en el recorrido GPS (D45)."""
        texto = texto.strip()
        with self._uow as uow:
            try:
                contenedor = uow.contenedores.obtener(UUID(texto))
            except ValueError:
                contenedor = uow.contenedores.obtener_por_codigo(texto.upper())
        if contenedor is None:
            raise NoEncontrado(f"No existe un contenedor con ID o codigo {texto!r}")
        return contenedor

    def listar(self, estado: EstadoContenedor | None = None) -> list[Contenedor]:
        with self._uow as uow:
            if estado is None:
                return uow.contenedores.listar()
            return uow.contenedores.listar_por_estado(estado)

    def modificar(
        self,
        id: UUID,
        tipo: str | None = None,
        capacidad: float | None = None,
    ) -> Contenedor:
        """El codigo ISO no se modifica: identifica fisicamente al contenedor,
        esta impreso en el, y lo referencian las lecturas de Cassandra y los
        nodos del grafo. Cambiarlo seria otro contenedor."""
        with self._uow as uow:
            contenedor = uow.contenedores.obtener(id)
            if contenedor is None:
                raise NoEncontrado(f"No existe el contenedor {id}")
            if tipo is not None:
                contenedor.tipo = tipo.strip().upper()
            if capacidad is not None:
                contenedor.capacidad = capacidad
            # Un setattr se saltea __post_init__: hay que revalidar entero.
            contenedor.validar()
            uow.contenedores.actualizar(contenedor)
            uow.outbox.guardar(eventos.contenedor_creado(contenedor, datetime.now(timezone.utc)))
            uow.commit()
        return contenedor

    def cambiar_estado(self, id: UUID, nuevo: EstadoContenedor) -> Contenedor:
        """Cambio administrativo: mandarlo a mantenimiento, darlo de baja o
        devolverlo a disponible.

        No se permite poner a mano los estados que los asigna un envio
        (ASIGNADO, EN_TRANSITO): esos los maneja `EnvioService`, que ademas
        escribe la fila de `envio_contenedor` en la misma transaccion (D28).
        Ponerlos desde aca dejaria un contenedor marcado como ocupado sin
        ningun envio que lo tenga.
        """
        if nuevo.esta_ocupado():
            raise ValidacionError(
                f"{nuevo.value} lo pone el envio al asignar el contenedor, no "
                "el ABM. Usa el menu de envios."
            )
        with self._uow as uow:
            contenedor = uow.contenedores.obtener(id)
            if contenedor is None:
                raise NoEncontrado(f"No existe el contenedor {id}")
            if contenedor.estado.esta_ocupado():
                raise ConflictoDeDatos(
                    f"El contenedor {contenedor.codigo_iso} esta "
                    f"{contenedor.estado.value}: sacalo del envio primero"
                )
            contenedor.estado = nuevo
            uow.contenedores.actualizar(contenedor)
            uow.outbox.guardar(eventos.contenedor_creado(contenedor, datetime.now(timezone.utc)))
            uow.commit()
        log.info("Contenedor %s paso a %s", contenedor.codigo_iso, nuevo.value)
        return contenedor

    def baja(self, id: UUID) -> Contenedor:
        """Baja logica (D26): la fila queda, porque la referencian los envios
        en los que viajo y sus lecturas en Cassandra."""
        return self.cambiar_estado(id, EstadoContenedor.BAJA)
