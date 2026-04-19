import psycopg_pool
import os
from dotenv import load_dotenv

load_dotenv()

# GENERAL POOL
pool: psycopg_pool.AsyncConnectionPool | None = None


# noinspection PyUnresolvedReferences
async def init_pool():
    global pool
    pool = psycopg_pool.AsyncConnectionPool(
        conninfo=os.getenv("DATABASE_URL", ""),
        min_size=2,
        max_size=10,
        open=False
    )

    await pool.open()

async def close_pool():
    global pool
    if pool:
        await pool.close()


# noinspection PyUnresolvedReferences
async def get_db():
    async with pool.connection() as conn:
        yield conn