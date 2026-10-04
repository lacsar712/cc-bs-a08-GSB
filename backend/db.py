import os

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from rules import judge_microstrain

DSN = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:54398/bridgestrain"
)

# 换算专页默认参数：灵敏度系数 K=2.0，额定（激励）电压 E=5.0 V
DEFAULT_SENSITIVITY = 2.0
DEFAULT_RATED_VOLTAGE = 5.0

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS strain_readings (
    id serial PRIMARY KEY,
    span_code text NOT NULL,
    microstrain double precision NOT NULL,
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
ALTER TABLE strain_readings ADD COLUMN IF NOT EXISTS input_mode text;
ALTER TABLE strain_readings ADD COLUMN IF NOT EXISTS conversion_log_id integer;

CREATE TABLE IF NOT EXISTS conversion_settings (
    id integer PRIMARY KEY DEFAULT 1,
    sensitivity double precision NOT NULL,
    rated_voltage double precision NOT NULL,
    updated_by text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT conversion_settings_singleton CHECK (id = 1)
);

CREATE TABLE IF NOT EXISTS conversion_logs (
    id serial PRIMARY KEY,
    reading_id integer NOT NULL REFERENCES strain_readings (id) ON DELETE CASCADE,
    span_code text NOT NULL,
    input_mode text NOT NULL,
    raw_voltage double precision,
    sensitivity double precision,
    rated_voltage double precision,
    microstrain double precision NOT NULL,
    formula text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversion_logs_reading ON conversion_logs (reading_id);
CREATE INDEX IF NOT EXISTS idx_conversion_logs_created ON conversion_logs (created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_strain_readings_status ON strain_readings (status, id);
"""

SETTINGS_SELECT = """
SELECT sensitivity, rated_voltage, updated_by, updated_at
FROM conversion_settings WHERE id = 1
"""

READING_COLUMNS = """
    id, span_code, microstrain, raw_voltage, sensitivity, rated_voltage,
    input_mode, verdict, reason, status, created_by, created_at, processed_at,
    conversion_log_id
"""


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
        await conn.execute(
            """
            INSERT INTO conversion_settings (id, sensitivity, rated_voltage, updated_by)
            VALUES (1, %s, %s, 'system')
            ON CONFLICT (id) DO NOTHING
            """,
            (DEFAULT_SENSITIVITY, DEFAULT_RATED_VOLTAGE),
        )
        await conn.commit()


async def seed_if_empty(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) AS n FROM strain_readings")
            row = await cur.fetchone()
            if row["n"] > 0:
                return
            samples = [
                ("跨中S1", 150.0),
                ("支座S2", 40.0),
            ]
            for span_code, microstrain in samples:
                verdict, reason = judge_microstrain(microstrain)
                await cur.execute(
                    """
                    INSERT INTO strain_readings
                        (span_code, microstrain, verdict, reason, status,
                         created_by, processed_at, input_mode)
                    VALUES (%s, %s, %s, %s, 'done', 'surveyor', now(), 'direct')
                    """,
                    (span_code, microstrain, verdict, reason),
                )
        await conn.commit()


def connect_sync():
    import psycopg

    return psycopg.connect(DSN, row_factory=dict_row)


def ensure_schema_sync(conn) -> None:
    conn.execute(SCHEMA_SQL)
    conn.execute(
        """
        INSERT INTO conversion_settings (id, sensitivity, rated_voltage, updated_by)
        VALUES (1, %s, %s, 'system')
        ON CONFLICT (id) DO NOTHING
        """,
        (DEFAULT_SENSITIVITY, DEFAULT_RATED_VOLTAGE),
    )


def seed_if_empty_sync(conn) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM strain_readings").fetchone()
    if row["n"] > 0:
        return
    samples = [
        ("跨中S1", 150.0),
        ("支座S2", 40.0),
    ]
    for span_code, microstrain in samples:
        verdict, reason = judge_microstrain(microstrain)
        conn.execute(
            """
            INSERT INTO strain_readings
                (span_code, microstrain, verdict, reason, status,
                 created_by, processed_at, input_mode)
            VALUES (%s, %s, %s, %s, 'done', 'surveyor', now(), 'direct')
            """,
            (span_code, microstrain, verdict, reason),
        )
    conn.commit()
