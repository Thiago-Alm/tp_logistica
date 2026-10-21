# TP Persistencia Poliglota - Ingenieria de Datos II

Plataforma de logistica internacional y monitoreo de cargas con sensores IoT.
Aplicacion de consola en Python con 5 motores: PostgreSQL, MongoDB, Neo4j, Redis y Cassandra.

## Puesta en marcha
1. Copiar `.env.example` a `.env` y completar las claves.
2. Crear el entorno: `python -m venv .venv` y activarlo (Windows: `.venv\Scripts\activate`).
3. Instalar: `pip install -r requirements.txt` y luego `pip install -e .`
4. Levantar las bases: `docker compose up -d`
5. Verificar que las 5 bases respondan: `python scripts/chequear_conexiones.py`
6. Crear el esquema y los datos de prueba: `python scripts/aplicar_esquema.py`
7. Correr los tests: `pytest`
8. Arrancar la aplicacion: `python -m logistica`
9. En otra terminal, los procesos periodicos: `python -m logistica.jobs.planificador`
   (propaga el Outbox cada 10 s y chequea la consistencia cada 30 min)

La contrasena de los cuatro usuarios de prueba es `demo1234`.

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
