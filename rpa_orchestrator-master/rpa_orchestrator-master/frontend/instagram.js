/* Extensión de Instagram del dashboard.
 *
 * Se monta como una pestaña más sobre el shell que arma app.core.js y no
 * comparte estado con él: todo lo de este módulo vive en `state` y en el
 * subárbol `#view-instagram`.
 */

const API = "/api/v1";
const POLL_INTERVAL_MS = 4000;
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

const state = {
  executionId: null,
  timer: null,
  catalog: null,
};

const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return data;
}

const $ig = (id) => document.getElementById(id);
const isViewActive = () => Boolean($ig("view-instagram")?.classList.contains("active"));

function ensureStyles() {
  if ($ig("instagram-dashboard-styles")) return;
  const style = document.createElement("style");
  style.id = "instagram-dashboard-styles";
  style.textContent = `
#view-instagram .ig-grid{display:grid;grid-template-columns:minmax(320px,1fr) minmax(420px,1.4fr);gap:16px}
#view-instagram .ig-card{padding:18px;margin-bottom:16px}
#view-instagram .ig-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#view-instagram .ig-field{display:flex;flex-direction:column;gap:6px;margin:10px 0}
#view-instagram .ig-field input,#view-instagram .ig-field select,#view-instagram .ig-field textarea{width:100%;box-sizing:border-box}
#view-instagram .ig-checks{max-height:180px;overflow:auto;border:1px solid var(--border,#ddd);padding:8px;border-radius:8px}
#view-instagram .ig-check{display:flex;gap:8px;padding:5px 2px}
#view-instagram .ig-status{font-weight:700;text-transform:uppercase}
#view-instagram .ig-muted{opacity:.7}
#view-instagram .ig-table{width:100%;border-collapse:collapse}
#view-instagram .ig-table th,#view-instagram .ig-table td{padding:7px;border-bottom:1px solid var(--border,#ddd);text-align:left;vertical-align:top}
#view-instagram .ig-events{max-height:220px;overflow:auto;font-family:monospace;font-size:12px;white-space:pre-wrap}
#view-instagram .ig-result{max-height:340px;overflow:auto;font-family:monospace;font-size:12px;white-space:pre-wrap}
@media(max-width:900px){#view-instagram .ig-grid{grid-template-columns:1fr}}
`;
  document.head.appendChild(style);
}

const VIEW_TEMPLATE = `
<div class="ig-grid">
  <section class="card ig-card">
    <div class="panel-head"><h2>Instagram · Nueva ejecución</h2></div>
    <div class="ig-field">
      <label for="ig-capability">Operación</label>
      <select id="ig-capability">
        <option value="instagram.prospecting">Prospección</option>
        <option value="instagram.maduracion">Maduración</option>
      </select>
    </div>
    <div class="ig-field">
      <label>Tipos de tarea</label>
      <div id="ig-task-types" class="ig-checks"><span class="ig-muted">Cargando catálogo…</span></div>
    </div>
    <div class="ig-field">
      <label for="ig-target-mode">Destino</label>
      <select id="ig-target-mode">
        <option value="accounts">Cuentas seleccionadas</option>
        <option value="owner">Propietario</option>
        <option value="all">Todas las cuentas Instagram</option>
      </select>
    </div>
    <div class="ig-field" id="ig-accounts-field">
      <label>Cuentas Instagram</label>
      <div id="ig-accounts" class="ig-checks"><span class="ig-muted">Cargando…</span></div>
    </div>
    <div class="ig-field" id="ig-owner-field" hidden>
      <label for="ig-owner">Propietario</label>
      <select id="ig-owner"></select>
    </div>
    <div class="ig-field">
      <label for="ig-custom">Tarea personalizada (JSON opcional)</label>
      <textarea id="ig-custom" rows="3" placeholder='{"type":"muro","post":"texto"}'></textarea>
    </div>
    <div class="ig-field">
      <label for="ig-executor">Bot executor (opcional)</label>
      <input id="ig-executor" placeholder="Se resuelve en el backend si se deja vacío">
    </div>
    <div class="ig-row">
      <button id="ig-run" class="button primary">Crear ejecución</button>
      <span id="ig-create-message" class="ig-muted" aria-live="polite"></span>
    </div>
  </section>
  <section class="card ig-card">
    <div class="panel-head">
      <h2>Seguimiento</h2>
      <button id="ig-cancel" class="button danger" disabled>Cancelar</button>
    </div>
    <div id="ig-current" class="ig-muted">No hay ejecución seleccionada.</div>
    <div id="ig-events" class="ig-events"></div>
    <div class="panel-head"><h2>Resultado</h2></div>
    <pre id="ig-result" class="ig-result">Sin resultado.</pre>
  </section>
</div>
<section class="card ig-card">
  <div class="panel-head">
    <h2>Historial Instagram</h2>
    <button id="ig-refresh-history" class="button secondary">Recargar</button>
  </div>
  <div class="table-wrap">
    <table class="ig-table">
      <thead>
        <tr><th>Execution</th><th>Capability</th><th>Estado</th><th>Creada</th><th>Acciones</th></tr>
      </thead>
      <tbody id="ig-history"></tbody>
    </table>
  </div>
</section>
`;

function mount() {
  const tabs = document.querySelector(".workspace-tabs");
  const shell = document.querySelector("main.shell");
  if (!tabs || !shell || $ig("view-instagram")) return;
  ensureStyles();

  const tab = document.createElement("button");
  tab.className = "workspace-tab";
  tab.dataset.view = "instagram";
  tab.textContent = "Instagram";
  tabs.appendChild(tab);

  const section = document.createElement("section");
  section.id = "view-instagram";
  section.className = "workspace-view";
  section.innerHTML = VIEW_TEMPLATE;
  shell.appendChild(section);

  // app.core.js ya delega los clics de .workspace-tab a switchMainView, que
  // activa la vista por id. Aca solo se engancha la carga de datos.
  tab.addEventListener("click", onViewActivated);
  $ig("ig-target-mode").addEventListener("change", updateTargetFields);
  $ig("ig-run").addEventListener("click", createExecution);
  $ig("ig-cancel").addEventListener("click", cancelExecution);
  $ig("ig-refresh-history").addEventListener("click", loadHistory);
  loadCatalog();
}

function onViewActivated() {
  loadHistory();
  // El polling se detiene al salir de la pestaña; al volver se retoma.
  if (state.executionId && state.timer === null) startPolling(state.executionId);
}

async function loadCatalog() {
  try {
    state.catalog = await api("/instagram/catalog");
  } catch (error) {
    $ig("ig-create-message").textContent = `Catálogo: ${error.message}`;
    return;
  }
  const tasks = state.catalog.task_types || [];
  $ig("ig-task-types").innerHTML = tasks.map((task) => `
    <label class="ig-check">
      <input type="checkbox" value="${esc(task.id)}">
      <span>${esc(task.id)} · ${esc(task.task_name || task.descripcion || "Tarea")}</span>
    </label>`).join("")
    || `<span class="ig-muted">No hay tareas Instagram disponibles.</span>`;

  const accounts = state.catalog.accounts || [];
  $ig("ig-accounts").innerHTML = accounts.map((account) => `
    <label class="ig-check">
      <input type="checkbox" value="${esc(account.id)}">
      <span>${esc(account.id)} · ${esc(account.account_name || "Cuenta")}</span>
    </label>`).join("")
    || `<span class="ig-muted">No hay cuentas Instagram disponibles.</span>`;

  const owners = state.catalog.owners || [];
  $ig("ig-owner").innerHTML = `<option value="">Seleccionar…</option>`
    + owners.map((item) => `<option value="${esc(item.id)}">${esc(item.owner_name || item.id)}</option>`).join("");
}

function updateTargetFields() {
  const mode = $ig("ig-target-mode").value;
  $ig("ig-accounts-field").hidden = mode !== "accounts";
  $ig("ig-owner-field").hidden = mode !== "owner";
}

function selectedValues(selector) {
  return [...document.querySelectorAll(`${selector} input:checked`)].map((input) => Number(input.value));
}

function buildPayload(message) {
  const taskTypes = selectedValues("#ig-task-types");
  if (!taskTypes.length) {
    message.textContent = "Selecciona al menos un tipo de tarea.";
    return null;
  }
  const mode = $ig("ig-target-mode").value;
  const targets = { mode };
  if (mode === "accounts") {
    targets.account_ids = selectedValues("#ig-accounts");
    if (!targets.account_ids.length) {
      message.textContent = "Selecciona al menos una cuenta.";
      return null;
    }
  }
  if (mode === "owner") {
    const owner = $ig("ig-owner").value;
    if (!owner) {
      message.textContent = "Selecciona un propietario.";
      return null;
    }
    targets.owner_id = Number(owner);
  }
  let customTask = {};
  const custom = $ig("ig-custom").value.trim();
  if (custom) {
    try {
      customTask = JSON.parse(custom);
    } catch {
      message.textContent = "El JSON de tarea personalizada no es válido.";
      return null;
    }
  }
  const options = {};
  const executor = $ig("ig-executor").value.trim();
  if (executor) options.bot_executor = executor;
  const capability = $ig("ig-capability").value;
  return {
    schema_version: `${capability}.input.v1`,
    stage: capability === "instagram.maduracion" ? "instagram_maduracion" : "instagram_prospecting",
    capability,
    task_types: taskTypes,
    targets,
    custom_task: customTask,
    schedule: {},
    options,
  };
}

async function createExecution() {
  const message = $ig("ig-create-message");
  const payload = buildPayload(message);
  if (payload === null) return;
  try {
    message.textContent = "Creando…";
    const execution = await api("/executions/standalone/instagram", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const id = execution?.id;
    if (!id) throw new Error("La API no devolvió el id de ejecución");
    message.textContent = `Creada: ${id}`;
    $ig("ig-events").textContent = "";
    $ig("ig-result").textContent = "Esperando resultado…";
    startPolling(id);
    await loadHistory();
  } catch (error) {
    message.textContent = `Error: ${error.message}`;
  }
}

function stopPolling() {
  clearTimeout(state.timer);
  state.timer = null;
}

function startPolling(id) {
  stopPolling();
  state.executionId = id;
  $ig("ig-cancel").disabled = false;
  $ig("ig-current").textContent = `Execution: ${id}`;

  const poll = async () => {
    state.timer = null;
    // No se consulta la API mientras la pestaña no está visible: evita dejar
    // un poll indefinido contra endpoints que comparten el resto de flujos.
    if (!isViewActive()) return;
    try {
      const execution = await api(`/executions/${encodeURIComponent(id)}`);
      renderExecution(execution);
      await loadEvents(id);
      if (TERMINAL_STATUSES.has(execution.status)) {
        await loadResult(id);
        $ig("ig-cancel").disabled = true;
        return;
      }
    } catch (error) {
      $ig("ig-current").textContent = `Error: ${error.message}`;
    }
    state.timer = setTimeout(poll, POLL_INTERVAL_MS);
  };
  poll();
}

function renderExecution(execution) {
  $ig("ig-current").innerHTML = `
    <div class="ig-status">${esc(execution.status)}</div>
    <div>${esc(execution.id)}</div>
    <div class="ig-muted">${esc(execution.requested_capability || "Instagram")}</div>`;
}

async function loadEvents(id) {
  try {
    const events = await api(`/executions/${encodeURIComponent(id)}/events?limit=100`);
    $ig("ig-events").textContent = events
      .map((event) => `[${event.sequence ?? "-"}] ${event.event_type || "event"}: ${event.summary || ""}`)
      .join("\n");
  } catch {
    // Los eventos son informativos: un fallo aca no corta el seguimiento.
  }
}

async function loadResult(id) {
  try {
    const result = await api(`/instagram/executions/${encodeURIComponent(id)}/result`);
    $ig("ig-result").textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    $ig("ig-result").textContent = error.message;
  }
}

async function cancelExecution() {
  if (!state.executionId) return;
  if (!window.confirm("¿Cancelar la ejecución de Instagram?")) return;
  try {
    await api(`/executions/${encodeURIComponent(state.executionId)}/cancel`, {
      method: "POST",
      body: "{}",
    });
    startPolling(state.executionId);
  } catch (error) {
    $ig("ig-current").textContent = `Cancelación: ${error.message}`;
  }
}

async function loadHistory() {
  const body = $ig("ig-history");
  if (!body) return;
  try {
    const data = await api("/instagram/executions?limit=50");
    const items = data.items || [];
    body.innerHTML = items.map((item) => `
      <tr>
        <td><code>${esc(item.id)}</code></td>
        <td>${esc(item.requested_capability)}</td>
        <td>${esc(item.status)}</td>
        <td>${esc(item.created_at)}</td>
        <td><button class="button ghost ig-open" data-id="${esc(item.id)}">Abrir</button></td>
      </tr>`).join("")
      || `<tr><td colspan="5" class="ig-muted">Sin ejecuciones Instagram.</td></tr>`;
    body.querySelectorAll(".ig-open").forEach((button) => {
      button.addEventListener("click", () => startPolling(button.dataset.id));
    });
  } catch (error) {
    body.innerHTML = `<tr><td colspan="5">${esc(error.message)}</td></tr>`;
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mount);
} else {
  mount();
}
