"""Menu de sincronizacion entre motores: Outbox, worker y consistencia."""
from logistica.cli import consola
from logistica.exceptions import LogisticaError
from logistica.sync.consistencia import ChequeoDeConsistencia
from logistica.sync.worker import WorkerDeSincronizacion


def construir(worker: WorkerDeSincronizacion, chequeo: ChequeoDeConsistencia) -> None:
    def propagar() -> None:
        consola.titulo("Propagar eventos pendientes")
        consola.aviso("Toma los eventos del Outbox y los proyecta sobre el grafo.")
        resultado = worker.procesar_tanda()
        consola.tabla(
            ["RESULTADO", "CANTIDAD"],
            [
                ["Procesados", str(resultado.procesados)],
                ["Fallidos", str(resultado.fallidos)],
                ["Pospuestos (backoff)", str(resultado.pospuestos)],
                ["Vencidos", str(resultado.vencidos)],
            ],
        )
        for error in resultado.errores[:5]:
            consola.error(error)

    def verificar() -> None:
        consola.titulo("Chequeo de consistencia")
        reporte = chequeo.verificar()
        for linea in reporte.resumen():
            print(f"  {linea}")

    def reconstruir() -> None:
        consola.titulo("Reconstruir el grafo desde PostgreSQL")
        consola.aviso("El grafo no contiene datos originales: se puede rearmar entero.")
        borrar = consola.confirmar("Vaciarlo antes? (necesario para borrar sobrantes)")
        proyectados = chequeo.reconstruir(borrar_antes=borrar)
        consola.tabla(
            ["TIPO", "PROYECTADOS"],
            [[a.value, str(c)] for a, c in proyectados.items()],
        )
        consola.exito("Grafo reconstruido.")

    def seguro(funcion):
        def envoltorio() -> None:
            try:
                funcion()
            except LogisticaError as e:
                consola.error(str(e))

        return envoltorio

    consola.menu(
        "Sincronizacion entre motores",
        {
            "1": ("Propagar eventos pendientes (Outbox -> Neo4j)", seguro(propagar)),
            "2": ("Verificar consistencia", seguro(verificar)),
            "3": ("Reconstruir el grafo desde PostgreSQL", seguro(reconstruir)),
        },
    )
