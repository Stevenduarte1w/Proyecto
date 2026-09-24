const API = "/api/v1/post-bot";
const state = { timer: null, jobId: null, selectedStatus: null, active: false, loading: false };
const el = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));

function ensureStyles() {
  if (document.getElementById("post-bot-styles")) return;
  const style = document.createElement("style");
  style.id = "post-bot-styles";
  style.textContent = `
    #view-post-bot-jobs .pb-grid{display:grid;grid-template-columns:minmax(280px,360px) minmax(0,1fr);gap:16px}
    #view-post-bot-jobs .pb-form{display:grid;gap:12px}
    #view-post-bot-jobs .pb-form label{display:grid;gap:6px;font-size:13px}
    #view-post-bot-jobs .pb-form input,#view-post-bot-jobs .pb-form select,#view-post-bot-jobs .pb-form textarea{width:100%;box-sizing:border-box}
    #view-post-bot-jobs .pb-form textarea{min-height:210px;font:12px/1.5 'JetBrains Mono',monospace}
    #view-post-bot-jobs .pb-workers{display:flex;gap:8px;flex-wrap:wrap}
    #view-post-bot-jobs .pb-worker{padding:8px 10px;border-radius:8px;background:rgba(120,140,160,.12);font-size:12px}
    #view-post-bot-jobs .pb-online{color:#16804a} #view-post-bot-jobs .pb-offline{color:#b54747}
    #view-post-bot-jobs .pb-detail pre{max-height:320px;overflow:auto;white-space:pre-wrap;word-break:break-word}
    #view-post-bot-jobs .pb-message{min-height:24px;margin:8px 0}
    #view-post-bot-jobs .pb-message.error{color:#b42318}
    #view-post-bot-jobs .pb-message.success{color:#16804a}
    #view-post-bot-jobs .pb-status{font-weight:600;text-transform:capitalize}
    @media(max-width:900px){#view-post-bot-jobs .pb-grid{grid-template-columns:1fr}}
  `;
  document.head.append(style);
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
    const error = new Error(detail || `Error ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function mount() {
  const tabs = document.querySelector(".workspace-tabs");
  const views = document.querySelector("main.shell");
  if (!tabs || !views || document.getElementById("view-post-bot-jobs")) return;
  ensureStyles();

  const tab = document.createElement("button");
  tab.className = "workspace-tab";
  tab.dataset.view = "post-bot-jobs";
  tab.textContent = "Cola de posts";
  tabs.append(tab);

  const section = document.createElement("section");
  section.id = "view-post-bot-jobs";
  section.className = "workspace-view";
  section.innerHTML = `
    <section class="stats">
      <article class="stat card queued"><strong id="pb-queued">0</strong><span>En cola</span></article>
      <article class="stat card running"><strong id="pb-running">0</strong><span>En curso</span></article>
      <article class="stat card success"><strong id="pb-succeeded">0</strong><span>Completados</span></article>
      <article class="stat card danger"><strong id="pb-failed">0</strong><span>Fallidos</span></article>
      <article class="stat card"><strong id="pb-workers-online">0</strong><span>Workers online</span></article>
    </section>
    <div id="pb-message" class="pb-message" role="status" aria-live="polite"></div>
    <div class="pb-grid">
      <section class="card panel">
        <div class="panel-head"><div><p class="eyebrow">NUEVO TRABAJO</p><h2>Encolar post</h2></div></div>
        <form id="pb-form" class="pb-form">
          <label>Acción
            <select name="capability"><option value="posts.create">Crear post</option><option value="posts.optimize">Optimizar post</option></select>
          </label>
          <label>Referencia externa (opcional)<input name="external_ref" maxlength="240" placeholder="ID estable para evitar duplicados"></label>
          <label>Prioridad<input name="priority" type="number" min="-100" max="100" value="0"></label>
          <label>Payload JSON<textarea name="payload" required spellcheck="false">{"campaign_id": 1, "title": "Título del post", "content": "<p>Contenido completo</p>"}</textarea></label>
          <button class="button primary" type="submit">Encolar trabajo</button>
        </form>
      </section>
      <div>
        <section class="card panel">
          <div class="panel-head"><div><p class="eyebrow">ESTADO</p><h2>Workers</h2></div><button id="pb-refresh" class="button secondary" type="button">Actualizar</button></div>
          <div id="pb-workers" class="pb-workers"><span class="helper">Cargando…</span></div>
        </section>
        <section class="card panel">
          <div class="panel-head"><div><p class="eyebrow">POST_BOT_JOBS</p><h2>Trabajos</h2></div></div>
          <div class="row-actions">
            <select id="pb-filter-status" aria-label="Filtrar por estado"><option value="">Todos los estados</option><option>queued</option><option>dispatched</option><option>running</option><option>succeeded</option><option>failed</option><option>cancelled</option></select>
            <select id="pb-filter-capability" aria-label="Filtrar por acción"><option value="">Todas las acciones</option><option value="posts.create">Crear</option><option value="posts.optimize">Optimizar</option></select>
          </div>
          <div class="table-wrap"><table><thead><tr><th>Creado</th><th>Acción</th><th>Estado</th><th>Referencia</th><th>Intentos</th><th>Acciones</th></tr></thead><tbody id="pb-jobs"></tbody></table></div>
        </section>
        <section class="card panel pb-detail">
          <div class="panel-head"><div><p class="eyebrow">DETALLE</p><h2 id="pb-detail-title">Selecciona un trabajo</h2></div></div>
          <div id="pb-detail" class="helper">El payload y el resultado se mostrarán aquí.</div>
        </section>
      </div>
    </div>`;
  views.append(section);

  tab.addEventListener("click", activate);
  document.querySelectorAll(".workspace-tab").forEach((other) => {
    if (other !== tab) other.addEventListener("click", stopPolling);
  });
  section.addEventListener("submit", onSubmit);
  section.addEventListener("click", onClick);
  el("#pb-refresh").addEventListener("click", () => refresh().catch(showError));
  el("#pb-filter-status").addEventListener("change", () => refresh().catch(showError));
  el("#pb-filter-capability").addEventListener("change", () => refresh().catch(showError));
}

function activate() {
  document.querySelectorAll(".workspace-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === "post-bot-jobs");
  });
  document.querySelectorAll(".workspace-view").forEach((view) => {
    view.classList.toggle("active", view.id === "view-post-bot-jobs");
  });
  state.active = true;
  refresh().catch(showError);
}

function stopPolling() {
  state.active = false;
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
}

function scheduleNext() {
  if (!state.active) return;
  if (state.timer) clearTimeout(state.timer);
  const delay = state.jobId && !["succeeded", "failed", "cancelled"].includes(state.selectedStatus) ? 3000 : 5000;
  state.timer = setTimeout(() => refresh().catch(showError), delay);
}

async function refresh() {
  if (!state.active || state.loading) return;
  state.loading = true;
  try {
    const status = el("#pb-filter-status")?.value || "";
    const capability = el("#pb-filter-capability")?.value || "";
    const params = new URLSearchParams({ limit: "100" });
    if (status) params.set("status", status);
    if (capability) params.set("capability", capability);
    const [overview, jobs, workers] = await Promise.all([
      api("/overview"), api(`/jobs?${params}`), api("/workers"),
    ]);
    el("#pb-queued").textContent = String(overview.queued ?? 0);
    el("#pb-running").textContent = String(overview.in_flight ?? 0);
    el("#pb-succeeded").textContent = String(overview.jobs?.succeeded ?? 0);
    el("#pb-failed").textContent = String(overview.jobs?.failed ?? 0);
    el("#pb-workers-online").textContent = String(overview.workers_online ?? 0);
    renderWorkers(workers);
    renderJobs(jobs);
    if (state.jobId) await loadDetail(state.jobId);
  } finally {
    state.loading = false;
    scheduleNext();
  }
}

function renderWorkers(workers) {
  const target = el("#pb-workers");
  if (!workers.length) {
    target.innerHTML = '<span class="helper">No hay workers registrados.</span>';
    return;
  }
  target.innerHTML = workers.map((worker) => `
    <span class="pb-worker ${worker.online ? "pb-online" : "pb-offline"}">
      ${esc(worker.name)} · ${worker.online ? "online" : "offline"} · ${esc(worker.available_slots)} slot libres
    </span>`).join("");
}

function renderJobs(jobs) {
  const target = el("#pb-jobs");
  if (!jobs.length) {
    target.innerHTML = '<tr><td colspan="6" class="helper">No hay trabajos para este filtro.</td></tr>';
    return;
  }
  target.innerHTML = jobs.map((job) => `
    <tr data-job-id="${esc(job.id)}" data-status="${esc(job.status)}">
      <td>${esc(new Date(job.created_at).toLocaleString())}</td>
      <td>${job.capability === "posts.optimize" ? "Optimizar" : "Crear"}</td>
      <td class="pb-status">${esc(job.status)}</td>
      <td>${esc(job.external_ref || "—")}</td>
      <td>${esc(job.attempts)}</td>
      <td class="row-actions"><button class="button ghost" type="button" data-action="detail" data-id="${esc(job.id)}">Ver</button>
      ${job.status === "queued" ? `<button class="button danger" type="button" data-action="cancel" data-id="${esc(job.id)}">Cancelar</button>` : ""}</td>
    </tr>`).join("");
  if (state.jobId) target.querySelector(`[data-job-id="${CSS.escape(state.jobId)}"]`)?.classList.add("active");
}

async function loadDetail(jobId) {
  const job = await api(`/jobs/${encodeURIComponent(jobId)}`);
  state.selectedStatus = job.status;
  el("#pb-detail-title").textContent = `${job.capability} · ${job.status}`;
  const detail = el("#pb-detail");
  detail.replaceChildren();
  const payloadLabel = document.createElement("p");
  payloadLabel.textContent = "Payload";
  const payload = document.createElement("pre");
  payload.textContent = JSON.stringify(job.payload ?? {}, null, 2);
  detail.append(payloadLabel, payload);
  if (job.result) {
    const resultLabel = document.createElement("p");
    resultLabel.textContent = "Resultado";
    const result = document.createElement("pre");
    result.textContent = JSON.stringify(job.result, null, 2);
    detail.append(resultLabel, result);
  }
  if (job.error) {
    const error = document.createElement("p");
    error.className = "pb-message error";
    error.textContent = job.error;
    detail.append(error);
  }
}

async function onSubmit(event) {
  if (event.target.id !== "pb-form") return;
  event.preventDefault();
  const form = new FormData(event.target);
  let payload;
  try {
    payload = JSON.parse(String(form.get("payload") || "{}"));
  } catch {
    showMessage("El payload debe ser JSON válido.", "error");
    return;
  }
  if (!payload || Array.isArray(payload) || typeof payload !== "object" || !Object.keys(payload).length) {
    showMessage("El payload debe ser un objeto JSON no vacío.", "error");
    return;
  }
  try {
    const job = await api("/jobs", { method: "POST", body: JSON.stringify({
      capability: form.get("capability"), payload,
      external_ref: String(form.get("external_ref") || "").trim() || null,
      priority: Number(form.get("priority") || 0),
    }) });
    state.jobId = String(job.id);
    showMessage(job.duplicate ? `Ya existía: ${job.id}` : `Encolado: ${job.id}`, "success");
    await refresh();
  } catch (error) {
    showError(error);
  }
}

async function onClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const jobId = button.dataset.id;
  if (button.dataset.action === "detail") {
    state.jobId = jobId;
    state.selectedStatus = null;
    await loadDetail(jobId).catch(showError);
    scheduleNext();
  } else if (button.dataset.action === "cancel") {
    try {
      await api(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
      showMessage("Trabajo cancelado.", "success");
      await refresh();
    } catch (error) {
      showMessage(error.status === 409 ? "El trabajo ya salió a ejecución y no se puede cancelar." : error.message, "error");
    }
  }
}

function showMessage(message, kind = "") {
  const target = el("#pb-message");
  target.textContent = message;
  target.className = `pb-message ${kind}`.trim();
}

function showError(error) {
  showMessage(error?.status === 409 ? "Ese identificador ya está en uso con otro contenido." : (error?.message || "No se pudo cargar la cola."), "error");
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, { once: true });
else mount();
