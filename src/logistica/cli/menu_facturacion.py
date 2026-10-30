"""Menu de facturacion, pagos y cuentas corrientes."""
from decimal import Decimal, InvalidOperation
from uuid import UUID

from logistica.cli import consola
from logistica.domain.facturacion import MedioPago, TitularTipo
from logistica.exceptions import LogisticaError
from logistica.services.cliente_service import ClienteService
from logistica.services.facturacion_service import FacturacionService
from logistica.services.parte_service import ServicioDeParte


def _elegir(opciones: list, etiqueta, titulo: str):
    consola.tabla(["#", titulo], [[str(i), etiqueta(o)] for i, o in enumerate(opciones, 1)])
    texto = consola.pedir(f"Numero de {titulo.lower()}")
    if not texto.isdigit() or not 1 <= int(texto) <= len(opciones):
        consola.error("Opcion invalida.")
        return None
    return opciones[int(texto) - 1]


def _pedir_decimal(etiqueta: str) -> Decimal | None:
    try:
        return Decimal(consola.pedir(etiqueta))
    except InvalidOperation:
        consola.error("Importe invalido.")
        return None


def construir(
    servicio: FacturacionService,
    clientes: ClienteService,
    proveedores: ServicioDeParte,
    operadores: ServicioDeParte,
) -> None:
    partes_por_tipo = {
        TitularTipo.CLIENTE: clientes,
        TitularTipo.PROVEEDOR: proveedores,
        TitularTipo.OPERADOR: operadores,
    }

    def _nombres() -> dict:
        """Razon social de cada titular, de los tres tipos.

        La cuenta corriente guarda `titular_tipo` + `titular_id` y no tiene
        clave foranea, porque apunta a tres tablas distintas (D41): resolver
        el nombre es tarea de quien muestra.
        """
        nombres = {}
        for servicio_parte in partes_por_tipo.values():
            for parte in servicio_parte.listar():
                nombres[parte.id] = parte.razon_social
        return nombres

    def _elegir_titular() -> tuple[TitularTipo, UUID] | None:
        """Los tres tipos se eligen de una lista por razon social.

        Antes solo el cliente: operadores y proveedores pedian el UUID a mano
        porque no tenian su propio ABM. Ahora lo tienen, asi que facturarle a un
        operador es tan directo como facturarle a un cliente.
        """
        tipo = _elegir(list(TitularTipo), lambda t: t.value, "Tipo de titular")
        if tipo is None:
            return None
        try:
            partes = partes_por_tipo[tipo].listar()
        except LogisticaError as error:
            consola.error(str(error))
            return None
        if not partes:
            consola.error(f"No hay {tipo.value.lower()}es cargados.")
            return None
        parte = _elegir(partes, lambda x: x.razon_social, tipo.value.capitalize())
        return (tipo, parte.id) if parte else None

    def listar_cuentas() -> None:
        consola.titulo("Cuentas corrientes")
        consola.aviso("El saldo es negativo cuando el titular debe.")
        nombres = _nombres()
        consola.tabla(
            ["TIPO", "TITULAR", "SALDO", "DEUDA", "LIMITE", "DISPONIBLE"],
            [
                [
                    c.titular_tipo.value,
                    nombres.get(c.titular_id, str(c.titular_id)[:8]),
                    f"{c.saldo:.2f}",
                    f"{c.deuda:.2f}",
                    f"{c.limite_credito:.2f}",
                    f"{c.credito_disponible():.2f}",
                ]
                for c in servicio.listar_cuentas()
            ],
        )

    def estado_de_cuenta() -> None:
        consola.titulo("Estado de cuenta")
        titular = _elegir_titular()
        if titular is None:
            return
        try:
            estado = servicio.estado_de_cuenta(*titular)
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.aviso(
            f"Saldo {estado.cuenta.saldo:.2f}  deuda {estado.cuenta.deuda:.2f}  "
            f"disponible {estado.cuenta.credito_disponible():.2f}"
        )
        consola.tabla(
            ["FECHA", "TIPO", "MONTO", "DESCRIPCION"],
            [
                [
                    m.fecha.strftime("%Y-%m-%d"),
                    m.tipo.value,
                    f"{m.monto:.2f}",
                    m.descripcion[:46],
                ]
                for m in estado.movimientos
            ],
        )
        if not estado.saldo_coincide:
            consola.error("El saldo guardado NO coincide con la suma de los movimientos.")

    def abrir_cuenta() -> None:
        consola.titulo("Abrir cuenta corriente")
        titular = _elegir_titular()
        if titular is None:
            return
        limite = _pedir_decimal("Limite de credito")
        if limite is None:
            return
        try:
            cuenta = servicio.abrir_cuenta(*titular, limite)
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(f"Cuenta abierta: {cuenta.id}")

    def emitir() -> None:
        consola.titulo("Emitir factura")
        titular = _elegir_titular()
        if titular is None:
            return
        importe = _pedir_decimal("Importe")
        if importe is None:
            return
        try:
            factura = servicio.emitir(*titular, importe, consola.pedir("Concepto"))
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(f"Factura {factura.numero_factura} por {factura.importe_total:.2f}")

    def listar_facturas() -> None:
        consola.titulo("Facturas de un titular")
        titular = _elegir_titular()
        if titular is None:
            return
        consola.tabla(
            ["NUMERO", "EMISION", "VENCIMIENTO", "IMPORTE", "ESTADO"],
            [
                [
                    f.numero_factura,
                    f.fecha_emision.strftime("%Y-%m-%d"),
                    f.fecha_vencimiento.strftime("%Y-%m-%d"),
                    f"{f.importe_total:.2f}",
                    f.estado.value,
                ]
                for f in servicio.listar_facturas(*titular)
            ],
        )

    def registrar_pago() -> None:
        consola.titulo("Registrar pago")
        titular = _elegir_titular()
        if titular is None:
            return
        pendientes = [f for f in servicio.listar_facturas(*titular) if f.esta_pendiente()]
        if not pendientes:
            consola.aviso("Ese titular no tiene facturas pendientes.")
            return
        factura = _elegir(
            pendientes,
            lambda f: f"{f.numero_factura}  {f.importe_total:.2f}  {f.estado.value}",
            "Factura",
        )
        if factura is None:
            return
        monto = _pedir_decimal("Monto del pago")
        if monto is None:
            return
        medio = _elegir(list(MedioPago), lambda m: m.value, "Medio de pago")
        if medio is None:
            return
        try:
            servicio.registrar_pago(
                factura.id, monto, medio, consola.pedir_opcional("Referencia")
            )
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(
            f"Pago registrado. La factura quedo "
            f"{servicio.obtener_factura(factura.id).estado.value}."
        )

    def facturar_entregados() -> None:
        consola.titulo("Facturacion automatica")
        consola.aviso("Factura los envios ENTREGADOS que todavia no tienen factura.")
        emitidas = servicio.facturar_entregados()
        if not emitidas:
            consola.aviso("No habia envios pendientes de facturar.")
            return
        consola.tabla(
            ["NUMERO", "IMPORTE", "ENVIO"],
            [[f.numero_factura, f"{f.importe_total:.2f}", str(f.envio_id)[:8]] for f in emitidas],
        )

    def cerrar_mes() -> None:
        consola.titulo("Cierre mensual de cuentas corrientes")
        r = servicio.cerrar_mes()
        consola.tabla(
            ["CONCEPTO", "VALOR"],
            [
                ["Cuentas revisadas", str(r.cuentas_revisadas)],
                ["Facturas marcadas vencidas", str(r.facturas_vencidas)],
                ["Cuentas con deuda", str(r.cuentas_con_deuda)],
                ["Deuda total", f"{r.deuda_total:.2f}"],
            ],
        )

    def verificar() -> None:
        consola.titulo("Control de integridad de saldos")
        consola.aviso("Compara el saldo guardado con la suma de los movimientos.")
        diferencias = servicio.verificar_saldos()
        if not diferencias:
            consola.exito("Todos los saldos cuadran.")
            return
        consola.tabla(
            ["CUENTA", "GUARDADO", "CALCULADO"],
            [[str(c.id)[:8], f"{c.saldo:.2f}", f"{calc:.2f}"] for c, calc in diferencias],
        )

    def seguro(funcion):
        def envoltorio() -> None:
            try:
                funcion()
            except LogisticaError as e:
                consola.error(str(e))

        return envoltorio

    consola.menu(
        "Facturacion y cuentas corrientes",
        {
            "1": ("Listar cuentas corrientes", seguro(listar_cuentas)),
            "2": ("Estado de cuenta", seguro(estado_de_cuenta)),
            "3": ("Abrir cuenta corriente", seguro(abrir_cuenta)),
            "4": ("Emitir factura", seguro(emitir)),
            "5": ("Listar facturas de un titular", seguro(listar_facturas)),
            "6": ("Registrar pago", seguro(registrar_pago)),
            "7": ("Facturacion automatica de entregados", seguro(facturar_entregados)),
            "8": ("Cierre mensual", seguro(cerrar_mes)),
            "9": ("Verificar saldos (integridad)", seguro(verificar)),
        },
    )
