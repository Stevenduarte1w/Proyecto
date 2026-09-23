# Integración del backend de Instagram

El backend Django se registra en `WS /api/v1/bots/ws` como un único adaptador:

```json
{
  "type": "bot.register",
  "bot_key": "instagram-backend-01",
  "name": "Instagram Backend",
  "bot_type": "instagram",
  "capabilities": ["instagram.maduracion", "instagram.prospecting"],
  "max_concurrency": 10,
  "available_slots": 10
}
```

El número de máquinas Selenium queda encapsulado detrás del adaptador. El
orquestador solo ve este bot y los slots que reporta. Se conserva sin cambios el
protocolo WebSocket documentado en `docs/bot-websocket-protocol.md`.

## Crear una ejecución autónoma

```http
POST /api/v1/executions/standalone/instagram
Content-Type: application/json
Authorization: Bearer <token de worker>
```

El endpoint exige credenciales. Acepta dos formas y con cualquiera de las dos
alcanza:

- `Authorization: Bearer <token>` con un token presente en `BOT_TOKENS` (es el
  camino del adaptador Django, el mismo token que usa para registrarse).
- `Authorization: Basic ...` con `DASHBOARD_USER` / `DASHBOARD_PASS` (es el
  camino del dashboard).

Si `DASHBOARD_USER` y `DASHBOARD_PASS` están vacíos el endpoint queda abierto,
igual que el resto del panel. Ver `docs/instagram-auth-setup.md`.

Ejemplo para maduración:

```json
{
  "schema_version": "instagram.maduracion.input.v1",
  "stage": "instagram_maduracion",
  "capability": "instagram.maduracion",
  "task_types": [1, 4, 7],
  "targets": {
    "mode": "accounts",
    "account_ids": [12, 45, 78],
    "owner_id": null
  },
  "custom_task": {
    "type": "muro",
    "post": "texto del post",
    "links_image": ["https://example.com/image.jpg"]
  },
  "schedule": {"start_date": "2026-09-18T14:00:00Z"},
  "options": {"bot_executor": null, "max_accounts": 50}
}
```

`capability` acepta `instagram.maduracion` o `instagram.prospecting`.
`task_types` es una lista obligatoria y no vacía de enteros. `targets.mode`
acepta `accounts`, `owner` o `all`; `accounts` exige `account_ids` no vacío y
`owner` exige `owner_id`. `custom_task`, `schedule` y `options` son opcionales.

La respuesta HTTP es `202 Accepted` y contiene la ejecución. Esta usa un
`flow_id` UUID sintético y `step_id: null`; no crea un flow, un flow step ni un
checkpoint. El objeto enviado se guarda íntegro como input y es la respuesta de:

```http
GET /api/v1/executions/{execution_id}/input
```

Cuando hay capacidad, el adaptador recibe el mensaje `execution.run` habitual y
consulta su `input_url`. Si no hay un adaptador online con slots libres, la
ejecución permanece `pending`.

## Resultado

El adaptador termina mediante `execution.succeeded` o `execution.failed`. Un
resultado exitoso tiene esta forma:

```json
{
  "type": "execution.succeeded",
  "execution_id": "uuid-ejecucion",
  "payload": {
    "schema_version": "instagram.maduracion.result.v1",
    "ok": true,
    "stage": "instagram_maduracion",
    "totals": {"created": 12, "ok": 11, "error": 1},
    "tasks": [
      {
        "task_bot_id": 8821,
        "account_id": 45,
        "status": "OK",
        "bot_executor": "Bot_Instagram_DESKTOP-MG4482N",
        "end_date": "2026-09-18T15:04:11Z",
        "comment": {}
      }
    ]
  }
}
```

El payload se persiste como un diccionario libre. No se valida contra los
esquemas de resultado SEO ni avanza un workflow, porque la ejecución no tiene
`step_id`.

## Consulta desde el dashboard

Las vistas de solo lectura de Instagram viven bajo `/api/v1/instagram` y están
acotadas a las capabilities `instagram.maduracion` e `instagram.prospecting`:
nunca devuelven ejecuciones de páginas, backlinks ni del resto de flujos. Todas
exigen Basic del dashboard.

```http
GET /api/v1/instagram/catalog
GET /api/v1/instagram/executions?capability=&status=&limit=50
GET /api/v1/instagram/executions/{execution_id}/result
```

- `catalog` es un proxy al backend Django; responde `503` si faltan
  `INSTAGRAM_BACKEND_URL` o `INSTAGRAM_BACKEND_TOKEN`, y `502` si Django falla.
- `executions` devuelve `{"items": [...], "total": n}` con una vista reducida
  (sin ids de documento, sin `error_message` ni `internal_state`). `total` es
  el conteo real de coincidencias, no el tamaño de la página. `capability`, si
  viene, debe ser una de Instagram: cualquier otra da `422`.
- `result` devuelve solo el `payload` del documento de salida. Da `409`
  mientras la ejecución sigue en curso y `404` si el id no es de una ejecución
  de Instagram.

## Decisión de concurrencia

El control de capacidad se aplica a todos los tipos de bot. Antes de asignar una
ejecución, el orquestador reserva atómicamente en Redis uno de los
`available_slots` reportados. Si no hay capacidad, no envía `execution.run` y
conserva la ejecución en estado `pending`. La reserva por `execution_id` hace
idempotentes los reintentos.

Al registrar el adaptador se intentan despachar pendientes hasta el límite de
slots informado. Cada heartbeat actualiza esa capacidad y, si vuelve a ser
positiva, dispara el mismo intento de despacho de pendientes. El adaptador debe
seguir reportando `current_jobs` y `available_slots` reales en cada heartbeat.
