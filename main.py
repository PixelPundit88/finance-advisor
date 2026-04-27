from fastapi import FastAPI
from contextlib import asynccontextmanager
from database import init_pool, close_pool
from routers import (
    auth,
    transactions,
    categories,
    assets,
    analysis,
    predictions,
    anomalies,
    chat,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_pool(_app)
    yield
    await close_pool(_app)

app = FastAPI(lifespan=lifespan)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(assets.router)
app.include_router(analysis.router)
app.include_router(predictions.router)
app.include_router(anomalies.router)
app.include_router(chat.router)

@app.get("/")
async def root():
    return {"message": "Finance Advisor API running"}