# Bot WebSocket Protocol

Endpoint:

```text
ws://localhost:8005/api/v1/bots/ws
```

Los bots ajenos al flujo de páginas usan un token vinculado al `bot_key`:

```http
Authorization: Bearer <token-del-bot>
```

La configuración `BOT_TOKENS` contiene el mapa JSON `token -> bot_key`. Los bots
que anuncian exclusivamente capacidades del flujo de páginas no necesitan ese
encabezado. La excepción comprende `wordpress.page_upsert`, `seo.main`,
`posts.create`, `video.create`, `pagespeed.check` e `indexing.submit`. Si un bot
anuncia cualquier otra capacidad, incluso mezclada con una de las anteriores,
debe autenticarse y el `bot_key` del registro debe coincidir con la identidad
asociada al token. En producción, el canal debe usar WSS en todos los casos.

## 1. Registro inicial

El primer mensaje enviado por el bot debe ser `bot.register`.

```json
{
  "type": "bot.register",
  "bot_key": "seo-audit-worker-01",
  "name": "SEO Audit Worker 01",
  "bot_type": "seo_audit",
  "capabilities": ["seo.audit", "seo.technical"],
  "version": "1.0.0",
  "max_concurrency": 3,
  "available_slots": 3,
  "active_executions": [],
  "metadata": {
    "host": "worker-01",
    "runtime": "python",
    "dispatch_policy": "available_slots",
    "input_format": "raw_payload"
  }
}
```

`active_executions` es opcional para compatibilidad. Un bot nuevo debe enviarlo
en cada reconexión. El orquestador conserva las ejecuciones activas declaradas y
devuelve en `stale_executions` las que el bot debe descartar porque ya son
terminales o no le pertenecen.

`bot_key` es la identidad estable del bot. Si el bot se reconecta con el mismo
`bot_key`, el orquestador actualiza el registro existente en PostgreSQL.

Respuesta del orquestador:

```json
{
  "type": "bot.registered",
  "status": "ok",
  "session_id": "...",
  "bot": {
    "id": "...",
    "bot_key": "seo-audit-worker-01",
    "bot_type": "seo_audit",
    "capabilities": ["seo.audit", "seo.technical"]
  },
  "stale_executions": []
}
```

## 2. Heartbeat

El bot debe enviar heartbeats antes de que expire `BOT_PRESENCE_TTL_SECONDS`.
La configuracion inicial usa 60 segundos, asi que un intervalo de 20 a 30
segundos es razonable.

```json
{
  "type": "bot.heartbeat",
  "current_jobs": 1,
  "available_slots": 2
}
```

El heartbeat actualiza los slots reportados sin borrar las reservas que el
orquestador mantiene por `execution_id`. El control se aplica a todos los tipos
de bot. La reserva es atómica; por ello un reintento no consume un segundo slot
y una liberación repetida no aumenta artificialmente la capacidad.

Respuesta:

```json
{
  "type": "bot.heartbeat.ack",
  "status": "ok"
}
```

## 3. Comando de ejecucion

Cuando el orquestador asigna una ejecucion, envia:

```json
{
  "type": "execution.run",
  "execution_id": "...",
  "flow_id": "...",
  "capability": "seo.main",
  "stage": "seo_audit",
  "input_document_id": "...",
  "input_url": "/api/v1/executions/{execution_id}/input",
  "result_url": "/api/v1/executions/{execution_id}/result"
}
```

`stage` identifica la etapa concreta que debe ejecutar el bot. Por ejemplo,
un bot con capability `seo.main` puede recibir `seo_audit` o
`wordpress_publish` en ejecuciones diferentes.

El bot debe consultar `input_url`, procesar el trabajo y devolver el resultado en
`result_url` o responder uno de estos mensajes por WebSocket.

Los endpoints HTTP `input_url` y `result_url` tampoco exigen Bearer cuando la
ejecución pertenece a un paso del flujo de páginas y usa una de las capacidades
exentas enumeradas al inicio. Las ejecuciones independientes y las capacidades
ajenas al flujo sí deben enviar el mismo `Authorization: Bearer` del handshake;
el backend comprueba que la ejecución esté asignada a ese bot.

### Inicio y checkpoint de `seo.main`

La ejecución inicial `seo.main / seo_audit` abarca tanto la auditoría como el
rewrite. Al comenzar, el bot envía:

```json
{
  "type": "execution.started",
  "execution_id": "uuid-a"
}
```

Cuando los payloads externos estén listos, pero antes de terminar el rewrite,
envía el checkpoint no terminal:

```json
{
  "type": "execution.checkpoint",
  "execution_id": "uuid-a",
  "flow_id": "uuid-flow",
  "capability": "seo.main",
  "checkpoint": "external_payloads_ready",
  "payload": {
    "schema_version": "seo.audit.checkpoint.v1",
    "audit": {},
    "post_bot_payload": [],
    "video_bot_payload": {
      "schema_version": "video.create.v1",
      "stage": "video_request",
      "flow_id": "uuid-flow",
      "source_execution_id": "uuid-a",
      "campaign_page_id": 123,
      "page_url": "https://example.com/pagina",
      "title": "Video del servicio"
    },
    "rewrite_brief": {},
    "debug": {}
  }
}
```

`post_bot_payload` puede estar vacío. Cuando contiene elementos, cada post debe
cumplir el contrato de `posts.create`. `execution_id` es obligatorio para
correlacionar el checkpoint con la ejecución asignada. El ACK conserva la
ejecución A activa:

```json
{
  "type": "execution.ack",
  "status": "ok",
  "execution_id": "uuid-a",
  "execution_status": "running",
  "internal_state": "page_rewrite_running",
  "checkpoint": "external_payloads_ready",
  "duplicate": false,
  "created_executions": ["uuid-posts", "uuid-video"]
}
```

El checkpoint crea `support_posts` y `video_request` cuando tienen payload. Una
dependencia sin assets queda `skipped`. El checkpoint no marca A como
terminada. Reenviar el mismo checkpoint es seguro y responde con
`duplicate: true`. `rewrite_result` no pertenece al checkpoint.

Después del checkpoint, A continúa la reescritura y envía el `rewrite_result`
real como resultado terminal:

```json
{
  "type": "execution.succeeded",
  "execution_id": "uuid-a",
  "payload": {
    "schema_version": "seo.rewrite.v1",
    "ok": true,
    "stage": "page_rewrite",
    "campaign_page_id": 123,
    "page_update": {
      "updated_elementor_data": {
        "version": "0.4",
        "title": "Página reescrita"
      }
    },
    "pending_insertions": {}
  }
}
```

`updated_elementor_data` debe contener datos. Sin una reescritura válida, el
orquestador no crea `wordpress_publish`.

Una vez terminadas A, posts y video, el input de `wordpress_publish` incluye:

```json
{
  "stage": "wordpress_publish",
  "flow_id": "uuid-flow",
  "source_rewrite_execution_id": "uuid-a",
  "rewrite_result": {},
  "posts_result": {},
  "video_result": {}
}
```

Exito:

```json
{
  "type": "execution.succeeded",
  "execution_id": "...",
  "payload": {
    "summary": "Trabajo terminado"
  }
}
```

Fallo:

```json
{
  "type": "execution.failed",
  "execution_id": "...",
  "error": "Detalle del error"
}
```

Respuesta del orquestador:

```json
{
  "type": "execution.ack",
  "status": "ok",
  "execution_status": "succeeded",
  "error": null
}
```

`status` confirma que el mensaje WebSocket fue procesado. `execution_status`
contiene el estado final decidido por el orquestador. Por ejemplo, una respuesta
PageSpeed puede ser recibida correctamente (`status: ok`) pero quedar rechazada
(`execution_status: failed`) si algun perfil devuelve `can_index: false`.

Los eventos terminales pueden reenviarse hasta recibir el ACK. Si la ejecución ya
era terminal, el orquestador devuelve el mismo estado sin volver a procesar el
payload y libera de forma idempotente cualquier reserva pendiente.

## 4. SAAF backlinks

El bot se registra con capability `backlinks.saaf`, `max_concurrency: 1` y el
catálogo de empresas en su metadata. El catálogo es una fotografía de la fuente
de verdad de SAAF:

```json
{
  "type": "bot.register",
  "bot_key": "saaf-backlinks-01",
  "name": "SAAF Backlinks",
  "bot_type": "backlinks",
  "capabilities": ["backlinks.saaf"],
  "max_concurrency": 1,
  "available_slots": 1,
  "active_executions": [],
  "metadata": {
    "catalog_version": "sha256:8de...",
    "companies": [
      {
        "id": "12",
        "nombre": "Empresa ejemplo",
        "nicho": "odontologia",
        "url": "https://example.com"
      }
    ]
  }
}
```

Cuando cambia `config/empresas.csv`, el bot publica la fotografía nueva:

```json
{
  "type": "bot.catalog.updated",
  "catalog_version": "sha256:91a...",
  "companies": []
}
```

El orquestador responde `bot.catalog.ack`. No edita ni combina el catálogo.

La ejecución es independiente (`step_id = null`) y llega como `execution.run`,
con `capability: "backlinks.saaf"`, `stage: "backlinks_pipeline"` e `input_url`.
El bot descarga el input `backlinks.saaf.input.v1` con el mismo Bearer del WS.

### Progreso persistente

SAAF usa `execution.progress`, no `execution.checkpoint`. `sequence` empieza en
1 y aumenta sin huecos dentro de cada ejecución. El bot conserva el evento en
su outbox hasta recibir el ACK.

```json
{
  "type": "execution.progress",
  "event_id": "4d2fb0ad-ac17-4872-a627-d4c2bf55dc57",
  "execution_id": "a8dd51ee-b427-4cbf-a271-d4cbe1b2378f",
  "sequence": 18,
  "event_type": "site.done",
  "stage": "publicar",
  "summary": "7 de 100 sitios procesados",
  "payload": {
    "url": "https://directorio.example",
    "estado": "backlink_verificado"
  }
}
```

Tipos permitidos: `run.start`, `stage.start`, `stage.end`, `site.start`,
`site.done`, `stats`, `log`, `run.end` y `error`. Un `stage.end` debe incluir
enteros `payload.in` y `payload.out`.

ACK normal o duplicado:

```json
{
  "type": "execution.progress.ack",
  "status": "stored",
  "execution_id": "a8dd51ee-b427-4cbf-a271-d4cbe1b2378f",
  "event_id": "4d2fb0ad-ac17-4872-a627-d4c2bf55dc57",
  "sequence": 18,
  "expected_sequence": 19
}
```

`status` puede ser `stored`, `duplicate`, `gap` o `error`. Ante `gap`, el bot
debe reenviar desde `expected_sequence`. Un duplicado se considera confirmado y
se elimina de la outbox.

### Cancelación cooperativa

El orquestador envía:

```json
{
  "type": "execution.cancel",
  "execution_id": "a8dd51ee-b427-4cbf-a271-d4cbe1b2378f"
}
```

SAAF termina el sitio actual, guarda checkpoint y cierra el navegador. Solo
entonces responde:

```json
{
  "type": "execution.cancelled",
  "execution_id": "a8dd51ee-b427-4cbf-a271-d4cbe1b2378f"
}
```

Mientras tanto la ejecución permanece `cancelling`. Si el bot reconecta en ese
estado, el orquestador reenvía la orden. El bot debe tratarla de forma
idempotente.

## 5. Protocolo de indexación

`indexing.submit` recibe el payload en línea:

```json
{
  "type": "execution.start",
  "bot_type": "indexing.submit",
  "stage": "indexing_submit",
  "flow_id": "...",
  "execution_id": "...",
  "campaign_page_id": 123,
  "payload": {
    "schema_version": "indexing.submit.input.v1",
    "page_url": "https://example.com/page/",
    "urls_to_index": [
      "https://example.com/page/",
      "https://example.com/post-1/",
      "https://example.com/post-2/"
    ],
    "providers": {
      "google_search_console": true,
      "twoindex_ninja": true
    }
  }
}
```

El bot responde con `execution.result`. Solo `ok: true`, schema
`indexing.result.v1` y estado `submitted` completan el flujo.

## Responsabilidades por capa

- PostgreSQL: registro persistente del bot, capabilities, version y `last_seen_at`.
- Redis: presencia temporal online/offline y estado vivo de la conexion.
- WebSocket: canal activo para heartbeat y comandos hacia el bot.
- MongoDB: payload completo del flujo referenciado por `flow_id`.
