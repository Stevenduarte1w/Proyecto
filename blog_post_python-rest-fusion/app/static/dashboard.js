const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}
async function loadQueue() {
  const params = new URLSearchParams({ limit: "500" });
  if ($("#kind").value) params.set("kind", $("#kind").value);
  if ($("#state").value) params.set("state", $("#state").value);
  try {
    const items = await api(`/api/queue?${params}`);
    $("#queue-rows").innerHTML = items.map((item) => `<tr><td>${esc(item.kind)}</td><td>${esc(item.id)}</td><td>${esc(item.title)}</td><td>${esc(item.date)}</td><td class="pill">${esc(item.state)}</td><td>${esc(item.attempts)}</td><td class="error">${esc(item.last_error || "—")}</td><td>${item.wp_post_url ? `<a href="${esc(item.wp_post_url)}" target="_blank" rel="noopener">${esc(item.wp_post_id || "Abrir")}</a>` : "—"}</td></tr>`).join("") || '<tr><td colspan="8">No hay elementos para estos filtros.</td></tr>';
    $("#queue-message").textContent = `${items.length} elementos`;
  } catch (error) { $("#queue-message").textContent = error.message; }
}
async function loadHistory() {
  const params = new URLSearchParams({ limit: "500" });
  if ($("#source").value) params.set("source", $("#source").value);
  if ($("#execution-status").value) params.set("status", $("#execution-status").value);
  try {
    const items = await api(`/api/executions?${params}`);
    $("#execution-rows").innerHTML = items.map((item) => `<tr><td>${esc(item.started_at || item.created_at)}</td><td>${esc(item.source)}</td><td>${esc(item.kind)}</td><td>${esc(item.title)}</td><td class="pill">${esc(item.status)}</td><td class="error">${esc(item.error || "—")}</td><td><button class="action" data-execution="${esc(item.id)}">Ver</button></td></tr>`).join("") || '<tr><td colspan="7">No hay ejecuciones para estos filtros.</td></tr>';
    $("#history-message").textContent = `${items.length} ejecuciones`;
  } catch (error) { $("#history-message").textContent = error.message; }
}
document.querySelectorAll(".tabs button").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((tab) => tab.classList.toggle("active", tab === button));
  document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== button.dataset.view; });
}));
$("#refresh-queue").addEventListener("click", loadQueue);
$("#refresh-history").addEventListener("click", loadHistory);
$("#kind").addEventListener("change", loadQueue); $("#state").addEventListener("change", loadQueue);
$("#source").addEventListener("change", loadHistory); $("#execution-status").addEventListener("change", loadHistory);
$("#execution-rows").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-execution]"); if (!button) return;
  try { const data = await api(`/api/executions/${encodeURIComponent(button.dataset.execution)}`); $("#execution-json").textContent = JSON.stringify(data, null, 2); $("#execution-detail").hidden = false; }
  catch (error) { $("#history-message").textContent = error.message; }
});
loadQueue();
