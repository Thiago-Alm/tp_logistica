"""Prediccion de atrasos: que envios en curso van a llegar tarde, y por que.

**No es machine learning, y es a proposito.** Con seis envios de prueba, un
modelo entrenado no tendria de donde aprender, y sobre todo no se podria
explicar: ante "por que este envio es de riesgo ALTO" la unica respuesta seria
"porque lo dijo el modelo".

Lo que hay es un **puntaje por factores observables**: cada senal suma puntos y
queda registrada con su motivo, asi que la prediccion viene con su propia
explicacion. Un operador puede discutirla, y es lo que se puede defender.

Los factores salen de datos que el sistema ya tiene:

- tramos que **ya llegaron tarde** (PostgreSQL): el atraso acumulado no es una
  estimacion, es un hecho, y se arrastra a los tramos que faltan;
- tramos **vencidos sin llegada** (PostgreSQL): estan tarde ahora mismo;
- **incidentes abiertos** del envio (MongoDB), pesados por su severidad.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

# Puntos de cada factor. Son constantes nombradas y no numeros sueltos para
# que el criterio se pueda discutir en un solo lugar.
PUNTOS_TRAMO_LLEGADO_TARDE = 2
PUNTOS_TRAMO_VENCIDO = 3
PUNTOS_INCIDENTE_ABIERTO = 2
PUNTOS_INCIDENTE_GRAVE = 3
PUNTOS_LLEGADA_VENCIDA = 4
PUNTOS_SIN_TRAMOS = 2
PUNTOS_RECORRIDO_COMPLETO_SIN_ENTREGA = 3

# Un envio sin ningun factor es BAJO. Los cortes son redondos a proposito: no
# hay nada que los calibre con seis envios, asi que inventar decimales seria
# fingir una precision que no existe.
CORTE_MEDIO = 1
CORTE_ALTO = 4
CORTE_CRITICO = 8


class NivelRiesgo(Enum):
    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"
    CRITICO = "CRITICO"

    @classmethod
    def desde_puntaje(cls, puntaje: int) -> "NivelRiesgo":
        if puntaje >= CORTE_CRITICO:
            return cls.CRITICO
        if puntaje >= CORTE_ALTO:
            return cls.ALTO
        if puntaje >= CORTE_MEDIO:
            return cls.MEDIO
        return cls.BAJO

    def necesita_atencion(self) -> bool:
        return self in (NivelRiesgo.ALTO, NivelRiesgo.CRITICO)


@dataclass(frozen=True)
class FactorDeRiesgo:
    """Una senal concreta, con su explicacion en palabras.

    El motivo es texto y no un codigo: lo que se muestra es la razon, y
    traducir un codigo a una frase seria otra tabla para mantener.
    """

    motivo: str
    puntos: int


@dataclass(frozen=True)
class PrediccionAtraso:
    """Lo que se proyecta para un envio en curso.

    `atraso_proyectado` NO sale del puntaje: sale del atraso que el envio ya
    acumulo en sus tramos. El puntaje mide **riesgo**; el atraso proyectado
    mide **tiempo**, y mezclarlos daria un numero de dias inventado.
    """

    envio_id: UUID
    cliente_id: UUID
    estado: str
    ruta: str
    llegada_estimada: datetime | None
    atraso_acumulado: timedelta
    factores: tuple[FactorDeRiesgo, ...] = ()

    @property
    def puntaje(self) -> int:
        return sum(f.puntos for f in self.factores)

    @property
    def nivel(self) -> NivelRiesgo:
        return NivelRiesgo.desde_puntaje(self.puntaje)

    @property
    def llegada_proyectada(self) -> datetime | None:
        """La estimada corrida por el atraso que ya se acumulo.

        Sin tramos no hay fecha estimada y tampoco proyectada: no se inventa
        una, se informa que falta cargar el recorrido.
        """
        if self.llegada_estimada is None:
            return None
        return self.llegada_estimada + self.atraso_acumulado

    @property
    def motivos(self) -> tuple[str, ...]:
        return tuple(f.motivo for f in self.factores)
