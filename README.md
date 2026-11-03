# TP Persistencia Poliglota - Ingenieria de Datos II

Plataforma de logistica internacional y monitoreo de cargas con sensores IoT.
Aplicacion de consola en Python con 5 motores: PostgreSQL, MongoDB, Neo4j, Redis y Cassandra.

## Puesta en marcha
1. Copiar `.env.example` a `.env` y completar las claves.
2. Crear el entorno: `python -m venv .venv` y activarlo (Windows: `.venv\Scripts\activate`).
3. Instalar: `pip install -r requirements.txt` y luego `pip install -e .`
4. Levantar y verificar todo de una: `python scripts/preparar_demo.py`
   (levanta los contenedores, espera a que las 5 bases respondan y dice que
   hacer si alguna falla; con `--recargar` reaplica el esquema y los datos)
5. Correr los tests: `pytest`
6. Arrancar la aplicacion: `python -m logistica`
7. En otra terminal, los procesos periodicos: `python -m logistica.jobs.planificador`
   (Outbox cada 10 s, consistencia y saldos cada 30 min, deteccion de sensores
   inactivos cada 30 s, facturacion y prediccion de riesgos diarias, cierre
   mensual el dia 1)

El paso 4 tambien se puede hacer a mano: `docker compose up -d`,
`python scripts/chequear_conexiones.py` y `python scripts/aplicar_esquema.py`.

La contrasena de los cuatro usuarios de prueba es `demo1234`. Se entra con
`admin@logistica.com`; los otros tres tienen menos permisos y sirven para ver
como el menu se recorta segun el rol.

### Datos IoT
Las lecturas de sensores las genera el simulador, no los datos semilla:

    python -m logistica.jobs.simulador_iot --ciclos 30 --intervalo 0

Hace falta correrlo para que el recorrido GPS y las consultas de lecturas
devuelvan algo. A diferencia de los datos de PostgreSQL, que se cargan con
fechas relativas al dia de carga, las lecturas llevan la fecha real en que se
generaron: si pasan varios dias, las consultas por defecto -que miran los
ultimos 7- empiezan a devolver poco.

### Si el chequeo falla
Revisar `docker compose ps`. Ojo con un detalle que ya nos paso: un contenedor
puede figurar como "Up" y aun asi no ser el que recibe las conexiones, si hay
otro servicio de la maquina ocupando el mismo puerto (por ejemplo, un MongoDB o
un PostgreSQL instalado de antes en Windows). Por eso el chequeo imprime la
version: si no coincide con la del `docker-compose.yml`, le estas hablando a
otra base. La solucion es detener el servicio nativo, o mover el puerto del
contenedor y actualizar el `.env`.

## Estructura
- `scripts/`: scripts de creacion de cada base (uno por motor) y utilidades.
- `docs/decisiones.md`: registro de decisiones de diseno. **Leerlo antes de escribir codigo o DDL.**
- `src/logistica/domain/`: entidades.
- `src/logistica/repositories/`: interfaces (clases abstractas), sin codigo de base de datos.
- `src/logistica/infrastructure/`: implementaciones de cada interfaz, una carpeta por motor.
- `src/logistica/services/`: casos de uso.
- `src/logistica/sync/`: Outbox, worker de sincronizacion y chequeo de consistencia.
- `src/logistica/jobs/`: procesos periodicos. Se arrancan con
  `python -m logistica.jobs.planificador`.
- `src/logistica/cli/`: menus de la consola. Se arranca con `python -m logistica`.
- `src/logistica/container.py`: decide que implementacion usa cada interfaz.
- `tests/` y `docs/`.

## Reparto
- Thiago: esqueleto, Outbox y sincronizacion.
- Fran: PostgreSQL.
- Mati: MongoDB y Cassandra.
- Umbi: Redis, consultas de lectura en Neo4j, datos de prueba y diagramas.
