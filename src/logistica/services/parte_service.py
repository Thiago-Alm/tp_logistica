"""Casos de uso de Proveedor y Operador logistico.

Los dos hacen lo mismo —alta, baja, modificacion, reactivacion— sobre tablas de
la misma forma, asi que comparten la logica y cada uno declara solo con que
repositorio trabaja y como construye su entidad. Repetir el mismo servicio dos
veces seria duplicar tambien sus reglas, y una se arreglaria sin la otra.

A diferencia de `ClienteService`, estos **no publican eventos al Outbox**: el
grafo de Neo4j proyecta clientes, envios, tramos y operadores a traves de los
eventos de envio (D37), y ni el alta de un proveedor ni la de un operador
cambian por si solas una relacion del grafo. Cuando ese operador participe de
un envio, el evento de ese envio es el que lo proyecta.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from logistica.domain.partes import EstadoParte, Operador, ParteComercial, Proveedor
from logistica.exceptions import ConflictoDeDatos, NoEncontrado
from logistica.repositories.unidad_de_trabajo import UnidadDeTrabajo

log = logging.getLogger(__name__)


class ServicioDeParte:
    """Lo que comparten proveedores y operadores.

    El servicio es el unico que decide que hora es y que id se genera, igual
    que `ClienteService`, y el unico que valida lo que necesita consultar la
    base (D3): que el CUIT no este repetido.
    """

    singular: str

    def __init__(self, unidad_de_trabajo: UnidadDeTrabajo) -> None:
        self._uow = unidad_de_trabajo

    def _repo(self, uow: UnidadDeTrabajo):
        raise NotImplementedError

    def _construir(self, **datos) -> ParteComercial:
        raise NotImplementedError

    def alta(
        self,
        cuit: str,
        razon_social: str,
        email: str,
        pais: str,
        telefono: str | None = None,
        **extra,
    ) -> ParteComercial:
        parte = self._construir(
            id=uuid4(),
            cuit=cuit,
            razon_social=razon_social,
            email=email,
            pais=pais,
            telefono=telefono,
            fecha_creacion=datetime.now(timezone.utc),
            **extra,
        )
        with self._uow as uow:
            if self._repo(uow).obtener_por_cuit(cuit) is not None:
                raise ConflictoDeDatos(
                    f"Ya existe un {self.singular} con CUIT {cuit}"
                )
            self._repo(uow).guardar(parte)
            uow.commit()
        log.info("%s dado de alta: %s (%s)", self.singular.capitalize(),
                 parte.razon_social, parte.id)
        return parte

    def obtener(self, id: UUID) -> ParteComercial:
        with self._uow as uow:
            parte = self._repo(uow).obtener(id)
        if parte is None:
            raise NoEncontrado(f"No existe el {self.singular} {id}")
        return parte

    def listar(self, solo_activos: bool = False) -> list[ParteComercial]:
        with self._uow as uow:
            return self._repo(uow).listar(EstadoParte.ACTIVO if solo_activos else None)

    def buscar_por_cuit(self, cuit: str) -> ParteComercial:
        with self._uow as uow:
            parte = self._repo(uow).obtener_por_cuit(cuit)
        if parte is None:
            raise NoEncontrado(f"No existe un {self.singular} con CUIT {cuit}")
        return parte

    def modificar(self, id: UUID, **cambios) -> ParteComercial:
        """Solo cambia los campos que vienen con valor. El CUIT no se modifica:
        es la identidad fiscal y lo referencian las cuentas corrientes."""
        with self._uow as uow:
            parte = self._repo(uow).obtener(id)
            if parte is None:
                raise NoEncontrado(f"No existe el {self.singular} {id}")
            for campo, valor in cambios.items():
                if valor is not None:
                    setattr(parte, campo, valor)
            # Revalida la entidad completa: un setattr se saltea __post_init__.
            parte.validar()
            self._repo(uow).actualizar(parte)
            uow.commit()
        return parte

    def baja(self, id: UUID) -> ParteComercial:
        """Baja logica (D26): no se borra la fila porque la referencian su
        cuenta corriente y sus movimientos."""
        return self._cambiar_estado(id, dar_de_baja=True)

    def reactivar(self, id: UUID) -> ParteComercial:
        return self._cambiar_estado(id, dar_de_baja=False)

    def _cambiar_estado(self, id: UUID, dar_de_baja: bool) -> ParteComercial:
        with self._uow as uow:
            parte = self._repo(uow).obtener(id)
            if parte is None:
                raise NoEncontrado(f"No existe el {self.singular} {id}")
            parte.dar_de_baja() if dar_de_baja else parte.reactivar()
            self._repo(uow).actualizar(parte)
            uow.commit()
        return parte


class OperadorService(ServicioDeParte):
    singular = "operador"

    def _repo(self, uow: UnidadDeTrabajo):
        return uow.operadores

    def _construir(self, **datos) -> Operador:
        return Operador(**datos)


class ProveedorService(ServicioDeParte):
    singular = "proveedor"

    def _repo(self, uow: UnidadDeTrabajo):
        return uow.proveedores

    def _construir(self, **datos) -> Proveedor:
        return Proveedor(**datos)
