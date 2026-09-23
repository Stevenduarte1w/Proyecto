# SEO Dashboard

Dashboard estático servido por FastAPI en:

```text
http://localhost:8001/dashboard/
```

La interfaz conserva las operaciones del dashboard anterior:

- listado de páginas registradas;
- filtro de páginas por campaña y tipo;
- registro y edición en `campaign_pages`, incluida la jerarquía de WordPress;
- consulta de la posición orgánica actual mediante Serper o BrightLocal;
- programación múltiple con prioridad;
- ejecución inmediata y daily;
- cancelación y reintentos;
- descarga de la plantilla XLSX e importación con validación;
- historial de `page_execution_queue`.

Pestañas disponibles:

- `Operaciones SEO`: páginas, programación, cola e importación.
- `Datos base`: campañas, servicios, sitios WordPress y prompt rules.
- `Posts por campaña`: grupos de posts de apoyo y sus ciudades.
- `Bot de posts`: telemetría del bot independiente.

El detalle de campos, columnas del Excel y endpoints está en
[docs/campaign-pages-and-post-groups.md](../docs/campaign-pages-and-post-groups.md).

La vista de resultados usa:

- MongoDB para los artefactos JSON dinámicos;
- Redis para el log vivo;
- PostgreSQL `seo_agent_deep_seek` para campañas, páginas y cola.

No se renderiza `html_preview`.

Archivos:

```text
frontend/index.html
frontend/styles.css
frontend/app.js
```

Configurar autenticación:

```env
DASHBOARD_USER=admin
DASHBOARD_PASS=change-me
```

Configurar la consulta de posiciones:

```env
RANK_PROVIDER=serper
SERPER_API_KEY=your-api-key
SERPER_API_BASE_URL=https://google.serper.dev
SERPER_RANK_NUM_RESULTS=100
SERPER_REQUEST_TIMEOUT_SECONDS=15
```

También se puede usar BrightLocal con `RANK_PROVIDER=brightlocal` y las variables
`BRIGHTLOCAL_*` documentadas en `.env.example`.

El botón `Consultar posición` muestra la posición orgánica exacta de la URL registrada.
Si no existe una coincidencia entre los primeros resultados configurados, muestra
`Fuera del top N`.

## Posts por campaña

La pestaña `Posts por campaña` consume:

```text
GET    /api/v1/seo/post-groups
POST   /api/v1/seo/post-groups
PUT    /api/v1/seo/post-groups/{group_id}
DELETE /api/v1/seo/post-groups/{group_id}
```

Opera sobre `support_post_groups`, `support_post_group_cities` y la vista
`v_support_post_groups` de `seo_agent_deep_seek`. No consulta ni modifica
ejecuciones del workflow SEO.

## Bot de posts independiente

La pestaña `Bot de posts` consume exclusivamente:

```text
GET /api/v1/post-monitor/overview
GET /api/v1/post-monitor/runs
GET /api/v1/post-monitor/alerts
PATCH /api/v1/post-monitor/alerts/{alert_id}
```

Muestra presencia, resultados y alertas reportados por el WebSocket separado
`/api/v1/post-monitor/ws`. No consulta ni modifica ejecuciones del workflow SEO.
