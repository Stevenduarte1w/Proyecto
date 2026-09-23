# Campañas, páginas y posts por campaña

Este documento describe cómo se administran desde el dashboard los datos que el
bot de WordPress y el flujo SEO necesitan: configuración por campaña, campos de
página, jerarquía real de WordPress, importación por Excel y grupos de posts de
apoyo.

Todo se guarda en la base `seo_agent_deep_seek`. No hay tablas nuevas: se usan
las columnas que ya existían en `campaigns`, `campaign_pages`,
`support_post_groups` y `support_post_group_cities`.

## Dónde va cada dato

La regla es una sola: **lo que se repite en toda la campaña se configura una vez
en la campaña; en la página solo se guardan las excepciones.**

| Dato | Campaña (`campaigns`) | Página (`campaign_pages`) |
| --- | --- | --- |
| Layout | `layout_id`, `layout_branch` | Solo si esa página usa otro |
| Canal de YouTube | `youtube_channel_id` | Solo para sobrescribir |
| Formulario Elementor | `default_elementor_form_id` | `elementor_form_id`, solo para sobrescribir |
| Plantilla de página | — | `page_template` |
| Código postal | — | `postal_code` |
| Jerarquía de WordPress | — | `parent_campaign_page_id`, `parent_slug`, `parent_required` |

`parent_wp_page_id` no se escribe a mano en ningún lado: lo resuelve el
orquestador a partir de la página padre indicada.

## Configuración de campaña

Pestaña **Datos base → campaigns**. Además de los campos que ya existían, el
formulario incluye:

- `layout_id`
- `layout_branch` (`cities` o `services`; por defecto `cities`)
- `youtube_channel_id` (ID del canal que empieza por `UC`, nunca la URL completa)
- `default_elementor_form_id`

Se configuran una sola vez por campaña y no hace falta repetirlos en cada fila
del Excel.

## Registro y edición de páginas

Pestaña **Operaciones SEO**. El formulario de página conserva los campos
anteriores y agrega el grupo *WordPress: jerarquía y plantilla*:

- `postal_code`
- `page_template`
- `parent_campaign_page_id` mediante un selector de páginas de la misma campaña
- `parent_slug`, para cuando la página padre todavía no está registrada
- `parent_required`
- `elementor_form_id`, `youtube_channel_id`, `layout_id`, `layout_branch`, solo
  como excepción a la configuración de la campaña

Cada fila de la tabla tiene el botón **Editar**, que carga la página en el mismo
formulario y lo cambia a modo actualización (`PUT /api/v1/seo/pages/{id}`). La
campaña no se puede cambiar al editar. La actualización es parcial: solo se
escriben los campos enviados.

### Cómo se resuelve la página padre

1. Si se indica `parent_campaign_page_id`, debe existir y pertenecer a la misma
   campaña; de lo contrario la operación falla.
2. Si solo se indica `parent_slug`, se busca esa página dentro de la campaña.
3. Si se encuentra, se guardan `parent_campaign_page_id`, `parent_slug` y
   `parent_wp_page_id` tomados de la página padre.
4. Si no se encuentra, se conserva `parent_slug` y `parent_wp_page_id` queda
   nulo: el bot de WordPress resuelve el padre por ruta en el sitio.

`parent_city` es una relación geográfica para páginas de barrio y no reemplaza a
`parent_slug` ni a `parent_campaign_page_id`.

## Importación por Excel

El botón **Descargar plantilla** entrega el archivo generado por
`GET /api/v1/seo/pages/import-template`. La plantilla tiene dos hojas:

- `programacion`: la hoja que se completa. Fila 1 con los encabezados, listas
  desplegables en las columnas con valores cerrados y un comentario por columna.
- `guia`: descripción, ejemplo y valores válidos de cada columna.

Las columnas obligatorias no cambiaron:

`campaign_slug`, `url`, `page_type`, `primary_keyword`, `scheduled_for`

Las opcionales agregadas en esta versión:

`postal_code`, `parent_campaign_page_id`, `parent_slug`, `parent_required`,
`page_template`, `elementor_form_id`, `youtube_channel_id`, `layout_id`,
`layout_branch`, `priority`

Ejemplo mínimo:

| campaign_slug | url | slug | page_type | primary_keyword | postal_code | parent_slug | scheduled_for |
| --- | --- | --- | --- | --- | --- | --- | --- |
| boxmarkdigital-com | https://ejemplo.com/fences/aurora/ | fences-aurora | service_city | Fence Company Aurora | 60505 | fences | 2026-09-25 |

Notas de uso:

- El canal de YouTube, el formulario y el layout no hace falta ponerlos: se
  heredan de la campaña.
- No existe una columna de acción. El flujo decide solo: `wp_page_id` vacío
  crea la página, `wp_page_id` con valor la actualiza, y una página ya
  optimizada omite la etapa de WordPress.
- La cola se marca `success`/`published` cuando la etapa de publicación en
  WordPress termina bien. Si luego falla la indexación o PageSpeed, el detalle
  queda en **Error / advertencia** y se debe verificar y completar manualmente
  la indexación pendiente; no se vuelve a crear la página por ese fallo.
- **Reintentar** solo aparece para ejecuciones `failed` o `cancelled` y crea una
  ejecución nueva. En ella, la etapa inicial vuelve a decidir con los datos
  actuales: si ya existe una ejecución `success`/`published`, hace `skip`;
  si no y hay `wp_page_id`, hace `update`; en otro caso, `create`.
- **Ejecutar daily** toma cada fila `queued` de forma atómica y la cambia a
  `running` antes de crear el flujo. Así otra pulsación no crea un flujo
  duplicado, incluso si el arranque se interrumpe. `running` indica que el
  orquestador tomó el trabajo, no necesariamente que el bot ya lo recibió;
  el mensaje del botón separa envíos reales y esperas de bot.
- Para registrar una página que ya fue optimizada, use `page_status=published`;
  el flujo conservará el slug registrado y omitirá la etapa inicial.
- `priority` controla el orden en `page_execution_queue`; el número menor se
  ejecuta primero.
- La fuente única de la plantilla es
  `src/orchestrator/application/import_template.py`. Para regenerar el archivo
  versionado en la raíz del repositorio:

  ```bash
  python tools/build_import_template.py
  ```

## Posts por campaña

Pestaña **Posts por campaña**, sobre `support_post_groups`,
`support_post_group_cities` y la vista `v_support_post_groups`.

Un grupo representa un post de apoyo y las ciudades que lo comparten. La vista
permite:

- filtrar por campaña, estado del post, estado/región y texto libre (región,
  título, keyphrase, slug o ciudad);
- crear y editar grupos, con su título, keyphrase, slug, categoría, URL
  publicada, prioridad y estado;
- mover un grupo a otra campaña desde el mismo formulario de edición;
- administrar las ciudades del grupo, una por línea, con el formato `Ciudad` o
  `Ciudad, ST`. Sin estado en la línea se usa el del grupo.

Valores admitidos por la base:

- `group_type`: `state_general`, `county`, `metro`, `regional`, `custom`
- `status`: `active`, `paused`, `archived`
- `post_status`: `empty`, `defined`, `creating`, `published`, `failed`

Restricciones a tener en cuenta:

- `region_name` es único por campaña y estado.
- Las ciudades repetidas dentro de un grupo se descartan antes de guardar,
  usando la misma normalización que la función `support_post_city_key` de la
  base (minúsculas, sin acentos ni signos).
- `state_key` y `city_key` son columnas generadas por PostgreSQL; el
  orquestador nunca las escribe.

Esta pestaña administra el contenido de los posts. La pestaña **Bot de posts**
sigue siendo independiente y solo muestra la telemetría del bot.

## Endpoints

```text
GET    /api/v1/seo/pages
POST   /api/v1/seo/pages
PUT    /api/v1/seo/pages/{campaign_page_id}
POST   /api/v1/seo/pages/import-xlsx
GET    /api/v1/seo/pages/import-template
GET    /api/v1/seo/post-groups
POST   /api/v1/seo/post-groups
PUT    /api/v1/seo/post-groups/{group_id}
DELETE /api/v1/seo/post-groups/{group_id}
```
