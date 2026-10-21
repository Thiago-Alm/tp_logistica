"""Interfaz de persistencia de Envio. La implementa infrastructure/postgres.

Cada metodo sale de un requisito del enunciado. Los metodos reciben y devuelven
entidades de dominio, nunca filas ni diccionarios.

Lo que NO esta aca y por que:
- Los tramos de un envio: son de TramoRepository (D6). El servicio compone los
  dos repositorios cuando una consulta necesita el envio con su recorrido.
- Los reportes que devuelven agregados (conteos, promedios, rankings): son de
  ReporteEnvioRepository, porque no devuelven envios.
- Los eventos logisticos ("historial completo de eventos"): viven en Cassandra.
- Los incidentes y las predicciones: viven en MongoDB.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from logistica.domain.envio import Envio, EstadoEnvio


class EnvioRepository(ABC):
    # --- Escritura -------------------------------------------------------

    @abstractmethod
    def guardar(self, envio: Envio) -> None:
        """Alta de un envio nuevo. Requisito: "Registro de envios"."""
        ...

    @abstractmethod
    def actualizar(self, envio: Envio) -> None:
        """Persiste los cambios de un envio existente.

        No hay un metodo `cambiar_estado(id, estado)` (D18): el cambio de
        estado lo hace el dominio con `Envio.pasar_a()`, que valida la
        transicion, y despues el servicio guarda el envio entero con este
        metodo. Asi la regla de transiciones vive en un solo lugar (D4).
        """
        ...

    @abstractmethod
    def asociar_contenedor(self, envio_id: UUID, contenedor_id: UUID) -> None:
        """Agrega un contenedor al envio (tabla envio_contenedor).

        La relacion es N:M HISTORICA: el mismo contenedor puede haber viajado en
        varios envios a lo largo del tiempo. Que no este en dos envios ACTIVOS a
        la vez lo valida el servicio (D3), porque esa regla no se puede declarar
        en la base sin perder el historico.
        """
        ...

    @abstractmethod
    def listar_contenedores(self, envio_id: UUID) -> list[UUID]:
        """Ids de los contenedores asignados a un envio."""
        ...

    # --- Lectura puntual -------------------------------------------------

    @abstractmethod
    def obtener(self, id: UUID) -> Envio | None:
        """Devuelve None si no existe, en vez de lanzar: que falte puede ser un
        caso valido para quien llama."""
        ...

    @abstractmethod
    def listar_por_cliente(self, cliente_id: UUID) -> list[Envio]:
        """Requisito: "Envios por cliente" (reporte operativo)."""
        ...

    @abstractmethod
    def listar_por_estado(self, estado: EstadoEnvio) -> list[Envio]:
        """Requisito: "Envios por estado" (reporte operativo)."""
        ...

    @abstractmethod
    def listar_por_pais_destino(self, pais: str) -> list[Envio]:
        """Requisito: "Envios por pais" (reporte operativo).

        Supuesto: el pais es el del destino. El envio no guarda el pais: se
        resuelve a traves de `destino_id` -> `ubicacion.pais`.
        """
        ...

    @abstractmethod
    def listar_demorados(self, momento: datetime) -> list[Envio]:
        """Requisito: "Envios demorados" (reporte operativo).

        Demorado = no entregado y el maximo de `fecha_llegada_estimada` entre
        sus tramos es anterior a `momento` (D7). La fecha estimada no esta en
        `envio`: la implementacion la calcula agregando sobre `tramo`.

        `momento` se recibe por parametro en vez de usar `datetime.now()` para
        poder testearlo con una fecha fija.
        """
        ...
