import os

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from rules import judge_microstrain

DSN = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:54398/bridgestrain"
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS strain_readings (
    id serial PRIMARY KEY,
    span_code text NOT NULL,
    microstrain double precision NOT NULL,
    raw_voltage double precision,
    sensitivity double precision,
    rated_voltage double precision,
    verdict text,
    reason text,
    status text NOT NULL DEFAULT 'pending',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);
ALTER TABLE strain_readings ADD COLUMN IF NOT EXISTS raw_voltage double precision;
ALTER TABLE strain_readings ADD COLUMN IF NOT EXISTS sensitivity double precision;
ALTER TABLE strain_readings ADD COLUMN IF NOT EXISTS rated_voltage double precision;
CREATE INDEX IF NOT EXISTS idx_strain_readings_status ON strain_readings (status, id);

CREATE TABLE IF NOT EXISTS conversion_logs (
    id serial PRIMARY KEY,
    reading_id integer NOT NULL REFERENCES strain_readings(id),
    span_code text NOT NULL,
    path text NOT NULL,
    raw_voltage double precision,
    sensitivity double precision,
    rated_voltage double precision,
    microstrain double precision NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversion_logs_id ON conversion_logs (id DESC);
"""

READING_COLUMNS = (
    "id, span_code, microstrain, raw_voltage, sensitivity, rated_voltage, "
    "verdict, reason, status, created_by, created_at, processed_at"
)


def serialize_reading(row) -> dict:
    return {
        "id": row["id"],
        "span_code": row["span_code"],
        "microstrain": row["microstrain"],
        "raw_voltage": row["raw_voltage"],
        "sensitivity": row["sensitivity"],
        "rated_voltage": row["rated_voltage"],
        "verdict": row["verdict"],
        "reason": row["reason"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "processed_at": row["processed_at"],
    }


def serialize_log(row) -> dict:
    return {
        "id": row["id"],
        "reading_id": row["reading_id"],
        "span_code": row["span_code"],
        "path": row["path"],
        "raw_voltage": row["raw_voltage"],
        "sensitivity": row["sensitivity"],
        "rated_voltage": row["rated_voltage"],
        "microstrain": row["microstrain"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }


async def create_pool() -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        conninfo=DSN,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await pool.open()
    return pool


async def ensure_schema(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.commit()


_SEED_SAMPLES = [
    ("跨中S1", 150.0),
    ("支座S2", 40.0),
]


async def seed_if_empty(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) AS n FROM strain_readings")
            row = await cur.fetchone()
            if row["n"] > 0:
                return
            for span_code, microstrain in _SEED_SAMPLES:
                verdict, reason = judge_microstrain(microstrain)
                await cur.execute(
                    """
                    INSERT INTO strain_readings
                        (span_code, microstrain, verdict, reason, status,
                         created_by, processed_at)
                    VALUES (%s, %s, %s, %s, 'done', 'surveyor', now())
                    RETURNING id
                    """,
                    (span_code, microstrain, verdict, reason),
                )
                inserted = await cur.fetchone()
                await cur.execute(
                    """
                    INSERT INTO conversion_logs
                        (reading_id, span_code, path, microstrain, created_by)
                    VALUES (%s, %s, 'direct', %s, 'surveyor')
                    """,
                    (inserted["id"], span_code, microstrain),
                )
        await conn.commit()


def connect_sync():
    import psycopg

    return psycopg.connect(DSN, row_factory=dict_row)


def ensure_schema_sync(conn) -> None:
    conn.execute(SCHEMA_SQL)


def seed_if_empty_sync(conn) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM strain_readings").fetchone()
    if row["n"] > 0:
        return
    for span_code, microstrain in _SEED_SAMPLES:
        verdict, reason = judge_microstrain(microstrain)
        inserted = conn.execute(
            """
            INSERT INTO strain_readings
                (span_code, microstrain, verdict, reason, status,
                 created_by, processed_at)
            VALUES (%s, %s, %s, %s, 'done', 'surveyor', now())
            RETURNING id
            """,
            (span_code, microstrain, verdict, reason),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO conversion_logs
                (reading_id, span_code, path, microstrain, created_by)
            VALUES (%s, %s, 'direct', %s, 'surveyor')
            """,
            (inserted["id"], span_code, microstrain),
        )
    conn.commit()
