# Diseño técnico — Bot v3 (unificación de `main` + `post-orquestador`)

> Documento de desarrollo para la nueva versión del bot.
> Objetivo: conservar **todo** lo que hace `main` (generación de contenido,
> scheduler diario, carga masiva desde Excel, base de datos propia y flujo de
> optimización de posts existentes), pero **sustituyendo Playwright/Chromium por
> la REST API de WordPress** ya probada en `post-orquestador`, y añadiendo un
> **canal propio contra el orquestador, independiente del flujo original**.

---

## 1. Resumen ejecutivo

| | `main` | `post-orquestador` | **v3 (este diseño)** |
|---|---|---|---|
| Generación de contenido | ✅ GPT-4 | ❌ | ✅ **se conserva** |
| Scheduler diario | ✅ | ❌ | ✅ **se conserva** |
| Carga masiva Excel | ✅ | ❌ | ✅ **se conserva** |
| Base de datos propia | ✅ | ❌ (lee la del SEO Agent) | ✅ **propia, ampliada** |
| Optimización de posts | ✅ Playwright | ❌ | ✅ **reescrita sobre REST** |
| Publicación | Playwright/Chromium | REST API | ✅ **REST API** |
| Canal con el orquestador | ❌ | ✅ | ✅ **independiente del flujo local** |
| Credenciales WP | en la BD, texto plano | Application Password en `.env` | ✅ **Application Password en `.env`** |

**Lo que desaparece:** `playwright`, Chromium, `PlaywrightClient`, las capturas
de pantalla de error, `show_alert()`, el `document.body.style.zoom = '33%'`, la
navegación por Tabs y todos los selectores de `wp-admin`.

**Lo que se hereda intacto:** los *prompts* de `NewPostContent` (son el valor
editorial del producto) y el `WordPressClient` de `post-orquestador` (ampliado).

---

## 2. Principios de diseño

1. **Fidelidad de comportamiento.** El alcance es sustituir el transporte
   (Playwright → REST), no cambiar lo que se publica. Ante cualquier duda, manda
   lo que hace `main` hoy, incluidas sus rarezas. Las mejoras detectadas se
   anotan en §18 y se deciden aparte.
2. **Un solo núcleo de publicación.** Los tres orígenes de trabajo (scheduler,
   API manual, orquestador) convergen en el mismo `PublishingService`. Nada de
   duplicar la lógica de WordPress por canal.
3. **Los canales son independientes entre sí.** El scheduler y el orquestador no
   comparten cola, ni presupuesto de concurrencia, ni estado en base de datos.
   Que uno se caiga o se sature no debe afectar al otro.
4. **Nunca dejar un post a medio configurar.** Al crear: borrador primero,
   publicar al final. Al optimizar: una sola escritura con todos los campos, y
   un *snapshot* previo guardado para poder revertir.
5. **El fallo se registra, no se pierde.** Toda ejecución (de cualquier canal)
   queda en base de datos con su log, su error y su resultado.
6. **Sin secretos en la base de datos.** Las contraseñas viven en `.env`,
   referenciadas por nombre desde la tabla de sitios.

---

## 3. Arquitectura

```
  ORIGEN DE TRABAJO                 NÚCLEO                        DESTINO

  ┌──────────────────┐
  │ Excel (.xlsx)    │──▶ posts / optimized_posts (BD propia)
  └──────────────────┘                 │
                                       ▼
  ┌──────────────────┐        ┌────────────────────┐
  │ SchedulerRunner  │───────▶│                    │
  │ (hora diaria)    │        │                    │
  └──────────────────┘        │                    │
                              │  PublishingService │      ┌──────────────────┐
  ┌──────────────────┐        │  ────────────────  │      │  WordPressClient │
  │ API manual       │───────▶│  · ContentService  │─────▶│  (REST wp/v2)    │─▶ WordPress
  │ POST /api/...    │        │  · ImageService    │      └──────────────────┘
  └──────────────────┘        │  · WordPressSite   │
                              │    Service         │
  ┌──────────────────┐        │                    │
  │ OrchestratorChan.│───────▶│                    │
  │ (WebSocket)      │        └────────────────────┘
  └──────────────────┘                 │
                                       ▼
                              ┌────────────────────┐
                              │ executions +       │
                              │ execution_logs     │  (BD propia)
                              └────────────────────┘
```

Cada origen tiene su **adaptador**, cuya única responsabilidad es traducir su
entrada a un `PublishRequest` u `OptimizeRequest` y decidir qué hacer con el
resultado. El núcleo no sabe de dónde viene el trabajo.

---

## 4. Estructura de módulos propuesta

```
app/
├── main.py                      # FastAPI + arranque de canales
├── router.py                    # API HTTP (delgada)
│
├── channels/                    # ← NUEVO: los tres orígenes de trabajo
│   ├── scheduler.py             #   SchedulerRunner (hora diaria, claim atómico)
│   ├── orchestrator.py          #   OrchestratorChannel (WebSocket, independiente)
│   └── manual.py                #   Disparos puntuales desde la API
│
├── core/                        # ← NUEVO: el núcleo compartido
│   ├── publishing_service.py    #   publish() y optimize()
│   ├── requests.py              #   PublishRequest / OptimizeRequest / Result
│   └── worker_pool.py           #   ThreadPoolExecutor por canal
│
├── clients/
│   ├── wordpress_client.py      # heredado de post-orquestador + métodos nuevos
│   └── websocket_client.py      # heredado de post-orquestador, sin cambios
│
├── controllers/
│   └── content_controller.py    # heredado de main (NewPostContent), saneado
│
├── services/
│   ├── wordpress_site.py        # reescrito sobre la BD propia (ORM)
│   ├── post.py                  # + claim atómico de pendientes
│   ├── optimize.py              # + claim atómico + snapshot
│   ├── execution.py             # ejecuciones persistidas (sustituye el tracker en memoria)
│   └── schedule_config.py       # ← NUEVO: hora del scheduler persistida
│
├── models/                      # campaigns, wordpress_sites, posts,
│                                # optimized_posts, executions, execution_logs,
│                                # schedule_config
├── schemas/
├── utils/
│   ├── image_resolver.py        # ← NUEVO: unifica Drive + prompt OpenAI
│   ├── file_downloader.py       # heredado (ambas ramas)
│   ├── massive_uploader.py      # heredado de main, con validación
│   └── links.py                 # ← NUEVO: construcción de enlaces internos
└── scripts/
    └── wordpress_preflight.py   # heredado de post-orquestador
```

---

## 5. Modelo de datos

La base de datos vuelve a ser **propia del bot** (no la compartida del SEO
Agent), con Alembic **activo** y sin el bloqueo `ALLOW_LEGACY_ALEMBIC`.

### 5.1 `campaigns` — se le quitan las credenciales

```sql
CREATE TABLE campaigns (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    slug        VARCHAR(100),
    url         VARCHAR(255) NOT NULL,
    domain      VARCHAR(255),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP
);
-- ELIMINADAS: email, password  (migran a wordpress_sites)
```

### 5.2 `wordpress_sites` — NUEVA, adaptada de la del SEO Agent

```sql
CREATE TABLE wordpress_sites (
    id              SERIAL PRIMARY KEY,
    campaign_id     INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    wp_base_url     VARCHAR(255) NOT NULL,
    wp_api_base_url VARCHAR(255),
    auth_type       VARCHAR(50)  NOT NULL DEFAULT 'application_password',
    username        VARCHAR(255) NOT NULL,
    credential_ref  VARCHAR(255) NOT NULL,   -- nombre de la variable en .env
    rest_namespace  VARCHAR(50)  NOT NULL DEFAULT 'wp/v2',
    yoast_enabled   BOOLEAN      NOT NULL DEFAULT TRUE,
    active          BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP
);
CREATE UNIQUE INDEX ux_wordpress_sites_active_campaign
    ON wordpress_sites (campaign_id) WHERE active;
```

> El índice único parcial resuelve de raíz la ambigüedad que en
> `post-orquestador` se tapaba con un `warning` ("varios sitios activos, uso el
> id más bajo"): **una campaña activa tiene como mucho un sitio activo**.

### 5.3 `posts` — estado explícito en vez de booleano

Se conservan todas las columnas de `main` y se añaden:

```sql
ALTER TABLE posts
    ADD COLUMN state        VARCHAR(20) NOT NULL DEFAULT 'pending',
        -- pending | claimed | running | done | failed
    ADD COLUMN attempts     INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN last_error   TEXT,
    ADD COLUMN claimed_at   TIMESTAMP,
    ADD COLUMN published_at TIMESTAMP,
    ADD COLUMN wp_post_id   INTEGER,
    ADD COLUMN wp_post_url  TEXT,
    ADD COLUMN image_prompt TEXT,     -- alternativa al enlace de Drive
    ADD COLUMN source       VARCHAR(20) NOT NULL DEFAULT 'excel';
        -- excel | api | orchestrator
CREATE INDEX ix_posts_pending ON posts (state, date);
```

> **Por qué se sustituye `status BOOLEAN`:** con un booleano no se distingue
> "aún no procesado" de "falló y se quedó ahí". En `main`, un post que fallaba
> quedaba con `status = False` y **no volvía a intentarse nunca** (el filtro
> solo mira la fecha de hoy), sin que nadie se enterara.
>
> `state` + `attempts` + `last_error` **no cambian ese comportamiento** — el
> post sigue sin reintentarse solo (§10.4) — pero lo hacen visible en la cola y
> permiten relanzarlo a mano.

### 5.4 `optimized_posts` — se añade la identidad del post remoto y el snapshot

Mismas columnas nuevas que `posts`, más:

```sql
ALTER TABLE optimized_posts
    ADD COLUMN wp_post_id        INTEGER,
    ADD COLUMN wp_route          VARCHAR(20),   -- 'posts' | 'pages'
    ADD COLUMN previous_title    TEXT,
    ADD COLUMN previous_content  TEXT,
    ADD COLUMN previous_meta     JSONB,
    ADD COLUMN previous_slug     TEXT,
    ADD COLUMN optimized_at      TIMESTAMP;
```

El *snapshot* (`previous_*`) se escribe **antes** de tocar WordPress. Es la red
de seguridad del flujo de optimización, que por definición no puede usar el
truco de "crear borrador y publicar al final".

`previous_meta` guarda el bloque `meta` completo tal como lo devolvió
`GET {route}/{id}?context=edit`, **incluido `_elementor_edit_mode`**. El
rollback (`POST /api/optimized/{id}/rollback`) reenvía título, contenido, slug y
ese mismo bloque de metas en una sola petición, de modo que un post que estaba
en modo `builder` **vuelve a renderizarse con Elementor**: su `_elementor_data`
nunca se tocó, así que basta con devolver el meta a `builder`.

> Sin ese detalle el rollback dejaría el post con el contenido antiguo pero ya
> fuera de Elementor, que no es el estado original.

### 5.5 `executions` y `execution_logs` — NUEVAS

Sustituyen al `ExecutionTracker` en memoria de `post-orquestador`, que se perdía
al reiniciar y no servía con varios canales.

```sql
CREATE TABLE executions (
    id             UUID PRIMARY KEY,
    source         VARCHAR(20) NOT NULL,  -- scheduler | api | orchestrator
    kind           VARCHAR(20) NOT NULL,  -- create | optimize
    campaign_id    INTEGER REFERENCES campaigns(id),
    post_id        INTEGER,               -- posts.id u optimized_posts.id
    external_id    VARCHAR(100),          -- execution_id del orquestador
    status         VARCHAR(20) NOT NULL,  -- queued|running|completed|failed
    title          TEXT,
    result         JSONB,
    error          TEXT,
    created_at     TIMESTAMP NOT NULL DEFAULT now(),
    started_at     TIMESTAMP,
    completed_at   TIMESTAMP
);

CREATE TABLE execution_logs (
    id           BIGSERIAL PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    ts           TIMESTAMP NOT NULL DEFAULT now(),
    level        VARCHAR(10) NOT NULL,
    message      TEXT NOT NULL
);
CREATE INDEX ix_execution_logs_exec ON execution_logs (execution_id, id);
```

Se conserva el mecanismo de `ContextVar` + handler de `logging` de
`post-orquestador` (que es lo que permite ver el progreso en vivo), pero
escribiendo en estas tablas con *buffer* en memoria y volcado periódico para no
hacer un `INSERT` por línea de log.

### 5.6 `schedule_config` — NUEVA

```sql
CREATE TABLE schedule_config (
    id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    hour        VARCHAR(5) NOT NULL DEFAULT '02:00',
    timezone    VARCHAR(50) NOT NULL DEFAULT 'America/Bogota',
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMP NOT NULL DEFAULT now()
);
```

> Resuelve el bug de `main`: la hora vivía en una variable global de
> [app/utils/time.py](../app/utils/time.py) y volvía a `02:00` en cada reinicio.
> Se añade **zona horaria explícita**, que en `main` no existía.

---

## 6. El núcleo de publicación

### 6.1 Contratos

```python
@dataclass(frozen=True)
class PublishRequest:
    campaign_id: int
    title: str
    seo_title: str
    slug: str
    content: str            # HTML final, ya generado
    meta_description: str
    keyphrase: str
    categories: str
    hashtags: str
    image_path: str | None  # ya resuelta en disco
    image_alt: str
    create_category: bool = False

@dataclass(frozen=True)
class OptimizeRequest(PublishRequest):
    target: str             # edition_url o wp_post_id
    keep_featured_image: bool = False
    keep_slug: bool = True  # cambiar el slug de un post vivo rompe SEO

@dataclass(frozen=True)
class PublishResult:
    success: bool
    wp_post_id: int | None
    wp_post_url: str | None
    media_id: int | None
    error: str | None
```

### 6.2 `PublishingService.publish()` — crear un post

Es el flujo de `post-orquestador` tal cual, sin cambios:

1. `GET users/me?context=edit` → valida credenciales.
2. `OPTIONS posts` → verifica que las metas de Yoast sean escribibles (si aplica).
3. Resuelve categorías (crea solo si `create_category`) y etiquetas (siempre crea).
4. Sube la imagen a `media` + segundo `POST media/{id}` para alt/título y vaciar
   caption y descripción.
5. Añade la `<figure>` al final del contenido.
6. `POST posts` con `status: "draft"`.
7. `POST posts/{id}` con las metas de Yoast.
8. `POST posts/{id}` con `status: "publish"`.

> **Optimización opcional (fase 2):** los pasos 6–7 se pueden fusionar enviando
> `meta` en el mismo `POST posts` de creación. Reduce una llamada, pero se deja
> para después de estabilizar, porque el paso separado es el que hoy está probado.

### 6.3 `PublishingService.optimize()` — reescribir un post existente

Esta es **la parte nueva**: el equivalente REST de lo que `main` hacía tecleando
en el editor. La diferencia de fondo es que **no se puede usar el truco del
borrador**: pasar un post publicado a `draft` lo sacaría de línea mientras se
trabaja. La estrategia es la contraria: **preparar todo primero y escribir una
sola vez.**

```
 1. Resolver el post remoto            → PostRef(route, id)
 2. GET {route}/{id}?context=edit      → estado actual + _elementor_edit_mode
 3. Guardar snapshot en la BD          → previous_title/content/meta/slug
 4. Resolver categorías y etiquetas    → ids
 5. Subir la imagen nueva (si la hay)  → media_id
 6. UNA sola escritura:
    POST {route}/{id} {
        title, content, categories, tags,
        featured_media,                      (si hay imagen nueva)
        slug,                                (solo si keep_slug = False)
        meta: { _yoast_wpseo_title,
                _yoast_wpseo_metadesc,
                _yoast_wpseo_focuskw,
                _elementor_edit_mode: "" }   (solo si venía en "builder" — §6.5)
    }
    ── sin tocar "status": el post sigue publicado todo el tiempo ──
 7. Verificar la respuesta y guardar wp_post_id / optimized_at
```

Los pasos 1–5 son solo lectura y preparación: si cualquiera falla, **el post
remoto no se ha tocado**. El paso 6 es una única petición, así que o se aplica
entera o no se aplica.

### 6.4 Resolver el post remoto desde `edition_url`

En `main` el `edition_url` se abría en el navegador y listo. Por REST hace falta
un **id**. Cadena de resolución, en orden, en `WordPressClient.resolve_post_ref()`:

| # | Entrada | Método |
|---|---|---|
| 1 | `123` (numérico) | Se usa directamente como `posts/123` |
| 2 | `.../wp-admin/post.php?post=123&action=edit` | Se lee el parámetro `post` |
| 3 | `https://sitio.com/?p=123` | Se lee el parámetro `p` |
| 4 | URL pública | `GET` a la URL y se lee la cabecera `Link: <.../wp-json/wp/v2/posts/123>; rel="alternate"; type="application/json"` — petición **sin autenticación**, con `allow_redirects=True` (los permalinks redirigen a menudo) y su propio timeout. Si el sitio no devuelve esa cabecera se pasa al método 5 |
| 5 | URL pública | Se extrae el slug del *path* → `GET posts?slug=<slug>&status=any&context=edit` |
| 6 | — | Error explícito: `No se pudo resolver el post de <url>` |

El método 4 es el preferido para URLs públicas porque **también indica la ruta
correcta** (`posts` vs `pages`), algo que el método 5 no distingue. Por eso el
resolutor devuelve un `PostRef(route, id)` y no un entero suelto:

```python
@dataclass(frozen=True)
class PostRef:
    route: str  # "posts" | "pages"
    id: int
```

El resultado se **cachea** en `optimized_posts.wp_post_id` / `wp_route`, de modo
que una segunda optimización del mismo post se salta la resolución.

### 6.5 Elementor: el paso extra del editor, resuelto con un meta

En `main`, el flujo de optimización empieza con este bloque:

```python
page.wait_for_selector('//span[@class="elementor-switch-mode-on"]')
page.click("//button[@id='elementor-switch-mode-button']")     # "Volver al editor de WordPress"
page.click('//div[contains(@class,"dialog-buttons-wrapper")]//button[2]')  # confirmar
```

Es decir: cuando el post está construido con Elementor, `main` **lo devuelve al
editor clásico** y a partir de ahí escribe el HTML en `#content` como en
cualquier otro post. No conserva la maquetación de Elementor — la deja de lado
a propósito, porque el objetivo es sustituir el contenido entero.

**Eso se hace por API directamente.** Elementor decide si "secuestra" el
renderizado con un único meta:

```php
// Elementor\Frontend::apply_builder_in_content()
get_post_meta($post_id, '_elementor_edit_mode', true) === 'builder'
```

Si ese meta deja de valer `builder`, WordPress vuelve a pintar `post_content`,
que es exactamente lo que consigue el botón. Así que el equivalente REST es
**un campo más en la misma petición**, sin llamada extra:

```python
payload = {
    "title": ..., "content": ..., "categories": [...], "tags": [...],
    "featured_media": media_id,
    "meta": {
        "_yoast_wpseo_title":    seo_title,
        "_yoast_wpseo_metadesc": meta_description,
        "_yoast_wpseo_focuskw":  keyphrase,
        "_elementor_edit_mode":  "",   # ← equivale al botón + confirmación
    },
}
```

Detalles que importan:

- **`_elementor_data` no se toca.** Guarda la maquetación y se queda como estaba,
  igual que al pulsar el botón en la interfaz: el post deja de renderizarse con
  Elementor, pero el diseño sigue almacenado y se puede recuperar volviendo a
  poner el meta en `builder`. Esto es además lo que hace el rollback (§5.4)
  reversible de verdad.
- **Solo se envía si hacía falta.** En el paso 2 se lee el meta; si no vale
  `builder`, no se incluye en el payload. Igual que `main`, que si no encontraba
  el botón dejaba un `warning` y seguía.
- **Sigue siendo una sola escritura.** El reset del meta viaja en el mismo
  `POST`, así que la propiedad de §6.3 (o se aplica todo o no se aplica nada) se
  mantiene.
- **El MU-plugin debe registrar `_elementor_edit_mode` como escribible**, no solo
  legible (§9).

### 6.5.1 Divi y WPBakery no tienen este problema

Ambos guardan su contenido como **shortcodes dentro de `post_content`**, no en
meta aparte. Al sobrescribir `content` por REST pasa lo mismo que pasaba al
sobrescribir el `textarea` en `main`: el contenido nuevo reemplaza al anterior.
No requieren tratamiento especial, igual que en `main`, que tampoco lo tenía.

### 6.6 Composición del contenido final — el orden importa

En `main` el contenido **no se escribía de una sola vez**. Se tecleaba el cuerpo
en el `textarea`, y luego se añadían más bloques *después*, en este orden exacto
(idéntico en el flujo de creación y en el de optimización):

```
1. contenido        ← intro + cuerpo + conclusión (lo que devuelve NewPostContent)
2. enlace externo   ← page.keyboard.type(external_link)
3. imagen           ← insertada desde el modal de medios, tamaño "full"
4. enlaces de ciudad← page.keyboard.type(city_links)
```

⚠️ **Esto choca con el núcleo heredado de `post-orquestador`.** Su
`append_media_to_content()` añade la `<figure>` **al final del contenido**. Si se
reutiliza tal cual, el post quedaría con los enlaces de ciudad *antes* de la
imagen — orden distinto al de todos los posts históricos.

Solución: un `ContentAssembler` explícito en `core/content_assembler.py`, y
`append_media_to_content()` deja de usarse en este flujo.

```python
def assemble(body: str, *, external_link: str, media: dict | None,
             alt_text: str, city_links: str) -> str:
    """Compone el HTML final en el mismo orden que producía el editor clásico."""
    blocks = [body.rstrip()]
    if external_link:
        blocks.append(f"<p>{external_link}</p>")
    if media:
        blocks.append(figure_html(media, alt_text))   # wp-block-image size-full
    if city_links:
        blocks.append(f"<p>{city_links}</p>")
    return "\n\n".join(blocks)
```

Por tanto `PublishRequest.content` **no** es "lo que devuelve la generación":
es la salida del `ContentAssembler`. El `PublishingService` recibe el HTML ya
compuesto y no vuelve a tocarlo.

> Verificar en staging comparando un post nuevo contra uno histórico del mismo
> sitio antes de cerrar la fase F2.

### 6.7 Categorías: se replica la semántica de `main`

Aquí `main` y `post-orquestador` no coinciden, y **manda `main`**.

**a) El separador.** `main` **no separa por comas**:

```python
categories = post.categories if isinstance(post.categories, list) else [post.categories]
```

`post.categories` siempre viene del Excel como texto, así que `"Amarres, Limpias"`
se busca como **una sola** categoría llamada literalmente `"Amarres, Limpias"`.

**b) Si la categoría no existe**, el `except` deja un `logger.warning` y **el
post se publica igual**, sin esa categoría.

Implementación en v3 — `resolve_categories_lenient()`:

```python
def resolve_categories_lenient(self, raw: str) -> list[int]:
    """Replica la resolución de categorías de main sobre REST:
    el valor se trata como UN nombre, y si no existe se avisa y se sigue."""
    ids: list[int] = []
    for name in [raw.strip()] if raw and raw.strip() else []:
        term_id = self.resolve_term("categories", name, create=False)
        if term_id is None:
            logger.warning("No se pudo seleccionar la categoría %r", name)
            continue          # ← no aborta: igual que el except de main
        ids.append(term_id)
    return ids
```

> **No se usa** `resolve_categories()` de `post-orquestador` en el flujo local:
> ese método **aborta** la publicación si la categoría no existe y
> `create_category` es `false`. Ese comportamiento se mantiene **solo** para el
> canal del orquestador, donde `create_category` sí llega en el payload y es
> el comportamiento que ese canal ya tenía.
>
> Si en el futuro se quiere separar por comas, es cambiar la lista de la línea 4
> por `split_names(raw)`. Es una decisión de producto, no de esta migración.

### 6.8 Equivalencias Playwright → REST

Tabla de referencia para la migración, paso por paso:

| Acción en `main` (Playwright) | Equivalente v3 (REST) |
|---|---|
| `page.goto('/wp-admin/')` + `#user_login` / `#user_pass` / `#wp-submit` | `HTTPBasicAuth(username, application_password)` + `GET users/me` |
| `page.fill('#title', ...)` | campo `title` del `POST posts` |
| `#content-html` + `textarea#content` | campo `content` |
| `page.keyboard.type(external_link)` tras el contenido | bloque `<p>` que añade el `ContentAssembler` (§6.6) |
| `page.keyboard.type(city_links)` al final | bloque `<p>` que añade el `ContentAssembler` (§6.6) |
| `#insert-media-button` → `#menu-item-upload` → `set_input_files` | `POST media` con `Content-Disposition` |
| `#attachment-details-alt-text` + limpiar caption | `POST media/{id}` con `alt_text`, `caption: ""`, `description: ""` |
| Selector de tamaño "full" + "Insertar en la entrada" | `<figure class="wp-block-image size-full">` añadida al contenido |
| `#set-post-thumbnail` + 7 Tabs + buscar por nombre de archivo | campo `featured_media` con el `media_id` |
| Marcar checkboxes en `#categorychecklist` | `GET/POST categories` → array `categories` |
| Teclear en `#new-tag-post_tag` + Enter | `GET/POST tags` → array `tags` |
| `#focus-keyword-input-metabox` (se tecleaba **`post.title`**) | meta `_yoast_wpseo_focuskw` — ver §7.1 |
| Desmarcar todas las categorías / borrar todos los tags antes de reasignar (solo optimización) | los arrays `categories` y `tags` del `POST` **reemplazan** los anteriores; no hay que borrar nada aparte |
| Editor Draft.js del título SEO de Yoast | meta `_yoast_wpseo_title` |
| Slug de Yoast + 3 Tabs hasta la meta descripción | campos `slug` y meta `_yoast_wpseo_metadesc` |
| `#publish` | `POST posts/{id}` con `status: "publish"` |
| Botón "Volver al editor de WordPress" + confirmación (Elementor) | meta `_elementor_edit_mode: ""` en la misma petición (§6.5) |
| Captura de pantalla en `errors/` | `executions.error` + `execution_logs` |
| `show_alert('Automation completed')` | — (se elimina) |

---

## 7. Generación de contenido

Se porta [app/controllers/content_controller.py](../app/controllers/content_controller.py)
de `main` **con los prompts intactos**. Cambios técnicos, no editoriales:

1. **Cliente por instancia.** Sustituir `openai.api_key = api_key` (estado
   global del módulo) por `self.client = OpenAI(api_key=...)`. Con varios hilos
   publicando en paralelo, el estado global es una condición de carrera.
2. **Modelos configurables.** `OPENAI_CONTENT_MODEL` (hoy `gpt-4` fijo en 12
   sitios) y `OPENAI_META_MODEL` (hoy `gpt-4o`). Permite mover el modelo sin
   tocar código.
3. **Idioma no soportado deja de romper.** Hoy, si `language` no es `es` ni `en`,
   se imprime "Language not supported" y `content` **queda sin asignar** →
   `UnboundLocalError` varias líneas más abajo. En v3 debe lanzarse
   `UnsupportedLanguageError` de inmediato y marcar el post como `failed` con
   mensaje claro.
4. **Reintentos.** Envolver las llamadas a OpenAI con reintento exponencial ante
   429 y 5xx. Una generación de post encadena hasta 6 llamadas; sin reintento,
   un 429 puntual tira el post entero.
5. **Tiempos.** La generación tarda minutos. Debe ejecutarse siempre en el
   *worker pool*, nunca en el hilo de la petición HTTP ni en el loop asíncrono.

### 7.1 Campos que el Excel no trae y `main` derivaba implícitamente

Dos campos del `PublishRequest` **no existen como columna del Excel**. En `main`
su valor salía de otro sitio, y v3 tiene que reproducirlo o el resultado cambia:

| Campo | De dónde salía en `main` | Valor en v3 (flujo Excel) |
|---|---|---|
| `keyphrase` | Se tecleaba **`post.title`** en el metabox de Yoast, tanto al crear como al optimizar. No hay columna de keyphrase | **`post.title`** — idéntico |
| `image_alt` | `Path(image_path).stem`: el **nombre del archivo** ya saneado, es decir el título en minúsculas y con guiones | **`Path(image_path).stem`** — idéntico |

Es decir, el texto alternativo sigue siendo `amarres-de-amor-efectivos` y no
`Amarres de amor efectivos`. Se replica tal cual:

```python
image_alt = Path(image_path).stem   # mismo valor que producía main
```

> Se evaluó usar el título legible (mejor para accesibilidad y SEO), pero queda
> **fuera del alcance de esta migración**: el objetivo es cambiar el transporte,
> no el contenido publicado. Es una mejora candidata para después, y entonces
> habría que decidir si se aplica también a los posts históricos.

En el flujo del orquestador estos dos campos sí pueden venir explícitos
(`keyphrase`, `image_alt`), y si vienen, mandan — eso ya era así en
`post-orquestador`.

### 7.2 Enlaces internos

El armado de enlaces internos (emparejar `keywords` con `keywords_urls`, las
conclusiones y el bloque de ciudades) sale del orquestador y se aísla en
`utils/links.py`, **conservando exactamente la semántica de `main`**, que no es
la misma para los tres campos:

```python
def build_links(phrases: str, urls: str, *, strict: bool) -> list[str]:
    """Empareja frases y URLs separadas por comas.

    strict=True  → lanza si las longitudes no coinciden  (ciudades)
    strict=False → zip(), descarta los sobrantes         (keywords, conclusiones)
    """
```

| Campo | `main` | v3 |
|---|---|---|
| `citys` / `citys_urls` | valida longitudes y lanza `RuntimeError` | `strict=True` |
| `keywords` / `keywords_urls` | `zip()`, descarta sobrantes en silencio | `strict=False` |
| `conclusions` / `conclusions_urls` | `zip()`, descarta sobrantes en silencio | `strict=False` |

> El desajuste en keywords y conclusiones **no se convierte en error**: un post
> que hoy sale con un enlace de menos debe seguir saliendo igual. Lo que sí se
> añade es un **aviso en el momento de cargar el Excel** (§11), que no cambia
> lo que se publica, solo avisa antes a quien sube el archivo.

---

## 8. Imagen destacada: las dos fuentes unificadas

`utils/image_resolver.py` decide el origen y devuelve siempre `(resized, original)`:

```python
def resolve_featured_image(post, output_dir, api_key) -> tuple[Path, Path] | None:
    if post.image_prompt:                      # vía post-orquestador
        return generate_image_from_prompt(...)  # OpenAI gpt-image-2
    if post.image and is_url(post.image):      # vía main
        return download_and_resize(...)         # Google Drive → WebP 700x400
    return None                                 # se publica sin imagen
```

Reglas heredadas de `post-orquestador`, que son las correctas:

- Si no hay imagen, **se publica igual**.
- Si la generación o descarga falla, se registra el error y **la publicación
  continúa sin imagen**. La imagen nunca bloquea el post.
- Los dos archivos se borran siempre al terminar (`finally`).

En el flujo de **optimización**, además: si `keep_featured_image = True` no se
sube nada y no se toca `featured_media`.

---

## 9. MU-plugin de WordPress: ampliación necesaria

El actual
[wordpress-plugin/post-bot-rest-fields.php](../wordpress-plugin/post-bot-rest-fields.php)
expone las tres metas de Yoast para el *post type* `post`. Para v3 hay que
ampliarlo:

1. **Registrar también para `page`**, porque el resolutor puede devolver
   `route = "pages"` al optimizar.
2. **Registrar `_elementor_edit_mode` en lectura y escritura**, que es lo que
   permite reproducir el botón *"Volver al editor de WordPress"* (§6.5):

   ```php
   register_post_meta($post_type, '_elementor_edit_mode', [
       'type'              => 'string',
       'single'            => true,
       'default'           => '',
       'sanitize_callback' => 'sanitize_text_field',
       'show_in_rest'      => ['schema' => ['type' => 'string',
                                            'context' => ['view', 'edit']]],
       'auth_callback'     => static fn(bool $a, string $k, int $id): bool
                                  => current_user_can('edit_post', $id),
   ]);
   ```

   **`_elementor_data` no se registra.** No hace falta tocarlo y dejarlo fuera
   del alcance del bot evita que un error pueda destruir una maquetación.
3. Mantener `auth_callback` con `current_user_can('edit_post', $post_id)` tal
   como está: la comprobación de capacidades de WordPress no se toca.
4. `ensure_yoast_meta_writable()` pasa a comprobar también
   `_elementor_edit_mode` cuando el post a optimizar viene en modo `builder`:
   si no es escribible, se falla **antes** de tocar nada, con un mensaje que
   pide actualizar el MU-plugin.

   Además debe consultar **la ruta correcta**: hoy hace `OPTIONS posts` fijo.
   Al optimizar una página hay que pedir `OPTIONS pages`, porque el esquema es
   independiente por *post type* y el MU-plugin podría estar registrado para
   uno y no para el otro:

   ```python
   def ensure_meta_writable(self, route: str, keys: set[str]) -> None:
       options = self._request("OPTIONS", route)   # "posts" o "pages"
   ```

Versionar el plugin (`Version: 2.0.0`) y que el **preflight verifique la versión**
antes de permitir optimizaciones, para no descubrir en producción que un sitio
sigue con la versión vieja.

---

## 10. Canal 1 — Scheduler diario

`channels/scheduler.py`.

Se conserva el comportamiento de `main` (dos trabajos diarios a la misma hora:
crear y optimizar) y se corrigen los defectos que impedian que ese
comportamiento se cumpliera de verdad:

### 10.1 El filtro de "los posts de hoy" está roto

```python
# main — app/services/post.py
today = datetime.now().date()
posts = self.db.query(Post).filter(Post.date == today).all()
```

`Post.date` es un `DateTime`. Comparar una columna `DateTime` con un `date`
genera `date = '2026-09-22'`, que en PostgreSQL solo casa con
`2026-09-22 00:00:00` exacto.

Efecto real, que conviene entender bien antes de tocarlo:

- Excel **con** columna `date` → `pd.to_datetime()` de una celda de fecha da
  medianoche → **sí casa**. Este es el caso que funciona hoy.
- Excel **sin** columna `date` → el uploader pone `datetime.now()` → **no casa
  nunca**. Esos posts quedan invisibles para siempre.

v3 aplica la **corrección mínima**: comparar por día, no por instante.

```python
def claim_due_posts(self, batch_size: int) -> list[int]:
    """Reclama atómicamente los posts del día y los marca como 'claimed'."""
    sql = text("""
        UPDATE posts SET state = 'claimed',
                         claimed_at = now(),
                         attempts = attempts + 1
        WHERE id IN (
            SELECT id FROM posts
            WHERE state = 'pending'
              AND date::date = CURRENT_DATE     -- mismo criterio que main, bien escrito
            ORDER BY date, id
            FOR UPDATE SKIP LOCKED
            LIMIT :batch_size
        )
        RETURNING id
    """)
```

> **Deliberadamente NO se usa `date <= now()`.** Sería lo "lógico" (procesar
> atrasados), pero en la primera ejecución publicaría de golpe todos los posts
> históricos que nunca llegaron a salir por este bug. El criterio se mantiene en
> "los de hoy", igual que `main`.
>
> Si se quiere recuperar ese atraso, es una operación aparte y manual: revisar
> qué posts son y reprogramarles la fecha.

### 10.2 Reclamo atómico contra la doble publicación

`FOR UPDATE SKIP LOCKED` + `state = 'claimed'` en la misma sentencia garantiza
que, aunque haya dos instancias del bot corriendo (o el scheduler solape con un
disparo manual), **ningún post se publica dos veces**. En `main` no había nada
que lo impidiera: el `status` se ponía a `True` *después* de publicar.

### 10.3 Hora persistida y con zona horaria

`reset_schedule()` lee `schedule_config` de la base de datos. El endpoint que
cambia la hora escribe en la tabla y reprograma.

**Hay que cambiar de librería.** `schedule` (la de `main`) **no soporta zonas
horarias**: `schedule.every().day.at("02:00")` usa la hora local del proceso.
En contenedor eso es UTC, así que la ejecución se correría de hora respecto a lo
que el equipo espera. Se sustituye por **APScheduler**, que sí la admite:

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

hour, minute = config.hour.split(":")
scheduler.add_job(
    run_daily_batch,
    CronTrigger(hour=int(hour), minute=int(minute), timezone=config.timezone),
    id="daily_batch",
    replace_existing=True,      # reprogramar = volver a llamar con el mismo id
    misfire_grace_time=3600,    # si el proceso estaba caído, se ejecuta al volver
)
```

Sustituye a `BackgroundScheduler` el hilo daemon + `while True: sleep(60)` de
`main`. La dependencia `schedule` se elimina del `pyproject.toml`.

> ⚠️ **`CURRENT_DATE` en el claim va en la zona del servidor de PostgreSQL**, no
> en la de `schedule_config`. Si no coinciden, un lote lanzado a las 02:00 hora
> local puede acabar preguntando por el día equivocado. Dos opciones, hay que
> elegir una y dejarla escrita:
>
> - Fijar la zona de la sesión: `SET TIME ZONE '<tz>'` al abrirla, o
> - Filtrar explícito: `date::date = (now() AT TIME ZONE :tz)::date`.
>
> La segunda es preferible: no depende de la configuración del servidor de base
> de datos.

### 10.4 Reintentos: el mismo comportamiento que `main`, ahora visible

En `main`, un post que fallaba se quedaba con `status = False`. Como el filtro
solo mira la fecha de hoy y el job corre una vez al día, **ese post no se
reintentaba nunca más**: quedaba muerto y en silencio.

v3 **no cambia eso**, solo lo hace visible: el post pasa a `state = 'failed'`
con `last_error` y `attempts`, y aparece en la cola de la interfaz como
fallido. Sigue sin reintentarse solo.

Para reintentarlo hay dos vías explícitas, ambas a petición de una persona:

- `POST /api/posts/{id}/run` — lo ejecuta ahora.
- Volver a poner `state = 'pending'` y ajustar la fecha.

> No se añade reintento automático. Sería un cambio de comportamiento, y con
> generación de contenido de por medio cada reintento cuesta dinero en OpenAI.

---

## 11. Canal 2 — API HTTP

`router.py`, prefijo `/api`.

| Endpoint | Método | Origen | Descripción |
|---|---|---|---|
| `/api/campaigns` | GET | nuevo | Campañas activas con su sitio y `credential_configured` |
| `/api/schedule` | GET/PUT | `main` | Consulta/actualiza hora, zona y `enabled` |
| `/api/posts/upload/new` | POST | `main` | Carga masiva `.xlsx` de posts a crear |
| `/api/posts/upload/optimized` | POST | `main` | Carga masiva `.xlsx` de posts a optimizar |
| `/api/posts/{id}/run` | POST | nuevo | Fuerza ahora un post concreto de la BD |
| `/api/optimized/{id}/run` | POST | nuevo | Fuerza ahora una optimización concreta |
| `/api/optimized/{id}/rollback` | POST | nuevo | Restaura el snapshot `previous_*` |
| `/api/post/create` | POST | `post-orq.` | Publicación directa (payload completo) |
| `/api/executions` | GET | nuevo | Lista ejecuciones, filtrable por canal y estado |
| `/api/executions/{id}` | GET | `post-orq.` | Estado + log en vivo |

Se conserva la interfaz web de `post-orquestador` (`app/static/`) y se le añaden
dos vistas: **cola de posts programados** y **historial de ejecuciones**.

### Carga masiva: validación previa

El `massive_uploader` de `main` acumula errores por fila y sigue. Se conserva,
pero se añade:

- **Validación de columnas** antes de procesar: si el Excel no trae las columnas
  esperadas, se rechaza el archivo entero con la lista de las que faltan, en vez
  de generar una fila de error por cada línea.
- **Verificación de `id_campaign`**: que exista, esté activa y tenga sitio
  WordPress activo. Es preferible fallar en la carga que a las 02:00 de la
  madrugada.
- **Aviso de enlaces desparejados**: contar frases y URLs de cada par y
  **avisar** (no rechazar) si no coinciden. La fila se acepta igual y se
  publicará como en `main`; el aviso solo adelanta la información a quien sube
  el archivo. Para `citys`/`citys_urls` sí es rechazo, porque `main` también
  falla en ese caso.

---

## 12. Canal 3 — Orquestador, independiente

`channels/orchestrator.py`. Reutiliza
[app/clients/websocket_client.py](../app/clients/websocket_client.py) sin cambios.

El requisito es que este canal sea **independiente del flujo de páginas
original**. Se materializa en cinco separaciones concretas:

| Separación | Implementación |
|---|---|
| **Identidad propia** | `bot_key = "post-bot-v3-<hostname>"`, distinto del bot de la rama anterior, para que ambos puedan coexistir durante la transición |
| **Capacidades propias** | `capabilities = ["posts.create", "posts.optimize"]` — el orquestador puede pedir **ambas** cosas |
| **Concurrencia propia** | `ThreadPoolExecutor` dedicado, con `ORCHESTRATOR_MAX_CONCURRENCY`. Una carga de 200 posts desde Excel **no** consume los slots del orquestador, y viceversa |
| **Estado propio** | Los trabajos del orquestador **no escriben en `posts` ni en `optimized_posts`**. Viven solo en `executions` con `source = 'orchestrator'` y `external_id = execution_id`. No tienen `state`, ni `attempts`, ni entran en el barrido del scheduler |
| **Ciclo de vida propio** | `ORCHESTRATOR_ENABLED` y `SCHEDULER_ENABLED` son flags separados. El servicio arranca y funciona con cualquiera de los dos apagado |

### 12.1 Flujo de un `execution.run`

Se hereda de `post-orquestador` (§4 de su documento): carga el input desde
`input_url` o `payload`, extrae los posts de forma tolerante, resuelve la
campaña por id / nombre / URL, normaliza los alias de campos y publica uno por
uno, devolviendo `partial_posts` si el lote falla a la mitad.

**Novedad de v3:** se despacha según `capability`:

```python
CAPABILITY_HANDLERS = {
    "posts.create":   _handle_create,    # → PublishingService.publish()
    "posts.optimize": _handle_optimize,  # → PublishingService.optimize()
}
```

Para `posts.optimize`, el payload debe traer un destino: `edition_url`,
`post_url` o `wp_post_id`. Se aplican los mismos alias tolerantes que en el
resto del normalizador.

### 12.2 Reentrada y duplicados

Se conserva la deduplicación por `execution_id` en memoria del cliente
WebSocket, y se refuerza con una **restricción única en base de datos**:

```sql
CREATE UNIQUE INDEX ux_executions_external
    ON executions (external_id) WHERE external_id IS NOT NULL;
```

Si el orquestador reenvía un `execution_id` ya completado tras una reconexión,
el bot devuelve el resultado guardado en vez de volver a publicar.

---

## 13. Concurrencia

```python
# core/worker_pool.py
local_pool        = ThreadPoolExecutor(max_workers=LOCAL_MAX_CONCURRENCY)         # scheduler + API
orchestrator_pool = ThreadPoolExecutor(max_workers=ORCHESTRATOR_MAX_CONCURRENCY)  # WebSocket
```

Reglas:

- **Una sesión de SQLAlchemy por tarea**, creada y cerrada dentro del worker.
  Nunca compartir sesión entre hilos.
- **Un `WordPressClient` por tarea** (es un context manager con su propia
  `requests.Session`).
- Los `available_slots` que el bot reporta en el `bot.heartbeat` salen **solo**
  del `orchestrator_pool`. Lo que haga el scheduler no altera lo que el
  orquestador cree que hay disponible.
- Límite de concurrencia **por sitio WordPress** (semáforo por `site_id`,
  por defecto 1) para no disparar los rate limits del hosting ni crear dos
  categorías iguales a la vez.

---

## 14. Configuración

```env
DEBUG=false

# Base de datos propia
DB_HOST=... 
DB_PORT=5432
DB_NAME=blog_post_bot
DB_USER=...
DB_PASSWORD=...

# Canal scheduler
SCHEDULER_ENABLED=true
SCHEDULER_BATCH_SIZE=20
SCHEDULER_TIMEZONE=America/Bogota   # semilla de schedule_config; manda la BD

# Canal orquestador (independiente del anterior)
ORCHESTRATOR_ENABLED=true
WEBSOCKET=ws://10.0.0.92:8001/api/v1/bots/ws
HTTP_TIMEOUT=30
ORCHESTRATOR_MAX_CONCURRENCY=2

# Concurrencia local
LOCAL_MAX_CONCURRENCY=3
SITE_MAX_CONCURRENCY=1

# OpenAI
OPENAI_API_KEY=...
OPENAI_CONTENT_MODEL=gpt-4
OPENAI_META_MODEL=gpt-4o
OPENAI_IMAGE_MODEL=gpt-image-2

# WordPress
WORDPRESS_HTTP_TIMEOUT=45

# Una variable por sitio — el nombre coincide con wordpress_sites.credential_ref
EXAMPLE_SITE_WP_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

**Alembic vuelve a estar activo.** Se elimina el bloqueo
`ALLOW_LEGACY_ALEMBIC` de [alembic/env.py](../alembic/env.py), que existía
únicamente porque `post-orquestador` apuntaba a la base compartida del SEO
Agent. Con base propia, las migraciones son el mecanismo normal.

---

## 15. Plan de implementación por fases

Cada fase debe quedar desplegable y verificable por sí sola.

| Fase | Alcance | Criterio de aceptación |
|---|---|---|
| **F0 — Base** | Esquema propio: `campaigns` sin credenciales, `wordpress_sites`, `executions`, `schedule_config`. Migración de datos desde la BD de `main`: `campaigns.email` → `wordpress_sites.username`, y una Application Password nueva en `.env` por cada sitio | `python -m app.scripts.wordpress_preflight --campaign <id>` pasa para **todas** las campañas activas |
| **F1 — Núcleo de creación** | Portar `WordPressClient` y `PublishingService.publish()` desde `post-orquestador` sobre el nuevo `WordPressSiteService` (ORM, BD propia) | Un post creado por `POST /api/post/create` sale idéntico al de `post-orquestador` |
| **F2 — Contenido** | Portar `NewPostContent` con las correcciones de §7. `utils/links.py`. `image_resolver` unificado | Un post generado desde un registro de `posts` (título + keywords + Drive) queda publicado y es indistinguible del que producía `main` |
| **F3 — Scheduler y Excel** | `state`/`attempts`, claim atómico, `schedule_config`, uploader con validación previa | Cargar un Excel de 10 filas, esperar a la hora programada y ver 10 posts publicados y 10 filas en `executions`. Arrancar dos instancias y comprobar que no hay duplicados |
| **F4 — Optimización REST** | `resolve_post_ref`, `update_post`, snapshot, rollback, reset de `_elementor_edit_mode`, MU-plugin v2 | Optimizar un post clásico y verificar el resultado. Optimizar uno de Elementor y comprobar que **queda renderizado con el contenido nuevo** y que `_elementor_data` sigue intacto. Probar el rollback en ambos |
| **F5 — Canal orquestador** | `OrchestratorChannel` con pool propio, `posts.create` + `posts.optimize`, dedupe por `external_id` | Con el scheduler saturado, el orquestador sigue recibiendo y completando trabajos. Reenviar un `execution_id` ya hecho no duplica el post |
| **F6 — Operación** | Vistas de cola e historial, Dockerfile/compose/Jenkins heredados de `post-orquestador`, tests | `python -m unittest discover -s tests -v` en verde. Despliegue por Jenkins sin intervención manual |

### Orden de migración de datos (F0)

1. Exportar `campaigns` de la BD de `main`.
2. Por cada campaña, **generar una Application Password** en su WordPress para
   el usuario del bot (`Usuarios → Perfil → Contraseñas de aplicación`).
   No es una medida de seguridad opcional: la REST API de WordPress **no acepta
   la contraseña normal de `wp-admin` por Basic Auth**, así que este paso es un
   requisito técnico del cambio a REST.
3. Insertar la fila en `wordpress_sites` con `username` = el `campaigns.email`
   actual y `credential_ref` apuntando a una variable nueva de `.env`.
4. Ejecutar el preflight por campaña.
5. **Solo entonces**, eliminar `campaigns.email` y `campaigns.password`.
   (La base de datos es interna, así que no hay urgencia con las credenciales
   antiguas; basta con que dejen de usarse.)

---

## 16. Pruebas

Se sigue la convención de `post-orquestador`: `unittest` + `MagicMock`, sin red
ni base de datos real.

```bash
python -m unittest discover -s tests -v
```

| Archivo | Qué cubre |
|---|---|
| `test_wordpress_client.py` | Heredado + **nuevos**: `resolve_post_ref` en sus 5 caminos, `update_post` arma un único payload correcto, `_elementor_edit_mode` se incluye solo si venía en `builder` |
| `test_publishing_service.py` | Crear: orden borrador→publicar. Optimizar: no se envía `status`; si falla la preparación no hay escritura. **`ContentAssembler` compone los bloques en el orden de `main`**; categoría inexistente publica igual |
| `test_scheduler_claim.py` | Claim atómico: dos hilos sobre el mismo lote no se solapan; el filtro de fecha coge los posts de hoy aunque no sean de medianoche, y **no** arrastra los de días anteriores |
| `test_content_controller.py` | Idioma no soportado lanza excepción (no `UnboundLocalError`); `build_links` con `strict=True` falla y con `strict=False` trunca como `zip()` |
| `test_orchestrator_channel.py` | Despacho por `capability`; `partial_posts` al fallar a la mitad; dedupe por `external_id` |
| `test_massive_uploader.py` | Columnas faltantes rechazan el archivo; campaña inválida se reporta en la carga |
| `test_execution_service.py` | Persistencia del log, buffer y volcado |

**Pruebas manuales obligatorias antes de producción** (no se pueden simular):

1. Preflight contra **todos** los sitios activos.
2. Un post creado de punta a punta en un sitio de staging.
3. Una optimización de un post clásico + su rollback.
4. Una optimización sobre un post de Elementor → el post debe renderizar el
   contenido nuevo, y `_elementor_data` debe seguir guardado (comprobar que el
   rollback devuelve el diseño original).
5. Un sitio con `yoast_enabled = true` pero **sin** el MU-plugin → debe fallar
   en el paso 2, **antes** de crear nada.

### La prueba que decide si la migración está bien: equivalencia lado a lado

Todas las comparaciones contra `main` que aparecen dispersas en este documento
se consolidan en **una sola prueba de aceptación**, que es la que responde a
"¿siguen saliendo los posts igual?".

**Procedimiento**, una vez por idioma (`es` y `en`), antes de cerrar F2:

1. Elegir una fila de `posts` real y **duplicarla**.
2. Publicar una con el bot de `main` (última vez que se usa Playwright) y la
   otra con v3, **en el mismo sitio de staging**.
3. Comparar el `post_content` de ambas por REST
   (`GET posts/{id}?context=edit`), no a ojo en la página.

**Qué debe coincidir:**

| | Criterio |
|---|---|
| Orden de bloques | contenido → enlace externo → imagen → enlaces de ciudad |
| Enlaces internos | mismas URLs, mismo `target`/`rel`, mismo número |
| Imagen | misma `<figure class="wp-block-image size-full">`, mismo `alt` |
| Imagen destacada | `featured_media` apunta al medio subido |
| Categorías y etiquetas | mismos ids asignados |
| Yoast | mismos `_yoast_wpseo_title`, `_metadesc`, `_focuskw` |
| Slug | idéntico |

**Qué puede diferir legítimamente:** el texto generado por GPT (cada llamada da
un resultado distinto) y los ids de WordPress. Por eso se compara **estructura**,
no palabras: de la comparación se excluyen los textos de párrafo y se revisan
las etiquetas, los atributos y el orden.

> Esta prueba solo se puede hacer **mientras `main` siga operativo**. Conviene
> ejecutarla y guardar los dos HTML como referencia antes de desmontar nada.

---

## 17. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Posts de Elementor**: olvidar el reset de `_elementor_edit_mode` | La petición devuelve 200 pero la página sigue mostrando el contenido viejo — un fallo silencioso | Se incluye en el mismo payload (§6.5) y hay prueba manual obligatoria (§16). El `auth_callback` del MU-plugin debe permitir escribirlo, si no el meta se descarta sin error |
| **`edition_url` no resoluble** | La optimización no encuentra el post | Cadena de 5 métodos + error explícito + caché en BD. Validar las URLs en la carga del Excel |
| **Cambio de slug en un post vivo** | Se rompe el SEO y los enlaces entrantes | `keep_slug = True` por defecto; cambiarlo exige acción explícita |
| **Orden de los bloques del contenido** distinto al histórico | Posts nuevos con la imagen y los enlaces de ciudad en distinto orden | `ContentAssembler` con el orden verificado (§6.6). Comparar en staging contra un post histórico antes de cerrar F2 |
| **Reescribir de más**: "aprovechar" la migración para arreglar rarezas de `main` | El resultado publicado deja de ser igual al histórico y la migración deja de ser verificable | El §18 es el criterio: lo que no esté en la columna "idéntico" necesita una decisión explícita y por escrito |
| **Diferencias de HTML** entre lo que generaba el editor clásico y lo que envía REST | Posts con maquetación distinta a los históricos | Comparar en staging un post generado por cada vía antes de F2 |
| **Coste y latencia de OpenAI** | Un lote grande se dispara en tiempo y en gasto | `SCHEDULER_BATCH_SIZE`, sin reintento automático (§10.4) y registrar tokens por ejecución en `executions.result` |
| **Rate limit del hosting WordPress** | 429 en lotes grandes | Semáforo por `site_id` + los reintentos que ya trae el cliente para `GET/HEAD/OPTIONS` |
| **Dos instancias del bot durante la transición** | Publicaciones duplicadas | `bot_key` distinto + claim atómico. No levantar v3 con el scheduler activo hasta apagar el de `main` |

---

## 18. Checklist de paridad con `main`

Repaso de **cada** comportamiento observable de
[new_post_contoller.py](../app/controllers/new_post_contoller.py) y
[optimize_post_controller.py](../app/controllers/optimize_post_controller.py) de
`main`. Esta tabla es el criterio de aceptación funcional de la migración: si
algo no está aquí, no está cubierto.

### Flujo de creación

| # | Comportamiento en `main` | v3 | Dónde |
|---|---|---|---|
| 1 | Login con `campaigns.email` / `campaigns.password` | Basic Auth con Application Password | §5.2, §15 |
| 2 | Título del post | campo `title` | §6.2 |
| 3 | Cuerpo generado (intro + cuerpo + conclusión) | campo `content` | §7 |
| 4 | Enlaces de keywords en la intro | `build_links()` dentro de la generación | §7.2 |
| 5 | Enlaces de conclusión en el cierre | `build_links()` dentro de la generación | §7.2 |
| 6 | Enlace externo **después** del contenido | bloque 2 del `ContentAssembler` | §6.6 |
| 7 | Imagen insertada en el cuerpo, tamaño *full* | bloque 3, `<figure class="wp-block-image size-full">` | §6.6 |
| 8 | Enlaces de ciudad **al final** | bloque 4 del `ContentAssembler` | §6.6 |
| 9 | Validación de que `citys` y `citys_urls` tienen igual longitud | `build_links()` lanza `ValueError` (y además para keywords y conclusiones, que `main` no validaba) | §7.2 |
| 10 | Imagen descargada de Google Drive y redimensionada a 700×400 WebP | `image_resolver` → `download_and_resize` | §8 |
| 11 | Caption y descripción del medio vaciadas | `POST media/{id}` con `caption:""`, `description:""` | §6.2 |
| 12 | Texto alternativo = `Path(image_path).stem` | idéntico: `Path(image_path).stem` | §7.1 |
| 13 | Frase clave de Yoast = **el título** | `keyphrase = post.title` | §7.1 |
| 14 | Título SEO de Yoast | meta `_yoast_wpseo_title` | §6.2 |
| 15 | Meta descripción generada por IA | meta `_yoast_wpseo_metadesc` | §6.2, §7 |
| 16 | Slug | campo `slug` | §6.2 |
| 17 | Categorías: nombre único sin separar por comas; si no existe, aviso y se publica igual | idéntico: `resolve_categories_lenient()` | §6.7 |
| 18 | Hashtags separados por comas, creados si no existen | array `tags`, `resolve_tags` siempre crea | §6.2 |
| 19 | Imagen destacada (buscada por nombre de archivo) | campo `featured_media` con el `media_id` ya conocido | §6.2 |
| 20 | Confirmación visual de la imagen destacada | la respuesta del `POST` incluye `featured_media`; se verifica ahí | §6.2 |
| 21 | Publicar | `POST posts/{id}` con `status: "publish"` | §6.2 |
| 22 | `post_service.publish_post(id)` → `status = True` | `state = 'done'` + `published_at` + `wp_post_id` + `wp_post_url` | §5.3 |
| 23 | Captura de pantalla al fallar | `executions.error` + `execution_logs` | §5.5 |
| 24 | Un fallo no detiene el resto del lote | se conserva: cada post es una tarea independiente | §10 |

### Flujo de optimización

| # | Comportamiento en `main` | v3 | Dónde |
|---|---|---|---|
| 25 | Navegar a `edition_url` y entrar a editar | `resolve_post_ref()` → `PostRef(route, id)` | §6.4 |
| 26 | Detectar Elementor y volver al editor clásico | idéntico: `_elementor_edit_mode: ""` en el mismo `POST` | §6.5 |
| 27 | Reemplazar el título completo | campo `title` | §6.3 |
| 28 | Reemplazar el contenido completo | campo `content` (mismo `ContentAssembler`) | §6.3, §6.6 |
| 29 | Enlace externo, imagen y enlaces de ciudad, en ese orden | idéntico al flujo de creación | §6.6 |
| 30 | **Borrar todos los hashtags existentes** antes de poner los nuevos | el array `tags` reemplaza el anterior; no hace falta borrar | §6.8 |
| 31 | **Desmarcar todas las categorías** antes de marcar las nuevas | el array `categories` reemplaza el anterior | §6.8 |
| 32 | Frase clave, título SEO y meta descripción de Yoast | las tres metas en el mismo `POST` | §6.3 |
| 33 | **El slug NO se toca** | `keep_slug = True` por defecto — verificado contra `main`, no es una suposición | §6.1, §6.3 |
| 34 | Imagen destacada **siempre** reemplazada | `keep_featured_image = False` por defecto | §6.1, §8 |
| 35 | El post sigue publicado (botón Actualizar) | no se envía `status` en el `POST` | §6.3 |
| 36 | Sin forma de deshacer | snapshot `previous_*` + endpoint de rollback | §5.4, §11 |

### Cobertura

Repasada la lista completa, **los 36 comportamientos son replicables por REST**.
No queda ningún caso en el que la API no pueda hacer lo que hacía el navegador.

El que más lo parecía —el botón *"Volver al editor de WordPress"* de Elementor
(#26)— resultó ser un simple meta: `_elementor_edit_mode` (§6.5). Va en la misma
petición que el resto de campos, así que ni siquiera añade una llamada.

Hay **dos correcciones de defecto** que no alteran lo que se publica, solo hacen
que el bot haga lo que ya pretendía hacer:

1. **El filtro de fecha** (§10.1): `date::date = CURRENT_DATE` en vez de
   comparar un `DateTime` con un `date`. Mismo criterio de `main` ("los posts de
   hoy"), escrito de forma que funcione también cuando la fecha no es medianoche.
2. **Idioma no soportado** (§7): se lanza un error con mensaje claro en lugar de
   un `UnboundLocalError` varias líneas más abajo. En ambos casos el post falla;
   solo cambia el mensaje.

Todo lo demás de las tablas anteriores es **idéntico a `main`**.

### Mejoras candidatas — explícitamente fuera de alcance

Se detectaron durante el análisis y **no se implementan aquí**. Quedan anotadas
para decidirlas después, por separado y con su propia validación:

- Texto alternativo legible en vez del nombre de archivo (§7.1).
- Separar las categorías por comas (§6.7).
- Convertir en error los enlaces desparejados de keywords y conclusiones (§7.2).
- Procesar los posts atrasados que nunca llegaron a publicarse (§10.1).
- Reintento automático de los posts fallidos (§10.4).

---

## 19. Qué NO entra en v3

Decisiones explícitas de alcance, para que no se cuelen por el camino:

- **No** se mantiene compatibilidad con Playwright. No hay modo "fallback a
  navegador": si un caso no se puede hacer por REST, se documenta y se resuelve
  a mano.
- **No** se conserva la base de datos compartida del SEO Agent. v3 tiene base
  propia; si hace falta sincronizar campañas con el SEO Agent, es un proceso
  aparte.
- **No** se generan contenidos desde el canal del orquestador: ahí el contenido
  llega ya escrito, como en `post-orquestador`. La generación con GPT-4 es del
  flujo local (Excel + scheduler).
- **No** se implementa multi-instancia real (varios procesos repartiéndose la
  carga). El claim atómico lo deja preparado, pero el scheduler asume una
  instancia activa.

---

## 20. Puntos abiertos antes de empezar

El comportamiento está cerrado (§18). Lo que sigue son decisiones que **no se
pueden tomar desde el código** porque dependen de datos o de criterio del
equipo. Conviene resolverlas antes de la fase que las necesita.

| # | Punto abierto | Lo necesita | Quién decide |
|---|---|---|---|
| 1 | **Zona horaria real de la operación** y zona del servidor de PostgreSQL. De esto depende el filtro del claim (§10.3) | F3 | Operaciones |
| 2 | **Cuántos posts de cada campaña usan Elementor.** Ya no bloquea (§6.5), pero determina cuántos posts cambiarán de modo de renderizado la primera vez que se optimicen | F4 | Consulta a la BD de cada sitio |
| 3 | **Qué hacer con los posts atrasados** que nunca se publicaron por el bug del filtro de fecha (§10.1). Hay que contarlos antes de decidir | F3 | Negocio |
| 4 | **Modelo de OpenAI**: `main` usa `gpt-4`, que es caro y lento. v3 lo deja configurable, pero cambiarlo altera el texto y exige revisar la calidad editorial | F2 | Negocio + editorial |
| 5 | **Usuario de WordPress para el bot** en cada sitio, y su rol. Necesita `edit_posts` y `upload_files`; conviene que no sea el administrador principal | F0 | Operaciones |
| 6 | **Cuándo se apaga el bot de `main`.** Los dos no pueden tener el scheduler activo a la vez (§17) | F3 | Operaciones |

### Verificación de que el documento es suficiente

Antes de dar por buena la especificación, el desarrollador que la reciba debería
poder responder **sin preguntar**:

- ✅ Qué endpoint de WordPress corresponde a cada acción de Playwright → §6.8
- ✅ En qué orden se componen los bloques del contenido → §6.6
- ✅ Qué valor lleva cada campo cuando el Excel no lo trae → §7.1
- ✅ Qué pasa si una categoría no existe → §6.7
- ✅ Cómo se llega del `edition_url` a un id de WordPress → §6.4
- ✅ Cómo se reproduce el botón de Elementor → §6.5
- ✅ Qué se escribe y en qué orden al optimizar → §6.3
- ✅ Cómo se evita publicar dos veces el mismo post → §10.2
- ✅ Qué separa al canal del orquestador del flujo local → §12
- ✅ Cómo se comprueba que un post de v3 es equivalente a uno de `main` → §16

Si alguna de estas preguntas no tiene respuesta en el documento, **es un fallo
de la especificación, no del desarrollador**: hay que ampliarla antes de
empezar a escribir código.
