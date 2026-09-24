import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .router import router
from app.scheduler import start_scheduler, stop_scheduler
from app.clients.post_bot_websocket import PostBotWebSocketWorker
from app.core.execution_logging import install_execution_log_handler, stop_execution_log_handler
from config.settings import settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Starting app...")
    if settings.ORCHESTRATOR_ENABLED and (
        not settings.ORCHESTRATOR_TOKEN or not settings.POST_BOT_WS_TOKEN
    ):
        raise RuntimeError(
            "ORCHESTRATOR_ENABLED requiere ORCHESTRATOR_TOKEN y POST_BOT_WS_TOKEN"
        )
    install_execution_log_handler()
    start_scheduler()
    worker_task = None
    worker_stop = asyncio.Event()
    if settings.ORCHESTRATOR_ENABLED:
        worker = PostBotWebSocketWorker()
        worker_task = asyncio.create_task(worker.run_forever(worker_stop), name="post-bot-websocket")
    try:
        yield
    finally:
        worker_stop.set()
        if worker_task:
            worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
        stop_scheduler()
        stop_execution_log_handler()
        logging.info("App shutting down...")


app = FastAPI(lifespan=lifespan)
app.include_router(router)
app.mount("/dashboard", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="dashboard")
