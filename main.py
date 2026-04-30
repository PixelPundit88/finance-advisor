from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
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
from errors import (
    AppException,
    app_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_pool(_app)
    yield
    await close_pool(_app)

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, # type: ignore
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppException, app_exception_handler)  # type: ignore
app.add_exception_handler(RequestValidationError, validation_exception_handler) # type: ignore
app.add_exception_handler(Exception, generic_exception_handler) # type: ignore

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