"""Route application log records into durable execution_logs rows."""

from __future__ import annotations

import contextvars
import logging
import queue
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from uuid import UUID

from app.models.execution import ExecutionLog
from config.database import SessionLocal

_execution_id: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "execution_id", default=None
)


@contextmanager
def execution_context(execution_id: UUID) -> Iterator[None]:
    token = _execution_id.set(execution_id)
    try:
        yield
    finally:
        _execution_id.reset(token)


class ExecutionLogHandler(logging.Handler):
    """Buffer log rows briefly and write batches with their own DB session."""

    def __init__(self, flush_interval: float = 0.5, batch_size: int = 200) -> None:
        super().__init__()
        self._queue: queue.Queue[tuple[UUID, datetime, str, str] | None] = queue.Queue()
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._flush_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="execution-log-writer", daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        execution_id = _execution_id.get()
        if execution_id is None:
            return
        try:
            message = self.format(record)[:12000]
            ts = datetime.now(timezone.utc).replace(tzinfo=None)
            self._queue.put_nowait((execution_id, ts, record.levelname[:10], message))
        except Exception:
            self.handleError(record)

    def _take_batch(self, first: tuple[UUID, datetime, str, str] | None = None) -> list[tuple[UUID, datetime, str, str]]:
        batch = [first] if first is not None else []
        while len(batch) < self._batch_size:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                batch.append(item)
        return batch

    def _write(self, batch: list[tuple[UUID, datetime, str, str]]) -> None:
        if not batch:
            return
        db = SessionLocal()
        try:
            db.add_all([
                ExecutionLog(execution_id=execution_id, ts=ts, level=level, message=message)
                for execution_id, ts, level, message in batch
            ])
            db.commit()
        except Exception:
            db.rollback()
            logging.getLogger(__name__).exception("Could not persist execution log batch")
        finally:
            db.close()

    def flush_pending(self) -> None:
        with self._flush_lock:
            self._write(self._take_batch())

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._queue.get(timeout=self._flush_interval)
            except queue.Empty:
                self.flush_pending()
                continue
            if first is None:
                continue
            with self._flush_lock:
                self._write(self._take_batch(first))
        self.flush_pending()

    def close(self) -> None:
        self._stop.set()
        self._queue.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        super().close()


_handler: ExecutionLogHandler | None = None


def install_execution_log_handler() -> ExecutionLogHandler:
    global _handler
    root = logging.getLogger()
    if _handler is None:
        _handler = ExecutionLogHandler()
        _handler.setLevel(logging.INFO)
        _handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        root.addHandler(_handler)
    _handler.start()
    return _handler


def flush_execution_logs() -> None:
    if _handler is not None:
        _handler.flush_pending()


def stop_execution_log_handler() -> None:
    global _handler
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler.close()
        _handler = None
