# Canal de trabajo del bot de posts — `/api/v1/post-bot/ws`

> Endpoint WebSocket que **asigna trabajo** al bot de posts (`posts.create` y
> `posts.optimize`) manteniéndolo **fuera del motor de workflows SEO**.
>
> Implementado en el orquestador. El cliente del bot necesita un ajuste mínimo
> (§7) que **todavía no está hecho**.

---

## 1. Por qué un tercer endpoint

El repositorio ya tenía dos canales, y ninguno servía para este caso:

| Endpoint | Asigna trabajo | Aislado del flujo SEO |
|---|---|---|
| `/api/v1/bots/ws` | ✅ | ❌ sus resultados avanzan etapas del workflow |
| `/api/v1/post-monitor/ws` | ❌ [por diseño](independent-post-bot-websocket.md) | ✅ |
| **`/api/v1/post-bot/ws`** | ✅ | ✅ |

El bot de posts necesita las dos cosas a la vez: recibir trabajo y no participar
del flujo de páginas.

### Invariantes de aislamiento

Verificados con pruebas automáticas en
`tests/unit/test_post_bot_channel.py`:

1. No importa `AdvanceWorkflow`, `DispatchExecution`, `SubmitExecutionResult`
   ni `ProcessExecutionCheckpoint`.
2. No lee ni escribe `flows`, `flow_steps`, `executions` ni
   `execution_checkpoints`. Solo usa las tablas `post_bot_*`.
3. Tiene su propio gestor de conexiones (`post_bot_ws_manager`), su propia
   entrada en `BOT_TOKENS` y su propio TTL de presencia. Comparte con el canal
   del workflow únicamente el resolutor de credenciales, que no arrastra lógica
   de workflow.
4. Rechaza con `unsupported_message_type` cualquier mensaje del protocolo del
   workflow (`execution.checkpoint`, `execution.progress`, …).

---

## 2. Instalación

```bash
alembic upgrade head        # crea post_bot_workers, post_bot_jobs, post_bot_job_events
```

La credencial vive en **`BOT_TOKENS`**, el mismo almacén que usa
`/api/v1/bots/ws`, con su propia entrada token → `bot_key`:

```env
BOT_TOKENS={"<secreto-del-post-bot>":"post-bot-prod-01"}
POST_BOT_PRESENCE_TTL_SECONDS=60
POST_BOT_MAX_MESSAGE_BYTES=262144
```

El endpoint resuelve el token con `authenticated_bot_key()` y **exige que el
`bot_key` del mensaje `bot.register` coincida** con el que mapea ese token. Un
token filtrado no permite suplantar otra identidad.

> Compartir `BOT_TOKENS` entre los dos canales tiene una contrapartida: ese
> mismo token también autentica en `/api/v1/bots/ws`. Para el bot de posts es
> inocuo mientras no se conecte ahí, pero conviene saberlo al rotar secretos.

---

## 3. Protocolo

Se reutilizan **los mismos nombres de mensaje** que ya habla
`WebSocketBotClient` del bot, para no reescribir el cliente.

### Bot → orquestador

| Mensaje | Campos | Notas |
|---|---|---|
| `bot.register` | `bot_key`, `name`, `bot_type`, `capabilities`, `version`, `max_concurrency`, `available_slots`, `metadata`, `active_jobs` | Primer mensaje obligatorio. `capabilities` solo admite `posts.create` y `posts.optimize` |
| `bot.heartbeat` | `current_jobs`, `available_slots` | Si `available_slots > 0` el orquestador aprovecha para repartir cola |
| `execution.started` | `execution_id` | Opcional. Marca el trabajo como `running` |
| `execution.succeeded` | `execution_id`, `payload` | Cierra el trabajo |
| `execution.failed` | `execution_id`, `error`, `payload` | `payload` puede traer `partial_posts` |

### Orquestador → bot

| Mensaje | Campos |
|---|---|
| `bot.registered` | `session_id`, `bot`, `requeued_jobs`, `heartbeat_interval_seconds` |
| `bot.heartbeat.ack` | `status` |
| `execution.run` | `execution_id`, `job_id`, `capability`, `input_url`, `result_url`, `payload` |
| `execution.ack` | `status`, `execution_id`, `job_status`, `duplicate` |
| `error` | `code`, `message`, `retryable` |

`execution.run` incluye el `payload` completo **y** un `input_url`, así que el
bot puede usar cualquiera de las dos vías sin cambios.

---

## 4. Ciclo de vida de un trabajo

```
 queued ──claim──▶ dispatched ──execution.started──▶ running
   ▲                   │                               │
   │                   └───────────┬───────────────────┘
   │                               ▼
   │                   succeeded / failed
   └── requeued (reconexión del worker o fallo al enviar)

 queued ──cancel──▶ cancelled        (solo mientras siga en cola)
```

Garantías:

- **Reparto en exclusiva.** Los candidatos se reclaman con
  `SELECT … FOR UPDATE SKIP LOCKED` y se marcan `dispatched` en la misma
  sentencia, así que dos instancias del orquestador no entregan el mismo trabajo.
- **Si falla el envío por el socket**, el trabajo vuelve a `queued`
  automáticamente.
- **Un resultado repetido no sobrescribe.** Reenviar `execution.succeeded` de un
  trabajo ya terminal devuelve `execution.ack` con `duplicate: true`.
- **Idempotencia al encolar.** `external_ref` es único: reenviar la misma
  petición devuelve `200` con el trabajo existente; el mismo `external_ref` con
  otro payload devuelve `409`.
- **Un worker solo recibe sus capacidades declaradas.**

---

## 5. API REST

Las rutas de gestión piden el usuario del dashboard (Basic). La de `input` pide
el Bearer del bot, porque quien la consume es el bot.

| Ruta | Método | Auth | Descripción |
|---|---|---|---|
| `/api/v1/post-bot/jobs` | POST | Basic | Encola un trabajo y lo despacha si hay worker libre |
| `/api/v1/post-bot/jobs` | GET | Basic | Lista, filtrable por `status` y `capability` |
| `/api/v1/post-bot/jobs/{id}` | GET | Basic | Detalle |
| `/api/v1/post-bot/jobs/{id}/input` | GET | **Bearer** | Documento que descarga el bot; solo entrega trabajos asignados a **su** worker |
| `/api/v1/post-bot/jobs/{id}/cancel` | POST | Basic | Cancela, solo si sigue en cola |
| `/api/v1/post-bot/workers` | GET | Basic | Workers y su presencia |
| `/api/v1/post-bot/overview` | GET | Basic | Conteos por estado |

Encolar un post:

```bash
curl -u admin:pass -X POST http://localhost:8001/api/v1/post-bot/jobs \
  -H 'Content-Type: application/json' \
  -d '{
        "capability": "posts.create",
        "external_ref": "campaign-12-post-2026-09-22",
        "payload": {
          "campaign_id": 12,
          "post_title": "Amarres de amor efectivos",
          "content": "<h1>…</h1>",
          "category": "Amarres",
          "image_prompt": "altar con velas rojas"
        }
      }'
```

Optimizar uno existente:

```bash
curl -u admin:pass -X POST http://localhost:8001/api/v1/post-bot/jobs \
  -H 'Content-Type: application/json' \
  -d '{
        "capability": "posts.optimize",
        "payload": {
          "campaign_id": 12,
          "edition_url": "https://sitio.com/amarres-de-amor/",
          "post_title": "Amarres de amor efectivos",
          "content": "<h1>…</h1>"
        }
      }'
```

El `payload` viaja tal cual hasta el bot: el orquestador **no lo interpreta**,
solo lo transporta. El contrato de sus campos es del bot.

---

## 6. Qué recibe el bot

```json
{
  "type": "execution.run",
  "execution_id": "0c2f…",
  "job_id": "0c2f…",
  "capability": "posts.create",
  "flow_id": "",
  "stage": null,
  "input_url": "/api/v1/post-bot/jobs/0c2f…/input",
  "result_url": "/api/v1/post-bot/jobs/0c2f…",
  "payload": { "campaign_id": 12, "post_title": "…" }
}
```

`GET input_url` devuelve:

```json
{
  "execution_id": "0c2f…",
  "job_id": "0c2f…",
  "capability": "posts.create",
  "created_at": "2026-09-22T02:00:00+00:00",
  "payload": { "campaign_id": 12, "post_title": "…" }
}
```

Es el mismo envoltorio `{"payload": …}` que ya espera `_input_payload()` en
`app/main.py` del bot, así que su extractor de posts funciona sin cambios.

---

## 7. ⚠️ Lo que falta en el cliente del bot

El `WebSocketBotClient` actual conecta con `ws_connect(url)` **sin cabeceras**,
así que si `POST_BOT_WS_TOKEN` está configurado el servidor cierra con **4401**.
Dos ajustes en `blog_post_python`:

**a) Enviar el token** (obligatorio). Es el valor de `BOT_TOKENS` cuya
`bot_key` sea la del bot:

```python
# app/clients/websocket_client.py
async with ws_connect(
    self.url,
    additional_headers={"Authorization": f"Bearer {settings.ORCHESTRATOR_TOKEN}"},
) as ws:
```

Y al descargar el input en `app/main.py`:

```python
response = requests.get(
    _orchestrator_url(input_url),
    headers={"Authorization": f"Bearer {settings.ORCHESTRATOR_TOKEN}"},
    timeout=...,
)
```

**b) Reportar los trabajos en curso al reconectar** (recomendado):

```python
msg = {
    "type": "bot.register",
    ...,
    "active_jobs": [str(job_id) for job_id in self._active_executions],
}
```

Sin esto, si el bot reconecta **mientras está publicando**, el orquestador da
ese trabajo por huérfano, lo devuelve a la cola y puede entregarlo otra vez —
publicando el post dos veces. Con `active_jobs` el trabajo se respeta.

Mientras no se haga (b), conviene no reiniciar el bot con publicaciones en
curso.

---

## 8. Pruebas

```bash
.venv/Scripts/python -m pytest tests/unit/test_post_bot_channel.py -q
```

17 pruebas: contrato de mensajes, reparto, devolución a la cola ante fallo de
socket, respeto de capacidades, reconexión con y sin `active_jobs`, resultado
duplicado, recorrido WebSocket completo, y las dos de aislamiento (no importar
el motor de workflows, no tocar sus tablas).

---

## 9. Pendiente antes de producción

1. Añadir la entrada del bot a `BOT_TOKENS` y servir el endpoint sobre WSS
   (en `production` el propio endpoint exige `wss`).
2. Aplicar los dos ajustes del cliente (§7).
3. Bloqueo de sesión duplicada si se despliegan varias instancias con el mismo
   `bot_key` (hoy la segunda conexión desplaza a la primera con código 1012).
4. Reaper de trabajos `dispatched` que se quedan colgados si el worker muere sin
   cerrar el socket: hoy se recuperan en la siguiente reconexión de ese worker.
5. Pestaña en el dashboard, si se quiere operar la cola desde la interfaz;
   la API REST ya está.
