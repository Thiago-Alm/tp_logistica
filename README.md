# TP Persistencia Poliglota - Ingenieria de Datos II

Plataforma de logistica internacional y monitoreo de cargas con sensores IoT.
Aplicacion de consola en Python con 5 motores: PostgreSQL, MongoDB, Neo4j, Redis y Cassandra.

## Puesta en marcha
1. Copiar `.env.example` a `.env` y completar las claves.
2. Crear el entorno: `python -m venv .venv` y activarlo (Windows: `.venv\Scripts\activate`).
3. Instalar: `pip install -r requirements.txt` y luego `pip install -e .`
4. Levantar las bases: `docker compose up -d`
5. Correr los tests: `pytest`

## Estructura
- `scripts/`: scripts de creacion de cada base (uno por motor).
- `src/logistica/domain/`: entidades.
- `src/logistica/repositories/`: interfaces (clases abstractas), sin codigo de base de datos.
- `src/logistica/infrastructure/`: implementaciones de cada interfaz, una carpeta por motor.
- `src/logistica/services/`: casos de uso.
- `src/logistica/sync/`: Outbox, worker de sincronizacion y chequeo de consistencia.
- `src/logistica/jobs/`: procesos periodicos.
- `src/logistica/cli/`: menus de la consola.
- `src/logistica/container.py`: decide que implementacion usa cada interfaz.
- `tests/` y `docs/`.

## Reparto
- Thiago: esqueleto, Outbox y sincronizacion.
- Fran: PostgreSQL.
- Mati: MongoDB y Cassandra.
- Umbi: Redis, consultas de lectura en Neo4j, datos de prueba y diagramas.
