# Bot de creación y actualización de páginas WordPress

## Objetivo

Este bot prepara la página de WordPress antes de comenzar la auditoría SEO. Se
registra en el WebSocket general del orquestador con la capacidad:

```json
{
  "type": "bot.register",
  "bot_key": "wordpress-page-setup-01",
  "name": "WordPress Page Setup",
  "bot_type": "wordpress",
  "capabilities": ["wordpress.page_upsert"],
  "max_concurrency": 1,
  "available_slots": 1
}
```

El slug se define cuando se registra `campaign_pages`. El bot debe usarlo tal
como lo recibe: no debe generarlo, corregirlo ni reemplazarlo.

Este bot puede conectarse sin `Authorization: Bearer` porque
`wordpress.page_upsert` pertenece al flujo de páginas. En producción debe seguir
usando WSS. Si anuncia además una capacidad ajena al flujo de páginas, el
orquestador sí exigirá un token configurado en `BOT_TOKENS`.

Tampoco necesita token para descargar `input_url`, enviar `result_url` ni
escribir en `log_url` o `artifacts_url`. Esos endpoints reconocen que la
ejecución pertenece al flujo de páginas.

## Cuándo se ejecuta

El orquestador calcula la acción antes de crear el workflow:

- `skip`: existe una optimización exitosa anterior o la página está publicada;
- `update`: no está optimizada y tiene `wp_page_id`;
- `create`: no está optimizada y no tiene `wp_page_id`.

Con `skip` no se envía trabajo al bot y `seo_audit` empieza directamente.

## Comando

El bot recibe un mensaje `execution.run` normal:

```json
{
  "type": "execution.run",
  "execution_id": "UUID",
  "flow_id": "UUID",
  "capability": "wordpress.page_upsert",
  "stage": "wordpress_page_setup",
  "input_url": "/api/v1/executions/UUID/input",
  "result_url": "/api/v1/executions/UUID/result"
}
```

Debe consultar `input_url`. El documento contiene un objeto `payload` con este
contrato:

```json
{
  "schema_version": "wordpress.page_setup.input.v1",
  "stage": "wordpress_page_setup",
  "action": "create",
  "queue_execution_id": 456,
  "campaign_page_id": 123,
  "campaign_id": 10,
  "page_url": "https://ejemplo.com/abogado-familia/",
  "slug": "abogado-familia",
  "wp_page_id": null,
  "log_url": "/api/v1/page-executions/456/log",
  "log_method": "PUT",
  "artifacts_url": "/api/v1/page-executions/456/artifacts"
}
```

Para `update`, `wp_page_id` siempre está presente. El bot debe buscar primero
por ese ID y conservar el slug recibido.

`create` también debe ser idempotente: antes de crear, el bot debe buscar una
página existente con el slug exacto recibido. Si ya existe, debe reutilizarla
y devolver su `wp_page_id`, sin crear un duplicado y sin cambiar el slug.

## Eventos y resultado

Al comenzar:

```json
{
  "type": "execution.started",
  "execution_id": "UUID"
}
```

Al completar correctamente:

```json
{
  "type": "execution.succeeded",
  "execution_id": "UUID",
  "payload": {
    "schema_version": "wordpress.page_setup.result.v1",
    "ok": true,
    "action": "create",
    "wp_page_id": 789,
    "slug": "abogado-familia",
    "page_url": "https://ejemplo.com/abogado-familia/",
    "template_applied": true
  }
}
```

`action` debe coincidir con la orden (`create` o `update`) y `wp_page_id` debe
ser un entero positivo. `slug` es opcional en la respuesta; si se envía, debe
ser idéntico al registrado. El orquestador sólo persiste el nuevo
`wp_page_id`: nunca reemplaza el slug usando la respuesta del bot.

Ante un fallo:

```json
{
  "type": "execution.failed",
  "execution_id": "UUID",
  "error": "Descripción breve del error",
  "payload": {
    "ok": false
  }
}
```

Si esta etapa falla, el workflow se detiene y no inicia `seo_audit`.
