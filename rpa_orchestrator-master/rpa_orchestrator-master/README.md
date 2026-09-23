# RPA Orchestrator

Proyecto base para un orquestador de bots RPA escritos en Python y expuestos por API REST.

## Proposito

El orquestador recibe informacion de flujos, la valida, guarda el control operativo, conserva los JSON completos del flujo SEO y distribuye tareas hacia bots externos segun reglas de negocio.

## Capas de informacion

- PostgreSQL: control operativo del orquestador, bots registrados, ejecuciones, estados, auditoria y trazabilidad.
- MongoDB: documentos JSON completos del flujo SEO, payloads ricos y snapshots del flujo.
- Redis: ejecucion temporal, colas, locks, cache y rate limits.

## Arquitectura

```text
src/orchestrator/
  api/             API REST y dependencias HTTP.
  application/     Casos de uso y DTOs de entrada/salida.
  domain/          Entidades, contratos y reglas puras del negocio.
  infrastructure/  Adaptadores concretos para Postgres, Mongo, Redis y bots REST.
  core/            Configuracion, logging y ciclo de vida.
```

El dominio no depende de frameworks. La aplicacion orquesta reglas y contratos. La infraestructura implementa persistencia, colas y clientes HTTP. La API solo traduce HTTP hacia casos de uso.

## Inicio local

```bash
cp .env.example .env
docker compose up --build
```

La API queda disponible en:

- `http://localhost:8005/api/v1/health`
- `http://localhost:8005/docs`
- `http://localhost:8005/dashboard/`

Servicios Docker iniciales:

- `orchestrator`: API REST del orquestador en Python/FastAPI.
- `postgres`: control operativo del orquestador.
- `mongo`: JSONs completos del flujo SEO.
- `redis`: colas, locks, cache y rate limits para la ejecucion temporal.

El worker de ejecuciones queda disponible como perfil opcional:

```bash
docker compose --profile worker up --build
```

Para ejecutar solo la infraestructura y correr la API fuera de Docker:

```bash
docker compose up -d postgres mongo redis
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
POSTGRES_DSN=postgresql+asyncpg://orchestrator:orchestrator@localhost:5434/orchestrator \
MONGO_DSN=mongodb://localhost:27017 \
REDIS_DSN=redis://localhost:6379/0 \
uvicorn orchestrator.main:create_app --factory --reload
```

En Windows PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up -d postgres mongo redis
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
$env:POSTGRES_DSN="postgresql+asyncpg://orchestrator:orchestrator@localhost:5434/orchestrator"
$env:SEO_AGENT_DSN="postgresql+asyncpg://readonly:password@localhost:5432/seo_agent_deep_seek"
$env:MONGO_DSN="mongodb://localhost:27017"
$env:REDIS_DSN="redis://localhost:6379/0"
uvicorn orchestrator.main:create_app --factory --reload
```

Worker de Redis:

```bash
docker compose run --rm orchestrator-worker
```

## Endpoints iniciales

- `GET /api/v1/health`
- `POST /api/v1/bots` para registro administrativo/manual opcional
- `WS /api/v1/bots/ws` para auto-registro y presencia viva de bots
- `WS /api/v1/post-monitor/ws` para resultados y alertas del bot de posts independiente
- `GET /api/v1/post-monitor/overview`
- `GET /api/v1/post-monitor/runs`
- `GET /api/v1/post-monitor/alerts`
- `PATCH /api/v1/post-monitor/alerts/{alert_id}`
- `POST /api/v1/flows`
- `GET /api/v1/flows/{flow_id}`
- `GET /api/v1/flows/{flow_id}/steps`
- `POST /api/v1/flows/{flow_id}/advance`
- `POST /api/v1/executions`
- `POST /api/v1/executions/standalone/instagram`
- `GET /api/v1/executions/{execution_id}`
- `GET /api/v1/executions/{execution_id}/input`
- `POST /api/v1/executions/{execution_id}/result`
- `POST /api/v1/page-executions/{queue_execution_id}/sync`
- `PUT /api/v1/page-executions/{queue_execution_id}/artifacts/{filename}`
- `PUT /api/v1/page-executions/{queue_execution_id}/log`
- `POST /api/v1/seo/pages/{campaign_page_id}/rank-position`
- `GET /api/v1/page-executions/campaigns`
- `GET /api/v1/page-executions/campaigns/{campaign_id}/pages`
- `GET /api/v1/page-executions/pages/{campaign_page_id}/executions`
- `GET /api/v1/page-executions/{queue_execution_id}/artifacts`
- `GET /api/v1/seo/campaigns`
- `GET /api/v1/seo/services?campaign_id={campaign_id}`
- `GET /api/v1/seo/pages?campaign_id={campaign_id}`
- `POST /api/v1/seo/pages`
- `PUT /api/v1/seo/pages/{campaign_page_id}`
- `POST /api/v1/seo/pages/import-xlsx`
- `GET /api/v1/seo/pages/import-template`
- `GET /api/v1/seo/post-groups`
- `POST /api/v1/seo/post-groups`
- `PUT /api/v1/seo/post-groups/{group_id}`
- `DELETE /api/v1/seo/post-groups/{group_id}`
- `GET /api/v1/seo/execution-queue`
- `POST /api/v1/seo/execution-queue/schedule`
- `POST /api/v1/seo/execution-queue/run-now`

La administración de campañas, páginas, jerarquía de WordPress, importación XLSX
y grupos de posts está documentada en
[docs/campaign-pages-and-post-groups.md](docs/campaign-pages-and-post-groups.md).

## Auto-registro de bots por WebSocket

El flujo recomendado para bots es:

```text
bot arranca
bot abre WS /api/v1/bots/ws con Authorization: Bearer
bot envia bot.register con bot_key, bot_type, capabilities y active_executions
orquestador hace upsert en PostgreSQL
orquestador marca presencia online en Redis
bot envia heartbeats
orquestador despacha execution.run por el mismo WebSocket
bot envia execution.started
seo.main puede emitir execution.checkpoint sin terminar la ejecucion
bot termina con execution.succeeded o execution.failed
```

Contrato completo:

```text
docs/bot-websocket-protocol.md
```

Cliente de ejemplo:

```text
examples/ws_bot_client.py
```

Modelo de workflow SEO:

```text
docs/workflow-model.md
```

Contrato del bot que crea o actualiza la página antes de la auditoría:

```text
docs/wordpress-page-setup-bot.md
```

Datos locales de prueba:

```text
docs/local-test-data.md
```

Sincronizacion de ejecuciones SEO, artefactos dinamicos y logs:

```text
docs/page-execution-artifacts.md
```

Diseño del WebSocket para el bot de posts independiente, sin participación en
el workflow SEO principal:

```text
docs/independent-post-bot-websocket.md
```

Aplicar la migración y configurar el token antes de conectar el bot:

```powershell
alembic upgrade head
$env:POST_MONITOR_WS_TOKEN="change-me"
.\.venv\Scripts\python.exe examples\post_monitor_smoke_client.py
```

Este canal no utiliza `flows`, `flow_steps`, `executions`, capabilities ni el
despachador del workflow SEO.

## Frontend

La integración propuesta para la pantalla del bot de maduración de correos está
documentada en `docs/emails-maturation-frontend-integration.md`. El navegador usa
REST; no se conecta al WebSocket privado de los bots.

La especificación técnica para integrar el bot SAAF de backlinks en el panel,
incluidos contratos REST, estados, progreso, cancelación y trabajo pendiente de
backend, está en `docs/backlinks-frontend-integration.md`.

La carpeta `frontend/` queda como placeholder para agregar una SPA o panel administrativo. La recomendacion inicial es construir un dashboard operativo con:

- registro y salud de bots;
- ejecuciones por estado;
- inspeccion de payloads SEO;
- reintentos y cancelaciones controladas;
- metricas de colas, locks y rate limits.

## Principios de desarrollo

- Separar reglas de negocio de frameworks y bases de datos.
- Usar puertos del dominio para que los adaptadores sean reemplazables.
- Preferir operaciones idempotentes para reintentos seguros.
- Registrar correlacion por `execution_id` y `flow_id`.
- Mantener estados explicitos y transiciones controladas.
- Evitar que los bots conozcan detalles internos del orquestador.
