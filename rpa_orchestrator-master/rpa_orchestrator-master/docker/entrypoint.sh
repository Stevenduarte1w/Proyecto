#!/usr/bin/env sh
set -eu

if [ "${1:-api}" = "api" ]; then
  alembic upgrade head
  exec uvicorn orchestrator.main:create_app --factory --host 0.0.0.0 --port 8000
fi

if [ "${1:-}" = "worker" ]; then
  exec arq orchestrator.infrastructure.queue.worker.WorkerSettings
fi

exec "$@"
