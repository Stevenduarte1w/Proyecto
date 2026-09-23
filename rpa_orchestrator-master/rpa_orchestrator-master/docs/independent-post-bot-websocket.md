# WebSocket para el bot de posts independiente

## Estado del documento

**Implementación mínima disponible.** El backend, la migración, el contrato
WebSocket, las consultas REST, el cliente de prueba y la pestaña del dashboard
descritos en esta guía ya están incluidos en el repositorio. Las mejoras de
producción pendientes se identifican expresamente como tales.

Antes de conectar el bot se debe aplicar la migración:

```bash
alembic upgrade head
```

Esta guía define cómo conectar un bot de posts que se ejecuta por su cuenta y
que solamente envía al orquestador:

- el resultado de cada ejecución;
- una alerta cuando una métrica baja del umbral configurado dentro del propio
  bot;
- heartbeats para mostrar su estado de conexión.

El bot tendrá una pestaña independiente en la interfaz. No recibirá trabajos del
orquestador, no avanzará etapas y no modificará el flujo SEO existente.

## 1. Decisión principal: integración completamente aislada

Este bot **no debe conectarse** al WebSocket actual:

```text
/api/v1/bots/ws
```

Ese endpoint pertenece al motor de workflows. Después del registro puede enviar
`execution.run` y solamente acepta resultados asociados a una ejecución creada
por el orquestador y asignada al bot conectado. Además, los mensajes
`execution.succeeded`, `execution.failed` y `execution.result` pueden avanzar el
workflow original.

Para el bot independiente se propone un endpoint distinto:

```text
WS /api/v1/post-monitor/ws
```

El nombre `post-monitor` se usa deliberadamente para no confundir esta
integración con la capability existente `posts.create` ni con la etapa
`support_posts` del flujo SEO.

### Invariantes de aislamiento

La implementación debe respetar siempre estas reglas:

1. No importar ni invocar `AdvanceWorkflow`, `DispatchExecution`,
   `SubmitExecutionResult` ni `ProcessExecutionCheckpoint`.
2. No crear ni actualizar registros en `flows`, `flow_steps`, `executions` o
   `execution_checkpoints`.
3. No publicar capabilities como `posts.create`.
4. No aceptar mensajes `execution.run`, `execution.started`,
   `execution.checkpoint`, `execution.succeeded` o `execution.failed`.
5. No usar `flow_id`, `step_id` o el `execution_id` del orquestador como claves
   internas.
6. Una caída, alerta o resultado inválido de este bot no puede cambiar el estado
   de una campaña, una página, una cola o un workflow SEO.
7. La pestaña del bot consulta endpoints propios y no mezcla sus datos con la
   vista de operaciones SEO.

Si se necesita relacionar visualmente un resultado con una página, se puede
guardar una referencia externa como `target.url` o `target.external_id`. Esa
referencia no debe ser una clave foránea ni activar lógica del flujo principal.

## 2. Arquitectura propuesta

```text
┌────────────────────────────┐
│ Bot de posts independiente │
│                            │
│ - ejecuta su propio ciclo  │
│ - calcula sus métricas     │
│ - configura sus umbrales   │
│ - conserva una outbox      │
└─────────────┬──────────────┘
              │ WSS
              │ register / heartbeat
              │ result / threshold.alert
              ▼
┌────────────────────────────┐
│ Módulo post_monitor        │
│                            │
│ - autentica                │
│ - valida el contrato       │
│ - deduplica por event_id   │
│ - persiste                 │
│ - responde ACK/error       │
└─────────────┬──────────────┘
              │
              ▼
┌────────────────────────────┐       ┌────────────────────────────┐
│ Tablas post_monitor_*      │◄──────│ Pestaña "Bot de posts"    │
│ completamente separadas   │ REST  │ resultados y alertas       │
└────────────────────────────┘       └────────────────────────────┘

        SIN conexión con:
        flows / flow_steps / executions / AdvanceWorkflow
```

El WebSocket es bidireccional, pero en esta integración el tráfico funcional es
principalmente del bot hacia el orquestador. El servidor solamente devuelve
confirmaciones, errores y, opcionalmente, una orden de cierre por mantenimiento.
Nunca envía órdenes de ejecución al bot.

### Distribución sugerida en el repositorio

```text
src/orchestrator/
  api/v1/routes/post_monitor.py
  application/post_monitor.py
  infrastructure/postgres/post_monitor.py
  infrastructure/postgres/models.py

frontend/
  index.html                 # nueva workspace-view
  app.js                     # carga y filtros de la pestaña
  styles.css

alembic/versions/
  xxxx_post_monitor_tables.py
```

La implementación comparte el proceso FastAPI y la instancia de PostgreSQL,
pero tiene módulo, rutas, tablas y configuración propios. La presencia mínima se
calcula desde `post_monitor_bots.last_seen_at`; no usa las capabilities ni la
presencia Redis del despachador. Si se
requiere aislamiento de infraestructura más fuerte, el mismo contrato permite
mover `post_monitor` a otro servicio y otra base de datos sin cambiar el bot.

### 2.1 Cómo funciona WebSocket en esta integración

La conexión comienza como una solicitud HTTP con `Upgrade: websocket`. Cuando
el servidor acepta el upgrade, cliente y servidor mantienen abierto un canal
TCP —protegido por TLS cuando se usa `wss://`— y pueden intercambiar frames sin
abrir una petición HTTP nueva para cada evento.

Eso aporta baja latencia y permite mostrar que el bot está conectado, pero no
convierte el socket en almacenamiento confiable:

- una conexión pertenece a una sola instancia y termina si cualquiera de los
  dos procesos se reinicia;
- un frame enviado no se considera persistido hasta recibir el ACK de la
  aplicación;
- WebSocket conserva el orden dentro de una conexión, pero una reconexión y los
  reintentos pueden hacer que el servidor reciba duplicados;
- por esa razón, el bot necesita una outbox durable y el servidor necesita
  deduplicación por `event_id`;
- ping/pong confirma que el canal de red responde, mientras que
  `post_monitor.heartbeat` actualiza la presencia funcional y los datos visibles
  en el dashboard.

El navegador no participa en este socket. El canal existe entre el proceso del
bot y el backend; la pestaña consulta al backend mediante REST y nunca conoce el
token del bot.

## 3. Direcciones y configuración

El `docker-compose.yml` actual publica el orquestador en el puerto local `8005`:

```env
POST_MONITOR_WS_URL=ws://localhost:8005/api/v1/post-monitor/ws
POST_MONITOR_API_URL=http://localhost:8005/api/v1/post-monitor
POST_MONITOR_BOT_KEY=post-monitor-prod-01
POST_MONITOR_WS_TOKEN=change-me
```

En producción se deben utilizar TLS y nombres públicos:

```env
POST_MONITOR_WS_URL=wss://orquestador.midominio.com/api/v1/post-monitor/ws
POST_MONITOR_API_URL=https://orquestador.midominio.com/api/v1/post-monitor
POST_MONITOR_BOT_KEY=post-monitor-prod-01
POST_MONITOR_WS_TOKEN=use-a-secret-manager
```

Configuración propuesta del orquestador:

```env
POST_MONITOR_WS_TOKEN=change-me
POST_MONITOR_PRESENCE_TTL_SECONDS=60
POST_MONITOR_MAX_MESSAGE_BYTES=262144
```

`POST_MONITOR_WS_TOKEN` debe ser distinto de los valores de `BOT_TOKENS`. Esto permite
revocar o rotar el acceso del bot independiente sin afectar a los bots del flujo
principal. Si queda vacío, la implementación permite conexiones sin token para
facilitar el desarrollo local. En producción debe tener siempre un secreto.

`POST_MONITOR_MAX_MESSAGE_BYTES` se anuncia al cliente durante el registro. El
límite efectivo del frame también debe configurarse en Uvicorn o en el proxy
inverso; este endurecimiento de infraestructura no se realiza desde la ruta.

## 4. Ciclo de vida de la conexión

```text
1. Bot abre wss://.../api/v1/post-monitor/ws con Bearer token.
2. Bot envía post_monitor.register como primer mensaje.
3. Servidor valida token, esquema y bot_key.
4. Servidor responde post_monitor.registered.
5. Bot envía post_monitor.heartbeat cada 20–30 segundos.
6. Cuando termina un trabajo propio, envía post_monitor.run.result.
7. Si detecta un umbral incumplido, envía post_monitor.threshold.alert.
8. Servidor persiste cada evento y responde post_monitor.event.ack.
9. Si la conexión cae, el bot conserva eventos sin ACK y se reconecta.
10. Al reconectar, reenvía los eventos pendientes con el mismo event_id.
```

### Estados de conexión visibles

- `online`: existe heartbeat dentro del TTL.
- `stale`: no hay heartbeat reciente, pero todavía no se ha confirmado el
  cierre.
- `offline`: expiró el TTL o se cerró la conexión.
- `disabled`: acceso deshabilitado administrativamente.

El estado de presencia es informativo. No participa en la asignación de trabajos.

## 5. Reglas generales del protocolo

- Codificación: JSON en texto UTF-8.
- Fechas: ISO 8601 en UTC, terminadas en `Z`.
- Identificadores: UUID en minúsculas.
- Tamaño máximo recomendado por mensaje: 256 KiB.
- Versión inicial del protocolo: `post-monitor.ws.v1`.
- El bot genera `event_id`; el servidor no lo reemplaza.
- Los eventos se entregan al menos una vez; el servidor los hace idempotentes.
- No se garantiza que eventos distintos lleguen en orden.
- El bot no debe incluir secretos, cookies, credenciales ni contenido completo
  innecesario en los payloads.
- Archivos grandes, capturas o reportes deben almacenarse externamente y
  referenciarse mediante HTTPS.

Todos los eventos persistibles comparten este sobre lógico:

```json
{
  "type": "post_monitor.event_name",
  "schema_version": "post-monitor.event.v1",
  "event_id": "d1d5367a-e65f-4f6b-af68-eeddf2385a1f",
  "bot_key": "post-monitor-prod-01",
  "occurred_at": "2026-09-04T15:20:41.215Z",
  "payload": {}
}
```

`bot_key` debe coincidir con el bot registrado en la conexión. El servidor no
debe aceptar que una conexión reporte eventos en nombre de otro bot.

## 6. Autenticación y registro

### 6.1 Autenticación del handshake

El bot envía el token en el encabezado del upgrade HTTP:

```http
Authorization: Bearer <POST_MONITOR_WS_TOKEN>
```

La ruta WebSocket valida este encabezado explícitamente cuando
`POST_MONITOR_WS_TOKEN` tiene valor. El middleware HTTP no protege conexiones
WebSocket.

Ante un token inválido, el servidor rechaza o cierra la conexión con código
`4401`. Ante un bot deshabilitado, usa `4403`. El token nunca debe viajar en la
query string ni dentro de un mensaje JSON, porque esas ubicaciones suelen quedar
registradas en logs y proxies.

### 6.2 Primer mensaje: registro

```json
{
  "type": "post_monitor.register",
  "schema_version": "post-monitor.register.v1",
  "bot_key": "post-monitor-prod-01",
  "name": "Monitor independiente de posts",
  "version": "1.0.0",
  "environment": "production",
  "started_at": "2026-09-04T15:00:00.000Z",
  "metadata": {
    "runtime": "python",
    "host_alias": "post-worker-01"
  }
}
```

El primer mensaje debe ser `post_monitor.register`. Si no lo es, el servidor
responde `invalid_first_message` y cierra con código `4400`.

Respuesta:

```json
{
  "type": "post_monitor.registered",
  "schema_version": "post-monitor.registered.v1",
  "status": "ok",
  "session_id": "c73020fe-8270-4e12-ab30-ca3d812aec6c",
  "server_time": "2026-09-04T15:20:00.000Z",
  "heartbeat_interval_seconds": 25,
  "max_message_bytes": 262144
}
```

`bot_key` es una identidad estable y debe mantenerse entre reinicios. Cada nueva
conexión crea un `session_id` distinto. La implementación mínima admite más de
una conexión con el mismo `bot_key`; hasta agregar coordinación distribuida, se
debe ejecutar una sola instancia productora por clave.

## 7. Heartbeat

Mensaje del bot:

```json
{
  "type": "post_monitor.heartbeat",
  "schema_version": "post-monitor.heartbeat.v1",
  "sent_at": "2026-09-04T15:20:25.000Z",
  "status": "idle",
  "current_jobs": 0,
  "outbox_pending": 0
}
```

Mientras está ejecutando trabajo propio puede usar `status: "running"`. Estos
datos solamente se muestran en la pestaña; no determinan capacidad ni provocan
despachos.

ACK:

```json
{
  "type": "post_monitor.heartbeat.ack",
  "status": "ok",
  "server_time": "2026-09-04T15:20:25.030Z"
}
```

Con un TTL de 60 segundos, un intervalo de 25 segundos deja margen para retrasos
temporales. WebSocket ping/pong verifica el transporte; el heartbeat JSON
actualiza el estado funcional que verá el dashboard. Se recomienda usar ambos.

## 8. Resultado de una ejecución propia

El bot genera su propio `run_id`. Este identificador no es un `execution_id` del
orquestador.

```json
{
  "type": "post_monitor.run.result",
  "schema_version": "post-monitor.result.v1",
  "event_id": "d1d5367a-e65f-4f6b-af68-eeddf2385a1f",
  "bot_key": "post-monitor-prod-01",
  "occurred_at": "2026-09-04T15:20:41.215Z",
  "payload": {
    "run_id": "850c97af-0b96-4aac-91f0-faca35314acf",
    "status": "succeeded",
    "started_at": "2026-09-04T15:18:03.010Z",
    "finished_at": "2026-09-04T15:20:41.215Z",
    "duration_ms": 158205,
    "target": {
      "external_id": "post-8472",
      "url": "https://example.com/blog/mi-post",
      "title": "Mi post"
    },
    "summary": "Validación y actualización completadas",
    "metrics": {
      "score": 84.5,
      "items_checked": 27,
      "items_ok": 25,
      "items_failed": 2
    },
    "result": {
      "changed": true,
      "provider_reference": "job-129948"
    },
    "artifacts": [
      {
        "name": "report.json",
        "url": "https://storage.example.com/reports/850c97af/report.json",
        "content_type": "application/json",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      }
    ]
  }
}
```

Estados permitidos:

- `succeeded`: terminó correctamente;
- `failed`: terminó con error;
- `partial`: produjo un resultado incompleto;
- `cancelled`: el propio bot canceló el trabajo.

Ejemplo de fallo:

```json
{
  "type": "post_monitor.run.result",
  "schema_version": "post-monitor.result.v1",
  "event_id": "2a23746f-bc03-45df-8815-ffb2e78492e9",
  "bot_key": "post-monitor-prod-01",
  "occurred_at": "2026-09-04T16:04:00.000Z",
  "payload": {
    "run_id": "7584a6d3-cf0e-4fb0-95d2-05260f028f37",
    "status": "failed",
    "started_at": "2026-09-04T16:03:14.000Z",
    "finished_at": "2026-09-04T16:04:00.000Z",
    "duration_ms": 46000,
    "target": {
      "external_id": "post-8472",
      "url": "https://example.com/blog/mi-post"
    },
    "error": {
      "code": "provider_timeout",
      "message": "El proveedor no respondió dentro del tiempo límite",
      "retryable": true
    },
    "metrics": {},
    "result": {},
    "artifacts": []
  }
}
```

El orquestador persiste y presenta el resultado. No decide reintentos ni inicia
otra ejecución; esa responsabilidad continúa dentro del bot.

## 9. Alerta por umbral

El umbral se configura, evalúa y versiona en el bot. El orquestador no recalcula
la regla y no envía configuración de umbrales por WebSocket. La alerta incluye
una fotografía de la regla aplicada para que el dashboard pueda explicar por
qué se generó.

Cuando una ejecución termina y además cruza un umbral, el bot envía dos eventos:
primero `post_monitor.run.result` y después
`post_monitor.threshold.alert`, ambos con el mismo `run_id`. La alerta no
reemplaza el resultado. Cada evento tiene su propio `event_id` y se confirma de
forma independiente.

```json
{
  "type": "post_monitor.threshold.alert",
  "schema_version": "post-monitor.alert.v1",
  "event_id": "bba5c9eb-1377-4631-97c1-bc9e88c4e426",
  "bot_key": "post-monitor-prod-01",
  "occurred_at": "2026-09-04T15:20:41.218Z",
  "payload": {
    "alert_id": "9cd4d464-ec2d-479b-acaf-a0ccf9631153",
    "run_id": "850c97af-0b96-4aac-91f0-faca35314acf",
    "severity": "warning",
    "metric": "score",
    "observed_value": 54.2,
    "operator": "lt",
    "threshold": 60.0,
    "unit": "points",
    "message": "El score del post bajó de 60 puntos",
    "rule": {
      "rule_id": "post-score-minimum",
      "config_version": "2026-09-01.1",
      "configured_by": "post-bot"
    },
    "target": {
      "external_id": "post-8472",
      "url": "https://example.com/blog/mi-post",
      "title": "Mi post"
    },
    "details": {
      "previous_value": 66.8
    }
  }
}
```

Valores iniciales de `severity`: `info`, `warning` y `critical`.

Operadores permitidos:

- `lt`: menor que;
- `lte`: menor o igual que;
- `gt`: mayor que;
- `gte`: mayor o igual que;
- `eq`: igual a.

Aunque el caso inicial sea “baja del umbral”, guardar el operador hace el evento
inequívoco y extensible.

### Ciclo de vida de una alerta

Al ingresar queda `open`. Desde la pestaña un usuario puede cambiarla a:

- `acknowledged`: alguien la revisó;
- `resolved`: la condición fue atendida;
- `dismissed`: no requiere acción.

Estos cambios pertenecen al módulo de monitoreo y tampoco afectan el workflow
SEO. En la primera versión no es necesario enviar el cambio de estado de vuelta
al bot.

## 10. ACK, idempotencia y errores

### ACK de evento nuevo

```json
{
  "type": "post_monitor.event.ack",
  "status": "accepted",
  "event_id": "d1d5367a-e65f-4f6b-af68-eeddf2385a1f",
  "stored_at": "2026-09-04T15:20:41.310Z",
  "duplicate": false
}
```

### ACK de reenvío

```json
{
  "type": "post_monitor.event.ack",
  "status": "accepted",
  "event_id": "d1d5367a-e65f-4f6b-af68-eeddf2385a1f",
  "stored_at": "2026-09-04T15:20:41.310Z",
  "duplicate": true
}
```

El servidor impone una restricción única por `(bot_id, event_id)`. Si recibe el
mismo evento otra vez, no duplica el resultado ni la alerta, pero devuelve ACK.
Si el mismo `event_id` llega con un contenido diferente, responde
`event_id_conflict`; no reemplaza el registro original.

El bot elimina un evento de su outbox solamente después de recibir un ACK con el
mismo `event_id`. Si pierde la conexión antes del ACK, debe reenviarlo sin crear
otro identificador.

### Error recuperable

```json
{
  "type": "post_monitor.error",
  "code": "temporary_storage_error",
  "message": "No fue posible guardar el evento; reintente el mismo event_id",
  "event_id": "d1d5367a-e65f-4f6b-af68-eeddf2385a1f",
  "retryable": true
}
```

### Error de validación

```json
{
  "type": "post_monitor.error",
  "code": "invalid_message",
  "message": "payload.run_id debe ser un UUID",
  "event_id": "d1d5367a-e65f-4f6b-af68-eeddf2385a1f",
  "retryable": false
}
```

Códigos de cierre propuestos:

| Código | Significado | Acción del bot |
|---:|---|---|
| `1000` | cierre normal | reconectar solo si debe seguir activo |
| `1009` | mensaje demasiado grande | reducir el payload; no repetirlo igual |
| `1011` | error temporal del servidor | reconectar con backoff |
| `4009` | sesión reemplazada | detener la instancia duplicada |
| `4400` | protocolo o registro inválido | corregir configuración/mensaje |
| `4401` | token inválido | renovar credencial |
| `4403` | bot deshabilitado | intervención administrativa |

## 11. Persistencia separada

Se proponen cuatro tablas sin claves foráneas hacia el workflow existente.

### `post_monitor_bots`

| Campo | Tipo | Uso |
|---|---|---|
| `id` | UUID PK | identidad interna |
| `bot_key` | varchar único | identidad estable enviada por el bot |
| `name` | varchar | nombre visible |
| `version` | varchar nullable | versión desplegada |
| `environment` | varchar | entorno reportado |
| `metadata` | JSONB | datos técnicos no sensibles |
| `enabled` | boolean | habilitación administrativa |
| `last_seen_at` | timestamptz | último registro o heartbeat |
| `created_at` | timestamptz | auditoría |
| `updated_at` | timestamptz | auditoría |

### `post_monitor_events`

Inbox append-only utilizado para deduplicar y auditar.

| Campo | Tipo | Uso |
|---|---|---|
| `id` | UUID PK | identidad interna |
| `bot_id` | UUID FK local | referencia a `post_monitor_bots` |
| `event_id` | UUID | identidad creada por el bot |
| `event_type` | varchar | tipo de mensaje |
| `schema_version` | varchar | versión del contrato |
| `occurred_at` | timestamptz | hora reportada por el bot |
| `received_at` | timestamptz | hora del servidor |
| `payload_hash` | char(64) | detección de conflictos |
| `raw_payload` | JSONB | evento validado completo |

Restricción única: `(bot_id, event_id)`.

### `post_monitor_runs`

| Campo | Tipo | Uso |
|---|---|---|
| `id` | UUID PK | identidad interna |
| `bot_id` | UUID FK local | bot que reportó |
| `run_id` | UUID | ejecución creada por el bot |
| `source_event_id` | UUID | evento que creó/actualizó el registro |
| `status` | varchar | succeeded/failed/partial/cancelled |
| `target_external_id` | varchar nullable | referencia externa informativa |
| `target_url` | text nullable | URL inspeccionada |
| `target_title` | text nullable | título visible |
| `started_at` | timestamptz | inicio informado |
| `finished_at` | timestamptz | fin informado |
| `duration_ms` | bigint nullable | duración |
| `summary` | text nullable | resumen legible |
| `metrics` | JSONB | métricas variables |
| `result` | JSONB | resultado específico del bot |
| `error` | JSONB nullable | error estructurado |
| `artifacts` | JSONB | enlaces a artefactos |
| `created_at` | timestamptz | auditoría |

Restricción única: `(bot_id, run_id)`.

### `post_monitor_alerts`

| Campo | Tipo | Uso |
|---|---|---|
| `id` | UUID PK | identidad interna |
| `bot_id` | UUID FK local | bot que alertó |
| `alert_id` | UUID | identidad creada por el bot |
| `run_id` | UUID nullable | ejecución propia relacionada |
| `source_event_id` | UUID | evento recibido |
| `severity` | varchar | info/warning/critical |
| `metric` | varchar | métrica evaluada |
| `observed_value` | numeric | valor observado |
| `operator` | varchar | comparación aplicada |
| `threshold` | numeric | umbral configurado en el bot |
| `unit` | varchar nullable | unidad |
| `message` | text | mensaje visible |
| `rule_snapshot` | JSONB | regla y versión reportadas |
| `target` | JSONB | objetivo informativo |
| `details` | JSONB | contexto adicional |
| `status` | varchar | open/acknowledged/resolved/dismissed |
| `occurred_at` | timestamptz | fecha del evento |
| `acknowledged_at` | timestamptz nullable | auditoría UI |
| `resolved_at` | timestamptz nullable | auditoría UI |

Restricción única: `(bot_id, alert_id)`.

Una ampliación futura puede mover la presencia temporal a Redis usando claves
propias:

```text
post_monitor:presence:{bot_id}
post_monitor:session:{bot_key}
```

La versión implementada no necesita esas claves: determina `online/offline`
comparando `last_seen_at` con `POST_MONITOR_PRESENCE_TTL_SECONDS`. En ningún caso
se deben usar `bots:presence:*` ni `bots:capability:*` del despachador actual.

## 12. API REST para la pestaña independiente

El navegador no debe conectarse al socket de ingreso del bot. La pestaña lee
datos validados y persistidos a través de REST:

```text
GET   /api/v1/post-monitor/overview
GET   /api/v1/post-monitor/runs
GET   /api/v1/post-monitor/alerts
PATCH /api/v1/post-monitor/alerts/{alert_id}
```

Filtros recomendados:

```text
GET /runs?status=failed&limit=50
GET /alerts?status=open&severity=critical&limit=50
```

La versión mínima permite `limit` entre 1 y 500 y ordena del registro más
reciente al más antiguo. La paginación por cursor y los filtros por rango de
fecha quedan como mejora posterior.

Ejemplo de `overview`:

```json
{
  "bot": {
    "bot_key": "post-monitor-prod-01",
    "connection_status": "online",
    "version": "1.0.0",
    "last_heartbeat_at": "2026-09-04T15:20:25.000Z"
  },
  "runs": {
    "last_24h": 42,
    "succeeded": 39,
    "failed": 2,
    "partial": 1
  },
  "alerts": {
    "open": 3,
    "critical": 1,
    "latest_at": "2026-09-04T15:20:41.218Z"
  },
  "latest_metrics": {
    "score": 54.2
  }
}
```

El dashboard ya protege `/dashboard` con autenticación Basic cuando
`DASHBOARD_USER` y `DASHBOARD_PASS` están configurados. Las nuevas rutas REST
también deben agregarse explícitamente al conjunto de rutas protegidas.

## 13. Pestaña “Bot de posts”

La navegación principal agregará una tercera vista, hermana de “Operaciones SEO”
y “Datos base”:

```text
[ Operaciones SEO ] [ Datos base ] [ Bot de posts ]
```

Contenido recomendado:

1. **Estado del bot:** online/offline, versión, última conexión y último
   heartbeat.
2. **Indicadores:** ejecuciones en 24 horas, tasa de éxito, fallos y alertas
   abiertas.
3. **Alertas abiertas:** severidad, métrica, valor observado, umbral, post,
   fecha y acciones de reconocer/resolver.
4. **Historial de ejecuciones:** estado, post, duración, resumen, métricas y
   acceso al detalle.
5. **Detalle:** JSON validado, error y enlaces a artefactos, sin renderizar HTML
   remoto.

La primera versión puede consultar `overview`, `runs` y `alerts` cada 15
segundos, además de recargar cuando el usuario vuelva a la pestaña. Esto mantiene
el socket del bot exclusivamente como canal de ingreso.

Si más adelante se requiere actualización instantánea en el navegador, debe
crearse un canal de solo lectura diferente, por ejemplo
`/api/v1/post-monitor/ui/ws`, autenticado como dashboard. No se debe exponer el
socket del bot directamente al frontend.

## 14. Reconexión y entrega confiable

El bot debe usar backoff exponencial con jitter:

```text
2 s, 4 s, 8 s, 16 s, 30 s máximo + jitter aleatorio
```

Después de una conexión estable se reinicia el retraso a 2 segundos. Los cierres
`4400`, `4401`, `4403` y `4009` requieren corregir configuración o detener la
instancia; no deben provocar un bucle agresivo de reconexión.

### Outbox local del bot

Para no perder resultados cuando el orquestador está desconectado, el bot debe
guardar antes de enviar:

```text
event_id
event_type
serialized_payload
created_at
attempt_count
last_attempt_at
acked_at
```

Flujo:

```text
bot termina ejecución
  -> crea evento y lo guarda en outbox
  -> intenta enviar
  -> recibe ACK del mismo event_id
  -> marca el evento como confirmado
```

El bot puede enviar varios eventos sin esperar, pero debe correlacionar cada ACK
por `event_id`. Para una primera versión más simple y robusta, se recomienda una
ventana de un solo evento pendiente en el socket.

## 15. Cliente Python de referencia

El repositorio incluye un cliente de smoke test listo para ejecutar. Después de
levantar el orquestador y aplicar la migración, en PowerShell:

```powershell
$env:POST_MONITOR_WS_URL="ws://localhost:8005/api/v1/post-monitor/ws"
$env:POST_MONITOR_WS_TOKEN="change-me"
$env:POST_MONITOR_SCORE="54.2"
$env:POST_MONITOR_THRESHOLD="60"
.\.venv\Scripts\python.exe examples\post_monitor_smoke_client.py
```

El ejemplo crea un resultado y, como `54.2 < 60`, crea también una alerta. Ambos
deben recibir `post_monitor.event.ack` y aparecer en la pestaña “Bot de posts”.
Si el orquestador local tiene `POST_MONITOR_WS_TOKEN` vacío, se puede omitir esa
variable en el cliente.

Este ejemplo muestra exclusivamente el transporte. `load_pending_events()` y
`mark_acked()` deben conectarse con la outbox real del bot.

```python
from __future__ import annotations

import asyncio
import json
import os
import random
from collections.abc import AsyncIterator
from typing import Any

import websockets


WS_URL = os.getenv(
    "POST_MONITOR_WS_URL",
    "ws://localhost:8005/api/v1/post-monitor/ws",
)
BOT_TOKEN = os.environ["POST_MONITOR_WS_TOKEN"]
BOT_KEY = os.getenv("POST_MONITOR_BOT_KEY", "post-monitor-prod-01")


async def load_pending_events() -> AsyncIterator[dict[str, Any]]:
    # Sustituir por SQLite, PostgreSQL u otra outbox persistente del bot.
    if False:
        yield {}


async def mark_acked(event_id: str) -> None:
    # Marcar como confirmado en la outbox real.
    print(f"ACK: {event_id}")


async def heartbeat_loop(websocket: Any) -> None:
    while True:
        await asyncio.sleep(25)
        await websocket.send(
            json.dumps(
                {
                    "type": "post_monitor.heartbeat",
                    "schema_version": "post-monitor.heartbeat.v1",
                    "status": "idle",
                    "current_jobs": 0,
                    "outbox_pending": 0,
                }
            )
        )


async def receive_loop(
    websocket: Any,
    event_responses: asyncio.Queue[dict[str, Any]],
) -> None:
    async for raw_message in websocket:
        response = json.loads(raw_message)
        response_type = response.get("type")
        if response_type == "post_monitor.heartbeat.ack":
            continue
        if response_type in {
            "post_monitor.event.ack",
            "post_monitor.error",
        }:
            await event_responses.put(response)
            continue
        print(f"Unhandled server message: {response}")


async def send_pending_events(
    websocket: Any,
    event_responses: asyncio.Queue[dict[str, Any]],
) -> None:
    async for event in load_pending_events():
        await websocket.send(json.dumps(event))

        while True:
            response = await event_responses.get()
            if response.get("type") == "post_monitor.event.ack":
                if response.get("event_id") != event["event_id"]:
                    raise RuntimeError("Received ACK for a different event")
                await mark_acked(event["event_id"])
                break
            if response.get("type") == "post_monitor.error":
                raise RuntimeError(f"Server rejected event: {response}")


async def run_connection() -> None:
    async with websockets.connect(
        WS_URL,
        additional_headers={"Authorization": f"Bearer {BOT_TOKEN}"},
        ping_interval=20,
        ping_timeout=20,
        close_timeout=10,
        max_size=262_144,
    ) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "post_monitor.register",
                    "schema_version": "post-monitor.register.v1",
                    "bot_key": BOT_KEY,
                    "name": "Monitor independiente de posts",
                    "version": "1.0.0",
                    "environment": "production",
                    "metadata": {"runtime": "python"},
                }
            )
        )

        registration = json.loads(await websocket.recv())
        if registration.get("type") != "post_monitor.registered":
            raise RuntimeError(f"Registration failed: {registration}")

        event_responses: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        heartbeat = asyncio.create_task(heartbeat_loop(websocket))
        receiver = asyncio.create_task(receive_loop(websocket, event_responses))
        sender = asyncio.create_task(
            send_pending_events(websocket, event_responses)
        )
        try:
            await asyncio.gather(heartbeat, receiver, sender)
        finally:
            for task in (heartbeat, receiver, sender):
                task.cancel()


async def main() -> None:
    delay = 2.0
    while True:
        try:
            await run_connection()
            delay = 2.0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Post monitor disconnected: {exc}")
            await asyncio.sleep(delay + random.uniform(0, delay * 0.2))
            delay = min(delay * 2, 30.0)


if __name__ == "__main__":
    asyncio.run(main())
```

`load_pending_events()` debe permanecer activo y producir también los eventos
que se creen después del registro. El ejemplo usa una sola ventana de envío y
una cola `asyncio` para mantener un único lector del WebSocket; esto evita el
error de ejecutar dos llamadas `recv()` concurrentes.

## 16. Observabilidad y seguridad

Registrar en logs estructurados:

- `session_id`, `bot_key`, `event_id`, `run_id` y `alert_id`;
- tipo y versión del mensaje;
- resultado de validación y deduplicación;
- latencia entre `occurred_at` y `received_at`;
- cierre del socket y código de cierre.

No registrar:

- encabezados de autorización;
- tokens;
- credenciales de proveedores;
- contenido completo de posts si no es necesario;
- payloads sin límite de tamaño.

Controles mínimos:

- `wss://` en producción;
- token separado y rotación periódica;
- límite de tamaño y frecuencia de mensajes;
- allowlist de `type` y `schema_version`;
- validación estricta de URLs y fechas;
- longitud máxima de textos;
- paginación en las consultas del dashboard;
- artefactos mediante URLs HTTPS firmadas o privadas;
- política de retención y eliminación de datos.

Métricas recomendadas:

```text
post_monitor_connections_current
post_monitor_events_received_total{type,status}
post_monitor_event_processing_seconds
post_monitor_invalid_messages_total{code}
post_monitor_open_alerts{severity}
post_monitor_last_heartbeat_age_seconds
```

## 17. Estado de implementación y próximos pasos

Ya está implementado:

1. DTOs estrictos para registro, heartbeat, resultados y alertas.
2. Migración y repositorio PostgreSQL con tablas `post_monitor_*`.
3. Validación explícita del Bearer token en el WebSocket.
4. Registro, heartbeat y presencia calculada con un TTL propio.
5. Inbox idempotente, proyecciones de resultados/alertas y ACK por `event_id`.
6. Consultas REST protegidas por la autenticación del dashboard.
7. Pestaña independiente con actualización cada 15 segundos.
8. Pruebas unitarias del contrato, rutas y rechazo de mensajes `execution.*`.

Antes de producción todavía corresponde:

1. Configurar WSS en el proxy inverso y un valor secreto para
   `POST_MONITOR_WS_TOKEN`.
2. Configurar el límite efectivo de frame en Uvicorn/proxy y rate limiting.
3. Implementar la outbox persistente en el bot real.
4. Añadir bloqueo de sesión duplicada si se desplegarán varias instancias con el
   mismo `bot_key`.
5. Ejecutar pruebas de integración contra PostgreSQL real, incluyendo
   concurrencia y reenvíos simultáneos.
6. Definir retención, métricas y alertas operativas.

## 18. Criterios de aceptación

- [x] Existe únicamente el canal aislado `/api/v1/post-monitor/ws` para esta
      integración.
- [x] El socket rechaza conexiones sin el token cuando
      `POST_MONITOR_WS_TOKEN` está configurado.
- [x] El primer mensaje válido siempre es `post_monitor.register`.
- [x] El servidor nunca envía trabajos al bot independiente.
- [x] Un resultado crea un registro en `post_monitor_runs`.
- [x] Una alerta crea un registro en `post_monitor_alerts` con la fotografía del
      umbral configurado por el bot.
- [x] Reenviar el mismo `event_id` devuelve ACK sin duplicar datos.
- [x] Un `event_id` repetido con contenido diferente es rechazado.
- [x] El módulo no escribe en `flows`, `flow_steps`,
      `executions` ni `execution_checkpoints`.
- [x] No se llama al motor de workflow durante el procesamiento de eventos.
- [x] La pestaña “Bot de posts” usa exclusivamente rutas `/post-monitor/*`.
- [x] Una alerta puede reconocerse o resolverse sin cambiar el flujo SEO.
- [x] El dashboard distingue online/offline usando su propio TTL de presencia.
- [ ] Los eventos sin ACK sobreviven a una desconexión en la outbox del bot.
- [ ] Los payloads que superan el límite son rechazados sin afectar el servicio
      principal.

## 19. Pruebas de aislamiento obligatorias

Además de las pruebas funcionales, conviene capturar el requisito principal con
pruebas explícitas:

1. Tomar un snapshot de las tablas `flows`, `flow_steps`, `executions` y
   `execution_checkpoints`.
2. Registrar el bot independiente.
3. Enviar un resultado exitoso, un resultado fallido y una alerta.
4. Confirmar los ACK y la aparición en los endpoints `/post-monitor/*`.
5. Verificar que las cuatro tablas originales conservan exactamente el mismo
   contenido.
6. Enviar por error un mensaje `execution.succeeded` al nuevo socket y comprobar
   que responde `unsupported_message_type`.
7. Dejar expirar `post_monitor_bots.last_seen_at` y confirmar que solamente
   cambia el indicador online/offline de la pestaña independiente.

## 20. Fuera de alcance

Esta primera integración no incluye:

- asignar trabajos al bot;
- configurar el umbral desde el orquestador;
- crear posts desde el workflow SEO;
- avanzar, aprobar o detener etapas;
- publicar resultados en `page_execution_queue`;
- indexar automáticamente URLs reportadas;
- enviar correos, SMS o mensajes a servicios externos;
- ejecutar acciones automáticas al recibir una alerta.

Si posteriormente se desea una notificación externa, debe añadirse como un
consumidor del módulo `post_monitor`, manteniendo la regla de que una
notificación nunca modifica el workflow SEO.

## Referencias del código actual

- `src/orchestrator/api/v1/routes/bots.py`: endpoint WebSocket acoplado al
  workflow que no debe reutilizarse.
- `src/orchestrator/infrastructure/bots/ws_manager.py`: envío actual de órdenes
  `execution.run`/`execution.start` que no aplica al bot independiente.
- `src/orchestrator/infrastructure/redis/presence.py`: presencia de bots del
  despachador que el nuevo módulo no utiliza.
- `src/orchestrator/application/post_monitor.py`: DTOs, puerto y servicio
  aislado.
- `src/orchestrator/infrastructure/postgres/post_monitor.py`: persistencia,
  idempotencia y consultas del módulo.
- `src/orchestrator/api/v1/routes/post_monitor.py`: WebSocket y API REST
  implementados.
- `alembic/versions/0004_post_monitor.py`: tablas independientes.
- `src/orchestrator/core/config.py`: ubicación de las nuevas variables de
  configuración.
- `src/orchestrator/main.py`: protección del dashboard y las nuevas rutas REST.
- `frontend/index.html` y `frontend/app.js`: pestaña independiente.
- `examples/post_monitor_smoke_client.py`: cliente ejecutable de validación.
