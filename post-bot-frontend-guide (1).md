# Guía para construir el frontend del bot de posts

> Cómo añadir al dashboard del orquestador una pestaña que opere **únicamente**
> el bot de posts: encolar trabajos, ver la cola y vigilar el worker.
>
> Backend ya implementado: ver [post-bot-job-websocket.md](post-bot-job-websocket.md).
> Esta guía cubre solo la interfaz.

---

## 1. Regla principal: módulo de extensión, no tocar el core

El dashboard tiene esta estructura:

```text
frontend/
├── index.html        ← markup base y las 4 pestañas existentes
├── styles.css        ← estilos compartidos
├── app.js            ← cargador
├── app.core.js       ← dashboard SEO (76 KB) — NO TOCAR
└── instagram.js      ← extensión aislada — ESTE ES EL MODELO A SEGUIR
```

`app.js` es solo un cargador:

```js
(async () => {
  await import("/dashboard/app.core.js");
  await import("/dashboard/instagram.js");
})();
```

**El trabajo consiste en crear `frontend/post-bot.js` y añadir una línea a
`app.js`.** Nada más. Ni `index.html` ni `app.core.js` se modifican.

```js
await import("/dashboard/post-bot.js");
```

### Por qué así

`instagram.js` **se inyecta a sí mismo**: crea su botón de pestaña y su
`<section>` en tiempo de ejecución. La pestaña `Bot de posts` existente
(post-monitor) hizo lo contrario —markup en `index.html` y lógica dentro de
`app.core.js`— y por eso está entrelazada con el dashboard SEO.

El canal del bot de posts mantiene invariantes de aislamiento verificados con
pruebas en el backend. El frontend debe respetar el mismo criterio: si la
pestaña vive en un archivo aparte, se puede borrar entera sin tocar el resto.

> ⚠️ **Ojo con el nombre.** Ya existe una pestaña llamada `Bot de posts`, que es
> la de **telemetría** (`/api/v1/post-monitor/*`). Son cosas distintas. Usa un
> nombre que no se confunda: **`Cola de posts`** o **`Trabajos del bot`**.

---

## 2. Endpoints que consume — y solo estos

```text
GET    /api/v1/post-bot/overview
GET    /api/v1/post-bot/jobs?status=&capability=&limit=
GET    /api/v1/post-bot/jobs/{job_id}
POST   /api/v1/post-bot/jobs
POST   /api/v1/post-bot/jobs/{job_id}/cancel
GET    /api/v1/post-bot/workers
```

**No** debe llamar a `/api/v1/executions`, `/api/v1/flows`, `/api/v1/seo` ni
`/api/v1/post-monitor`. Si la pestaña necesita algo de ahí, es señal de que el
alcance se está desbordando.

`GET /api/v1/post-bot/jobs/{id}/input` **no es para el navegador**: se autentica
con el Bearer del bot, no con la sesión del dashboard. Devolverá 401.

### Autenticación

Las rutas de gestión usan la Basic Auth del dashboard, que el navegador ya tiene
de la sesión. Basta con `credentials: "same-origin"`, exactamente como hace
`instagram.js`:

```js
const API = "/api/v1";
const api = async (path, options = {}) => {
  const response = await fetch(API + path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
  return data;
};
```

No hay token que guardar ni cabecera que construir.

---

## 3. Contratos de datos

Campos exactos que devuelve el backend. Todo `id` llega como **string UUID** y
las fechas como **ISO 8601 o `null`**.

### Trabajo (`/jobs`, `/jobs/{id}`)

```json
{
  "id": "0c2f8b1e-…",
  "capability": "posts.create",
  "status": "queued",
  "priority": 0,
  "payload": { "campaign_id": 12, "post_title": "…" },
  "external_ref": "campaign-12-2026-09-22",
  "requested_by": "jorge",
  "worker_id": null,
  "attempts": 0,
  "result": null,
  "error": null,
  "dispatched_at": null,
  "started_at": null,
  "finished_at": null,
  "created_at": "2026-09-22T02:00:00+00:00",
  "updated_at": "2026-09-22T02:00:00+00:00"
}
```

`status` ∈ `queued` · `dispatched` · `running` · `succeeded` · `failed` · `cancelled`.

`result` se rellena al terminar con lo que devolvió el bot — para
`posts.create` suele traer `{"posts": [{"title": …, "url": …}], "summary": …}`.
En un fallo parcial puede venir `{"partial_posts": [...]}` junto a `error`.

### Worker (`/workers`)

```json
{
  "id": "…", "bot_key": "post-bot-prod-01", "name": "Post Bot v3",
  "bot_type": "create_post", "version": "3.0.0",
  "capabilities": ["posts.create", "posts.optimize"],
  "metadata": { "hostname": "…" },
  "enabled": true, "online": true,
  "max_concurrency": 2, "available_slots": 2, "current_jobs": 0,
  "last_seen_at": "2026-09-22T02:00:00+00:00"
}
```

`online` ya viene calculado contra `POST_BOT_PRESENCE_TTL_SECONDS`: **no lo
recalcules en el navegador**, el reloj del cliente no es fiable.

### Resumen (`/overview`)

```json
{
  "jobs": { "queued": 3, "dispatched": 1, "succeeded": 40, "failed": 2 },
  "queued": 3,
  "in_flight": 1,
  "workers": [ … ],
  "workers_online": 1,
  "presence_ttl_seconds": 60
}
```

`jobs` **solo trae las claves con conteo mayor que cero**. Para las tarjetas de
estadística usa `data.jobs.failed ?? 0`, no asumas que la clave existe.

---

## 4. Pantallas

Tres bloques bastan. Sugerencia de disposición siguiendo el resto del dashboard:

```
┌──────────────────────────────────────────────────────────────┐
│  [En cola 3] [En curso 1] [Exitosas 40] [Fallidas 2] [Bot ●] │   ← .stats
├──────────────────────────────────────────────────────────────┤
│  Nuevo trabajo                    │  Detalle del trabajo      │
│  · capability (select)            │  · estado, intentos       │
│  · campaña / título / contenido   │  · payload enviado        │
│  · payload JSON (textarea)        │  · result o error         │
│  · external_ref (opcional)        │  · [Cancelar]             │
│  [Encolar]                        │                           │
├──────────────────────────────────────────────────────────────┤
│  Cola          filtros: estado ▾  capability ▾   [↺ Recargar] │
│  ┌──────────┬────────────┬────────┬──────────┬─────────────┐  │
│  │ Creado   │ Capability │ Estado │ Intentos │ Acciones    │  │
│  └──────────┴────────────┴────────┴──────────┴─────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### El formulario de encolado

El orquestador **no interpreta el `payload`**: lo transporta tal cual hasta el
bot. Eso obliga a una decisión de interfaz.

**Recomendado:** campos cómodos para lo habitual (`campaign_id`, `post_title`,
`content`, `category`, `image_prompt`) **más** un textarea JSON que se fusiona
encima. Así el 90 % de los casos se hacen con el formulario y el 10 % raro sigue
siendo posible sin tocar código:

```js
function buildPayload() {
  const base = {
    campaign_id: Number(el("#pb-campaign").value) || undefined,
    post_title: el("#pb-title").value.trim() || undefined,
    content: el("#pb-content").value.trim() || undefined,
    category: el("#pb-category").value.trim() || undefined,
    image_prompt: el("#pb-image").value.trim() || undefined,
  };
  const extra = el("#pb-json").value.trim();
  const merged = { ...base, ...(extra ? JSON.parse(extra) : {}) };
  // El backend rechaza un payload vacío con 422.
  Object.keys(merged).forEach((k) => merged[k] === undefined && delete merged[k]);
  return merged;
}
```

Valida el JSON **antes** de enviar y muestra el error de parseo en la interfaz;
si no, el usuario recibe un 422 genérico sin saber qué línea está mal.

Para `posts.optimize` el campo que manda es el destino: `edition_url`,
`post_url` o `wp_post_id`. Cambia las etiquetas del formulario según el
`capability` seleccionado.

---

## 5. Respuestas que hay que tratar aparte

Esto es lo que diferencia una pestaña que funciona de una que confunde:

| Situación | Respuesta | Qué mostrar |
|---|---|---|
| Trabajo encolado | `201` + el trabajo | "Encolado" y refrescar la cola |
| `external_ref` repetido, mismo payload | **`200`** + el trabajo + `duplicate: true` | "Ya estaba encolado", **no** es un error |
| `external_ref` repetido, payload distinto | `409` | "Ese external_ref ya existe con otro contenido" |
| `capability` desconocida | `422` | Error de validación |
| Cancelar un trabajo que ya salió al bot | `409` | "Ya está en el bot, no se puede cancelar" |
| Cancelar uno ya terminado | `409` | Mismo mensaje |
| Trabajo inexistente | `404` | |

El caso del `200` con `duplicate: true` es el que más se suele equivocar:
`response.ok` es verdadero, así que si no lo distingues el usuario cree que creó
un trabajo nuevo cuando no lo hizo.

```js
const created = await api("/post-bot/jobs", { method: "POST", body: JSON.stringify(body) });
message.textContent = created.duplicate
  ? `Ya existía: ${created.id}`
  : `Encolado: ${created.id}`;
```

---

## 6. Actualización: polling, no WebSocket

**El WebSocket `/api/v1/post-bot/ws` es del bot, no del navegador.** Si lo
abres desde la interfaz, el servidor cierra la conexión con 4401 porque el
navegador no tiene el Bearer del bot — y aunque lo tuviera, registrarse ahí
suplantaría al worker.

La interfaz consulta por REST:

- Mientras la pestaña está activa: `/overview` + `/jobs` cada **5 s**.
- Si hay un trabajo abierto en el detalle y no está en estado terminal:
  `/jobs/{id}` cada **3 s**.
- **Detén los temporizadores al cambiar de pestaña.** `instagram.js` usa
  `clearTimeout(state.timer)`; repítelo. Si no, la pestaña sigue consultando en
  segundo plano toda la sesión.

```js
function stopPolling() { clearTimeout(state.timer); state.timer = null; }
```

Encadena con `setTimeout` tras completar la petición, no con `setInterval`: si
el backend va lento, `setInterval` acumula peticiones solapadas.

---

## 7. Estilos: reutilizar, no inventar

`styles.css` ya trae lo necesario. Clases disponibles:

| Clase | Uso |
|---|---|
| `.card`, `.panel`, `.panel-head` | Contenedores y cabeceras de sección |
| `.stats`, `.stat` | Rejilla de tarjetas de estadística |
| `.stat.queued` / `.running` / `.success` / `.danger` | Color del número según estado |
| `.button` + `.primary` `.secondary` `.dark` `.ghost` `.danger` | Botones |
| `.table-wrap` + `<table>` | Tablas con scroll horizontal |
| `.eyebrow`, `.helper` | Antetítulo y texto secundario |
| `.row-actions` | Fila de filtros o acciones |
| `.notice`, `.notice.error` | Avisos |

Fíjate en que `.stat.queued`, `.running`, `.success` y `.danger` **coinciden con
los estados del trabajo**: mapea directo sin inventar colores.

Si hace falta algo propio, inyéctalo desde el módulo con un `<style>` con id
único, como hace `ensureStyles()` en `instagram.js`. **No edites `styles.css`**:
mantiene la pestaña borrable de una pieza.

---

## 8. Esqueleto de arranque

`frontend/post-bot.js`:

```js
const API = "/api/v1";
const state = { timer: null, jobId: null };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const el = (sel) => document.querySelector(sel);

function mount() {
  const tabs = document.querySelector(".workspace-tabs");
  const views = document.querySelector("main.shell");
  if (!tabs || !views || document.getElementById("view-post-bot")) return;

  const tab = document.createElement("button");
  tab.className = "workspace-tab";
  tab.dataset.view = "post-bot";
  tab.textContent = "Cola de posts";
  tabs.appendChild(tab);

  const section = document.createElement("div");
  section.id = "view-post-bot";
  section.className = "workspace-view";
  section.innerHTML = `…`;           // markup de §4
  views.appendChild(section);

  tab.addEventListener("click", activate);
  // Las otras pestañas deben detener nuestro polling:
  document.querySelectorAll(".workspace-tab").forEach((other) => {
    if (other !== tab) other.addEventListener("click", stopPolling);
  });
}

function activate() {
  document.querySelectorAll(".workspace-tab")
    .forEach((b) => b.classList.toggle("active", b.dataset.view === "post-bot"));
  document.querySelectorAll(".workspace-view")
    .forEach((v) => v.classList.toggle("active", v.id === "view-post-bot"));
  refresh();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mount);
} else {
  mount();
}
```

El patrón de `activate()` está copiado de `instagram.js` a propósito: es el
mecanismo que usa el dashboard para cambiar de vista y conviene no desviarse.

---

## 9. Escapado obligatorio

El `payload` y el `error` los escribe **un usuario o el bot**, y se pintan en la
tabla. Todo valor que entre en `innerHTML` pasa por `esc()`.

Para mostrar el `payload` y el `result` usa `<pre>` con `textContent`, no
`innerHTML`:

```js
el("#pb-result").textContent = JSON.stringify(job.result ?? {}, null, 2);
```

Es más seguro y además respeta los saltos de línea del JSON.

---

## 10. Criterios de aceptación

- [ ] Existe `frontend/post-bot.js` y `app.js` lo importa. `index.html`,
      `app.core.js` y `styles.css` **sin cambios**.
- [ ] La pestaña se llama distinto de la de telemetría (`Bot de posts`).
- [ ] Solo consume rutas `/api/v1/post-bot/*`.
- [ ] Un trabajo encolado aparece en la cola sin recargar la página.
- [ ] `duplicate: true` se muestra como "ya existía", no como creación nueva.
- [ ] Un `409` al cancelar muestra un mensaje entendible, no "Error 409".
- [ ] El estado del worker (online/offline, slots) sale de `/workers`, no se
      calcula en el navegador.
- [ ] Al cambiar de pestaña, el polling se detiene (verificable en la pestaña
      Red del navegador).
- [ ] Un `payload` con `<script>` en el título se pinta como texto.
- [ ] Borrar `post-bot.js` y su línea de `app.js` deja el dashboard intacto.

---

## 11. Cómo probarlo sin el bot conectado

No hace falta que el bot esté vivo: un trabajo encolado se queda en `queued`
hasta que un worker se conecte, y eso es exactamente lo que debe mostrar la
interfaz.

```bash
# Encolar desde la terminal y comprobar que aparece en la pestaña
curl -u admin:pass -X POST http://localhost:8001/api/v1/post-bot/jobs \
  -H 'Content-Type: application/json' \
  -d '{"capability":"posts.create","payload":{"campaign_id":12,"post_title":"Prueba"}}'

# Repetir con external_ref para ver el caso duplicate
curl -u admin:pass -X POST http://localhost:8001/api/v1/post-bot/jobs \
  -H 'Content-Type: application/json' \
  -d '{"capability":"posts.create","external_ref":"x1","payload":{"post_title":"A"}}'
```

Lanzar dos veces el segundo comando debe devolver `201` y luego `200` con
`duplicate: true`. Es la forma más rápida de validar §5.
