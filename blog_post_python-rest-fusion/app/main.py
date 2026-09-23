from fastapi import FastAPI
from contextlib import asynccontextmanager
from .router import router
from app.scheduler import start_scheduler, stop_scheduler
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Starting app...")

    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        logging.info("App shutting down...")


app = FastAPI(lifespan=lifespan)
app.include_router(router)
