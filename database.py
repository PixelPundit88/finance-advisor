import psycopg_pool
from psycopg_pool import AsyncConnectionPool
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv()

# noinspection PyUnresolvedReferences
async def init_pool(app: FastAPI):
    app.state.pool = psycopg_pool.AsyncConnectionPool(
        conninfo=os.getenv("DATABASE_URL", ""),
        min_size=2,
        max_size=10,
        open=False
    )
    
    await app.state.pool.open()

async def close_pool(app: FastAPI):
    if app.state.pool:
        await app.state.pool.close()


# noinspection PyUnresolvedReferences
async def get_db(request: Request):
    async with request.app.state.pool.connection() as conn:
        yield conn

async def create_pool() -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        conninfo=os.getenv("DATABASE_URL", ""),
        min_size=1,
        max_size=5,
        open=False
    )
    await pool.open()
    return pool