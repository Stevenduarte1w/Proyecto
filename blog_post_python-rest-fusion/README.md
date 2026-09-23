# Blog Post Bot: generación local + publicación REST

Este proyecto conserva el flujo local que genera artículos en español o inglés y crea imágenes originales con OpenAI. La publicación y optimización de posts se realizan por la REST API oficial de WordPress; no se inicia navegador ni Playwright.

El mismo servicio de publicación se usa en los dos canales:

1. **Bot autónomo:** el scheduler toma filas pendientes, genera texto e imagen, y publica en WordPress.
2. **Contenido del orquestador:** `POST /api/orchestrator/jobs` recibe el contenido completo, lo valida, completa la imagen si hace falta y lo publica o actualiza mediante WordPress REST.

## Preparación

1. Crear una copia de `.env.example` llamada `.env` y configurar la base PostgreSQL, `OPENAI_API_KEY` y las opciones de operación.
2. Crear una **Application Password** de WordPress para el usuario del bot en cada sitio. El usuario debe poder editar posts y subir medios. La contraseña normal de `wp-admin` no sirve para Basic Auth REST.
3. Instalar `wordpress/mu-plugins/post-bot-meta.php` en cada sitio como `wp-content/mu-plugins/post-bot-meta.php`. Esto registra las metas REST de Yoast y Elementor que se escriben durante la optimización.
4. Hacer una copia de seguridad de la base de datos anterior y ejecutar `alembic upgrade head`.
5. La migración crea una fila de sitio por campaña y elimina las columnas antiguas de usuario/contraseña de `campaigns`. Para cada sitio, define en el entorno la variable indicada por `wordpress_sites.credential_ref` (inicialmente `WP_SITE_<id>_APP_PASSWORD`) con una Application Password nueva.
6. Instalar dependencias con `uv sync` y arrancar con `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`.

No ejecutes la migración en producción hasta tener las Application Passwords nuevas preparadas y una copia de seguridad verificada. Las contraseñas antiguas de WordPress no se copian: no son válidas para REST y no vuelven a guardarse en la BD.

## Bot autónomo

El scheduler diario usa `SCHEDULER_TIMEZONE` como valor inicial; luego conserva hora, zona y estado en `schedule_config`. El horario puede consultarse/actualizarse con `/api/schedule`. Los trabajos reclaman cada fila atómicamente; dos instancias no procesan la misma fila a la vez. Los fallos quedan en estado `failed` con `last_error` y solo se reintentan cuando se solicitan de nuevo.

Para la imagen, el bot usa la URL de Google Drive de la fila si está presente. Si no hay URL, crea una imagen original a partir de `image_prompt` o del título; esto requiere `OPENAI_API_KEY`. Los temporales se borran al terminar.

Los archivos Excel conservan las columnas de la versión anterior. `image_prompt` es opcional. Se rechaza el archivo completo si faltan columnas requeridas y se informa cada fila con una campaña inexistente o inactiva.

## Envío desde el orquestador

Activa `ORCHESTRATOR_ENABLED=true` y configura un secreto largo en `ORCHESTRATOR_TOKEN`. El orquestador envía `Authorization: Bearer <token>` y un ID estable para deduplicar:

```http
POST /api/orchestrator/jobs
Authorization: Bearer <ORCHESTRATOR_TOKEN>
Content-Type: application/json
```

Ejemplo de creación con contenido ya generado:

```json
{
  "job_id": "uuid-del-trabajo",
  "capability": "posts.create",
  "campaign_id": 1,
  "payload": {
    "title": "Título del artículo",
    "content": "<h1>Título</h1><p>Artículo HTML completo…</p>",
    "seo_title": "Título SEO",
    "meta_description": "Descripción SEO",
    "categories": "Categoría",
    "hashtags": "Etiqueta uno,Etiqueta dos",
    "image_prompt": "Ilustración editorial original, sin texto",
    "citys": "Ciudad",
    "citys_urls": "https://example.com/ciudad"
  }
}
```

Usa `capability: "posts.optimize"` y proporciona `edition_url` o `wp_post_id` para optimizar. El cuerpo y la imagen se preparan antes de actualizar el post, y se guarda una instantánea para `/api/optimized/{id}/rollback`. Envía `keep_featured_image: true` si debe conservar la imagen del post. Una repetición del mismo `job_id` y cuerpo devuelve el resultado guardado; reutilizar el ID con contenido distinto da `409`. Un lote puede devolver `partial_posts` y se reintentan solo sus elementos fallidos.

Este ZIP no incluía el cliente/protocolo WebSocket del repositorio del orquestador. El canal incorporado aquí es una entrada HTTP autenticada para contenido completo. Para que el orquestador existente use su cola `/api/v1/post-bot/ws`, hay que adaptar el transporte en ese repositorio al contrato WebSocket publicado por el orquestador.

## Operación y API

- `GET /api/health`
- `GET /api/campaigns` (no devuelve credenciales)
- `GET|PUT /api/schedule`
- `POST /api/posts/upload/new` y `/api/posts/upload/optimized`
- `POST /api/posts/{id}/run`, `/api/optimized/{id}/run`, `/api/optimized/{id}/rollback`
- `GET /api/executions` y `GET /api/executions/{id}`
- `POST /api/orchestrator/jobs`

WordPress se valida con `GET users/me` y `OPTIONS posts`. Las lecturas repetibles pueden reintentarse; las escrituras no se reenvían automáticamente para evitar duplicar posts o medios.
