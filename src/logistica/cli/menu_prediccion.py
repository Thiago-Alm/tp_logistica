"""Menu de prediccion de atrasos y analisis de riesgos."""

from logistica.cli import consola
from logistica.cli.permisos import NIVEL_ADMINISTRADOR, NIVEL_AUDITOR, opciones_para
from logistica.domain.prediccion import PrediccionAtraso
from logistica.exceptions import LogisticaError
from logistica.services.prediccion_service import PrediccionService


def _fecha(valor) -> str:
    return "-" if valor is None else f"{valor.astimezone():%d/%m/%Y %H:%M}"


def _mostrar(predicciones: list[PrediccionAtraso], nombres: dict) -> None:
    consola.tabla(
        ["RUTA", "CLIENTE", "ESTADO", "RIESGO", "PTS", "ESTIMADA", "PROYECTADA"],
        [
            [
                p.ruta,
                nombres.get(p.cliente_id, str(p.cliente_id)[-12:])[:22],
                p.estado,
                p.nivel.value,
                str(p.puntaje),
                _fecha(p.llegada_estimada),
                _fecha(p.llegada_proyectada),
            ]
            for p in predicciones
        ],
    )


def construir(
    servicio: PrediccionService, clientes, rol_nivel: int = NIVEL_ADMINISTRADOR
) -> None:
    def _nombres() -> dict:
        try:
            return {c.id: c.razon_social for c in clientes.listar()}
        except LogisticaError:
            return {}

    def listar() -> None:
        consola.titulo("Prediccion de atrasos")
        consola.aviso(
            "No es un modelo entrenado: es un puntaje por factores observables, "
            "y cada envio viene con los motivos de su riesgo (D55)."
        )
        try:
            predicciones = servicio.predecir_atrasos()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not predicciones:
            consola.aviso("No hay envios en curso.")
            return
        _mostrar(predicciones, _nombres())
        atencion = [p for p in predicciones if p.nivel.necesita_atencion()]
        if atencion:
            consola.error(f"{len(atencion)} envio(s) necesitan atencion.")
        else:
            consola.exito("Ningun envio en curso con riesgo alto.")

    def detalle() -> None:
        consola.titulo("Por que un envio es de riesgo")
        try:
            predicciones = servicio.predecir_atrasos()
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not predicciones:
            consola.aviso("No hay envios en curso.")
            return

        nombres = _nombres()
        consola.tabla(
            ["#", "RUTA", "CLIENTE", "RIESGO"],
            [
                [
                    str(i),
                    p.ruta,
                    nombres.get(p.cliente_id, str(p.cliente_id)[-12:])[:22],
                    p.nivel.value,
                ]
                for i, p in enumerate(predicciones, 1)
            ],
        )
        eleccion = consola.pedir("Numero del envio").strip()
        if not eleccion.isdigit() or not 1 <= int(eleccion) <= len(predicciones):
            consola.error("Envio invalido.")
            return
        prediccion = predicciones[int(eleccion) - 1]

        consola.aviso(f"Envio {prediccion.envio_id}")
        consola.aviso(
            f"Estimada {_fecha(prediccion.llegada_estimada)} -> "
            f"proyectada {_fecha(prediccion.llegada_proyectada)}"
        )
        if not prediccion.factores:
            consola.exito("Sin senales de atraso.")
            return
        consola.tabla(
            ["MOTIVO", "PUNTOS"],
            [[f.motivo, str(f.puntos)] for f in prediccion.factores],
        )
        consola.aviso(
            f"Total: {prediccion.puntaje} puntos -> riesgo {prediccion.nivel.value}"
        )

    def resumen() -> None:
        consola.titulo("Analisis de riesgos de la operacion")
        try:
            conteo = servicio.resumen_por_nivel()
        except LogisticaError as error:
            consola.error(str(error))
            return
        total = sum(conteo.values())
        if not total:
            consola.aviso("No hay envios en curso.")
            return
        consola.tabla(
            ["NIVEL", "ENVIOS", "PROPORCION"],
            [
                [nivel.value, str(cantidad), f"{cantidad / total:.0%}"]
                for nivel, cantidad in conteo.items()
            ],
        )
        en_riesgo = sum(c for n, c in conteo.items() if n.necesita_atencion())
        consola.aviso(f"{en_riesgo} de {total} envios en curso necesitan atencion.")

    def solo_criticos() -> None:
        consola.titulo("Envios que necesitan atencion")
        try:
            predicciones = [
                p for p in servicio.predecir_atrasos() if p.nivel.necesita_atencion()
            ]
        except LogisticaError as error:
            consola.error(str(error))
            return
        if not predicciones:
            consola.exito("Ningun envio en curso con riesgo alto o critico.")
            return
        _mostrar(predicciones, _nombres())

    secciones = [
        (NIVEL_AUDITOR, "Prediccion de atrasos de todos los envios", listar),
        (NIVEL_AUDITOR, "Envios que necesitan atencion", solo_criticos),
        (NIVEL_AUDITOR, "Por que un envio es de riesgo", detalle),
        (NIVEL_AUDITOR, "Analisis de riesgos de la operacion", resumen),
    ]
    consola.menu("Prediccion de atrasos y riesgos", opciones_para(rol_nivel, secciones))
