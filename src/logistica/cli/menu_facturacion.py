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

    def _titulares_con_cuenta() -> set:
        """Los (tipo, id) que hoy tienen cuenta corriente abierta."""
        return {(c.titular_tipo, c.titular_id) for c in servicio.listar_cuentas()}

    def _elegir_titular(con_cuenta: bool | None = None) -> tuple[TitularTipo, UUID] | None:
        """Los tres tipos se eligen de una lista por razon social.

        `con_cuenta` recorta la lista segun para que se la pida:

        - `True`  -> solo los que ya tienen cuenta (facturar, cobrar, consultar)
        - `False` -> solo los que no la tienen (abrir cuenta)
        - `None`  -> todos

        Sin ese recorte el menu ofrecia titulares con los que la operacion no
        podia terminar: aparecia un proveedor sin cuenta para facturarle, o uno
        que ya la tenia para abrirsela. El error llegaba recien al final, del
        servicio. Es mejor no ofrecer lo que no se puede hacer.
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

        if con_cuenta is not None:
            try:
                con_cuenta_hoy = _titulares_con_cuenta()
            except LogisticaError as error:
                consola.error(str(error))
                return None
            partes = [
                x for x in partes if ((tipo, x.id) in con_cuenta_hoy) is con_cuenta
            ]
            if not partes:
                consola.aviso(
                    f"No hay {tipo.value.lower()}es "
                    + ("con" if con_cuenta else "sin")
                    + " cuenta corriente."
                )
                if not con_cuenta:
                    consola.aviso("Todos los de ese tipo ya tienen una.")
                else:
                    consola.aviso("Primero hay que abrirsela (opcion 3).")
                return None

        parte = _elegir(partes, lambda x: x.razon_social, tipo.value.capitalize())
        return (tipo, parte.id) if parte else None

    def listar_cuentas() -> None:
        consola.titulo("Cuentas corrientes")
        consola.aviso(
            "Cliente y operador son cuentas por COBRAR: el saldo en rojo es lo "
            "que nos deben."
        )
        consola.aviso(
            "Proveedor es cuenta por PAGAR: el saldo en rojo es lo que le "
            "debemos nosotros."
        )
        nombres = _nombres()
        consola.tabla(
            ["TIPO", "TITULAR", "SALDO", "NOS DEBE", "LE DEBEMOS", "LIMITE", "DISPONIBLE"],
            [
                [
                    c.titular_tipo.value,
                    nombres.get(c.titular_id, str(c.titular_id)[:8]),
                    f"{c.saldo:.2f}",
                    "-" if c.es_por_pagar() else f"{c.deuda:.2f}",
                    f"{c.a_pagar:.2f}" if c.es_por_pagar() else "-",
                    f"{c.limite_credito:.2f}" if c.tiene_limite() else "SIN LIMITE",
                    f"{c.credito_disponible():.2f}" if c.tiene_limite() else "-",
                ]
                for c in servicio.listar_cuentas()
            ],
        )

    def estado_de_cuenta() -> None:
        consola.titulo("Estado de cuenta")
        titular = _elegir_titular(con_cuenta=True)
        if titular is None:
            return
        try:
            estado = servicio.estado_de_cuenta(*titular)
        except LogisticaError as e:
            consola.error(str(e))
            return
        cuenta = estado.cuenta
        if cuenta.es_por_pagar():
            consola.aviso(
                f"Cuenta por PAGAR. Saldo {cuenta.saldo:.2f}  "
                f"le debemos {cuenta.a_pagar:.2f}  sin limite de credito"
            )
        else:
            consola.aviso(
                f"Cuenta por COBRAR. Saldo {cuenta.saldo:.2f}  "
                f"nos debe {cuenta.deuda:.2f}  "
                f"disponible {cuenta.credito_disponible():.2f}"
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
        titular = _elegir_titular(con_cuenta=False)
        if titular is None:
            return
        if titular[0] is TitularTipo.PROVEEDOR:
            # No se le pide un limite que no se le va a aplicar.
            consola.aviso("El proveedor no lleva limite de credito: se abre sin tope.")
            limite = Decimal("0")
        else:
            limite = _pedir_decimal("Limite de credito")
            if limite is None:
                return
        try:
            cuenta = servicio.abrir_cuenta(*titular, limite)
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(f"Cuenta abierta: {cuenta.id}")

    def cambiar_limite() -> None:
        consola.titulo("Cambiar el limite de credito")
        titular = _elegir_titular(con_cuenta=True)
        if titular is None:
            return
        try:
            cuenta = servicio.estado_de_cuenta(*titular).cuenta
        except LogisticaError as e:
            consola.error(str(e))
            return
        if not cuenta.tiene_limite():
            consola.error(
                "Una cuenta de PROVEEDOR es por pagar y no lleva limite (D62)."
            )
            return
        consola.aviso(
            f"Limite actual {cuenta.limite_credito:.2f}  "
            f"nos debe {cuenta.deuda:.2f}  "
            f"disponible {cuenta.credito_disponible():.2f}"
        )
        nuevo = _pedir_decimal("Nuevo limite de credito")
        if nuevo is None:
            return
        try:
            cuenta = servicio.cambiar_limite(*titular, nuevo)
        except LogisticaError as e:
            consola.error(str(e))
            return
        consola.exito(
            f"Limite actualizado a {cuenta.limite_credito:.2f}. "
            f"Disponible: {cuenta.credito_disponible():.2f}"
        )

    def emitir() -> None:
        consola.titulo("Emitir factura")
        titular = _elegir_titular(con_cuenta=True)
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
        titular = _elegir_titular(con_cuenta=True)
        if titular is None:
            return
        resumen = servicio.resumen_de_facturas(*titular)
        if not resumen.lineas:
            consola.aviso("Ese titular no tiene facturas.")
            return
        # Cada factura con su detalle: lo emitido, lo cobrado y lo que falta.
        # El total de abajo es exactamente la suma de esta columna.
        consola.tabla(
            ["NUMERO", "EMISION", "VENCIMIENTO", "IMPORTE", "COBRADO",
             "PENDIENTE", "ESTADO"],
            [
                [
                    x.factura.numero_factura,
                    x.factura.fecha_emision.strftime("%Y-%m-%d"),
                    x.factura.fecha_vencimiento.strftime("%Y-%m-%d"),
                    f"{x.factura.importe_total:.2f}",
                    f"{x.pagado:.2f}",
                    f"{x.pendiente:.2f}",
                    x.factura.estado.value,
                ]
                for x in resumen.lineas
            ],
        )
        consola.titulo("Totales")
        filas = [
            ["Facturado", f"{resumen.total_facturado:.2f}", "sin contar las anuladas"],
            ["Cobrado", f"{resumen.total_cobrado:.2f}", "pagos registrados"],
            ["Pendiente", f"{resumen.total_pendiente:.2f}", "lo que falta cobrar"],
        ]
        if resumen.total_anulado:
            filas.append(
                ["Anulado", f"{resumen.total_anulado:.2f}", "queda en el historial"]
            )
        consola.tabla(["CONCEPTO", "IMPORTE", "DETALLE"], filas)

    def registrar_pago() -> None:
        consola.titulo("Registrar pago")
        titular = _elegir_titular(con_cuenta=True)
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
            "4": ("Cambiar el limite de credito", seguro(cambiar_limite)),
            "5": ("Emitir factura", seguro(emitir)),
            "6": ("Listar facturas de un titular", seguro(listar_facturas)),
            "7": ("Registrar pago", seguro(registrar_pago)),
            "8": ("Facturacion automatica de entregados", seguro(facturar_entregados)),
            "9": ("Cierre mensual", seguro(cerrar_mes)),
            "10": ("Verificar saldos (integridad)", seguro(verificar)),
        },
    )
