const API = "/api/v1";

const state = {
  campaigns: [],
  pages: [],
  queue: [],
  currentQueueId: null,
  currentArtifact: null,
  rankPositions: {},
  selectedPageIds: new Set(),
  admin: {
    resource: "campaigns",
    records: [],
    editingId: null,
  },
  postMonitor: {
    loaded: false,
    overview: null,
    runs: [],
    alerts: [],
  },
  postGroups: {
    loaded: false,
    records: [],
    editingId: null,
  },
  editingPageId: null,
};

const ADMIN_RESOURCES = {
  campaigns: {
    label: "campaigns",
    endpoint: "campaigns",
    title: "Campaign",
    table: ["id", "name", "slug", "domain", "layout_id", "youtube_channel_id", "default_elementor_form_id", "active"],
    fields: [
      { name: "name", label: "Nombre", required: true },
      { name: "slug", label: "Slug", required: true },
      { name: "domain", label: "Dominio", required: true },
      { name: "business_name", label: "Nombre comercial", required: true },
      { name: "industry", label: "Industria", required: true },
      { name: "language", label: "Idioma", type: "select", default: "es", options: [["es", "es"], ["en", "en"]] },
      { name: "main_city", label: "Ciudad base" },
      { name: "main_state", label: "Estado base" },
      { name: "country", label: "Pais", default: "US" },
      { name: "phone", label: "Telefono" },
      { name: "whatsapp", label: "WhatsApp" },
      { name: "address", label: "Direccion", span: 2 },
      { name: "business_hours_text", label: "Horario", type: "textarea", span: 2 },
      { name: "google_maps_url", label: "Google Maps URL", span: 2 },
      { name: "is_24_hours", label: "24 horas", type: "boolean", default: false },
      { name: "contact_page_url", label: "URL pagina contacto", span: 2 },
      { name: "contact_page_wp_page_id", label: "WP ID contacto", type: "number" },
      { name: "years_experience", label: "Anios experiencia", type: "number" },
      { name: "experience_text", label: "Texto experiencia", type: "textarea", span: 2 },
      { name: "brand_phrase", label: "Frase de marca", span: 2 },
      { name: "brand_phrase_exact", label: "Frase exacta", type: "boolean", default: false },
      { name: "brand_phrase_allow_city_variant", label: "Variante con ciudad", type: "boolean", default: true },
      { name: "brand_phrase_max_uses", label: "Max usos frase", type: "number" },
      { name: "city_links_csv_path", label: "Ruta CSV ciudades", span: 2 },
      { name: "button_style_json", label: "Button style JSON", type: "json", span: 2, default: "{}" },
      { name: "layout_id", label: "Layout ID", type: "number" },
      { name: "layout_branch", label: "Rama del layout", type: "select", default: "cities", options: [["cities", "cities"], ["services", "services"]] },
      { name: "youtube_channel_id", label: "Canal de YouTube", pattern: "UC[A-Za-z0-9_-]+", title: "Usa el ID del canal que empieza por UC, no la URL completa", placeholder: "UCxxxxxxxx" },
      { name: "default_elementor_form_id", label: "Formulario Elementor por defecto" },
      { name: "active", label: "Activo", type: "boolean", default: true },
    ],
  },
  "campaign-services": {
    label: "campaign_services",
    endpoint: "campaign-services",
    title: "Campaign service",
    table: ["id", "campaign_name", "name", "slug", "primary_keyword", "image_policy", "active"],
    fields: [
      { name: "campaign_id", label: "Campana", type: "campaign", required: true },
      { name: "name", label: "Nombre", required: true },
      { name: "slug", label: "Slug", required: true },
      { name: "primary_keyword", label: "Keyword principal", span: 2 },
      { name: "category", label: "Categoria" },
      { name: "brand_phrase", label: "Frase de marca", span: 2 },
      { name: "customer_segment", label: "Segmento", type: "select", default: "unknown", options: [["unknown", "unknown"], ["residential", "residential"], ["commercial", "commercial"], ["both", "both"], ["not_applicable", "not_applicable"]] },
      { name: "language", label: "Idioma", type: "select", default: "es", options: [["es", "es"], ["en", "en"]] },
      { name: "image_policy", label: "Politica imagen", type: "select", default: "general_allowed", options: [["general_allowed", "general_allowed"], ["city_required", "city_required"], ["disabled", "disabled"]] },
      { name: "manual_image_url", label: "Imagen manual URL", span: 2 },
      { name: "image_prompt_hint", label: "Hint prompt imagen", type: "textarea", span: 2 },
      { name: "active", label: "Activo", type: "boolean", default: true },
    ],
  },
  "wordpress-sites": {
    label: "wordpress_sites",
    endpoint: "wordpress-sites",
    title: "WordPress site",
    table: ["id", "campaign_name", "wp_base_url", "username", "credential_ref", "elementor_enabled", "active"],
    fields: [
      { name: "campaign_id", label: "Campana", type: "campaign", required: true },
      { name: "wp_base_url", label: "WP base URL", required: true, span: 2 },
      { name: "wp_api_base_url", label: "WP API base URL", span: 2 },
      { name: "wp_admin_url", label: "WP admin URL", span: 2 },
      { name: "auth_type", label: "Auth type", default: "application_password" },
      { name: "username", label: "Usuario" },
      { name: "credential_ref", label: "Credential ref" },
      { name: "rest_namespace", label: "REST namespace", default: "wp/v2" },
      { name: "elementor_enabled", label: "Elementor", type: "boolean", default: true },
      { name: "yoast_enabled", label: "Yoast", type: "boolean", default: true },
      { name: "custom_elementor_cache_enabled", label: "Cache custom", type: "boolean", default: true },
      { name: "automation_key_ref", label: "Automation key ref" },
      { name: "active", label: "Activo", type: "boolean", default: true },
    ],
  },
  "campaign-prompt-rules": {
    label: "campaign_prompt_rules",
    endpoint: "campaign-prompt-rules",
    title: "Prompt rule",
    table: ["id", "campaign_name", "page_type", "service_name", "active", "rules_json"],
    fields: [
      { name: "campaign_id", label: "Campana", type: "campaign", required: true },
      { name: "page_type", label: "Tipo pagina", type: "select", options: [["", "Todas"], ["home", "home"], ["service", "service"], ["service_city", "service_city"]] },
      { name: "service_id", label: "Service ID", type: "number" },
      { name: "rules_json", label: "Rules JSON", type: "json", span: 2, default: "{}" },
      { name: "active", label: "Activo", type: "boolean", default: true },
    ],
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json().catch(() => ({
      detail: `Respuesta JSON invalida (${response.status})`,
    }))
    : {
      detail: (await response.text()).trim()
        || `Respuesta no JSON (${response.status} ${response.statusText})`,
    };
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
    throw new Error(detail);
  }
  return data;
}

function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.style.background = error ? "#991b1b" : "#0f172a";
  el.style.display = "block";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.style.display = "none"; }, 4500);
}

function campaignLabel(campaign) {
  return campaign.display_name || campaign.name || campaign.business_name || campaign.slug || `Campaña ${campaign.id}`;
}

function campaignQuery() {
  const id = $("#global-campaign").value;
  return id ? `campaign_id=${encodeURIComponent(id)}` : "";
}

function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function buildQuery(values) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) params.set(key, value);
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

function supportPostsPreference() {
  return {
    support_posts: {
      mode: $("#support-posts-mode").value || "auto",
    },
  };
}

async function loadCampaigns() {
  state.campaigns = await api("/seo/campaigns");
  const options = state.campaigns
    .map((campaign) => `<option value="${esc(campaign.id)}">${esc(campaignLabel(campaign))}</option>`)
    .join("");
  const globalCurrent = $("#global-campaign").value;
  const groupCurrent = $("#group-campaign").value;
  $("#global-campaign").innerHTML = `<option value="">Todas las campañas</option>${options}`;
  $("#form-campaign").innerHTML = `<option value="">Selecciona una campaña</option>${options}`;
  $("#group-campaign").innerHTML = `<option value="">Todas las campañas</option>${options}`;
  $("#group-form-campaign").innerHTML = `<option value="">Selecciona una campaña</option>${options}`;
  if (globalCurrent) $("#global-campaign").value = globalCurrent;
  if (groupCurrent) $("#group-campaign").value = groupCurrent;
}

async function loadParentPageOptions(campaignId, selectedId = "") {
  const select = $("#form-parent-page");
  select.innerHTML = `<option value="">Sin página padre</option>`;
  if (!campaignId) return;
  const pages = await api(`/seo/pages${buildQuery({ campaign_id: campaignId, limit: 1000 })}`);
  select.innerHTML += pages
    .filter((page) => Number(page.id) !== Number(state.editingPageId))
    .map((page) => `<option value="${esc(page.id)}">${esc(page.slug || page.url)}${page.wp_page_id ? ` · WP ${esc(page.wp_page_id)}` : ""}</option>`)
    .join("");
  if (selectedId) select.value = String(selectedId);
}

async function loadServices(campaignId) {
  const select = $("#form-service");
  select.innerHTML = `<option value="">Sin servicio</option>`;
  if (!campaignId) return;
  const services = await api(`/seo/services?campaign_id=${encodeURIComponent(campaignId)}`);
  select.innerHTML += services
    .map((service) => `<option value="${esc(service.id)}">${esc(service.name || service.slug || service.id)}</option>`)
    .join("");
}

function renderAdminResourceTabs() {
  $("#admin-resource-tabs").innerHTML = Object.entries(ADMIN_RESOURCES)
    .map(([key, config]) => `<button class="admin-resource-tab ${key === state.admin.resource ? "active" : ""}" data-resource="${esc(key)}">${esc(config.label)}</button>`)
    .join("");
}

async function loadAdminRecords() {
  const config = ADMIN_RESOURCES[state.admin.resource];
  try {
    state.admin.records = await api(`/seo/admin/${config.endpoint}`);
    renderAdminTable();
    resetAdminForm();
    $("#admin-message").innerHTML = "";
  } catch (error) {
    $("#admin-message").innerHTML = `<div class="notice error">${esc(error.message)}</div>`;
  }
}

function renderAdminTable() {
  const config = ADMIN_RESOURCES[state.admin.resource];
  $("#admin-table-head").innerHTML = `<tr>${config.table
    .map((field) => `<th>${esc(field)}</th>`)
    .join("")}<th>Acciones</th></tr>`;
  const body = $("#admin-table-body");
  if (!state.admin.records.length) {
    body.innerHTML = `<tr><td colspan="${config.table.length + 1}" class="admin-empty">No hay registros.</td></tr>`;
    return;
  }
  body.innerHTML = state.admin.records.map((record) => `<tr>
    ${config.table.map((field) => `<td>${renderAdminCell(record[field])}</td>`).join("")}
    <td><div class="inline-actions">
      <button class="button secondary admin-edit" data-id="${esc(record.id)}">Editar</button>
      <button class="button danger admin-delete-row" data-id="${esc(record.id)}">Borrar</button>
    </div></td>
  </tr>`).join("");
}

function renderAdminCell(value) {
  if (value === null || value === undefined || value === "") return `<span class="muted">--</span>`;
  if (typeof value === "boolean") return value ? "Si" : "No";
  if (typeof value === "object") return `<code>${esc(JSON.stringify(value))}</code>`;
  return esc(shorten(value, 90));
}

function resetAdminForm() {
  state.admin.editingId = null;
  renderAdminForm();
}

function renderAdminForm(record = null) {
  const config = ADMIN_RESOURCES[state.admin.resource];
  const editing = Boolean(record);
  state.admin.editingId = editing ? Number(record.id) : null;
  $("#admin-form-title").textContent = editing ? `Editar ${config.title} #${record.id}` : `Nuevo ${config.title}`;
  $("#admin-form-mode").textContent = editing ? "actualizar" : "insertar";
  $("#admin-delete").disabled = !editing;
  $("#admin-fields").innerHTML = config.fields.map((field) => renderAdminField(field, record)).join("");
}

function renderAdminField(field, record) {
  const value = record && record[field.name] !== undefined ? record[field.name] : field.default ?? "";
  const required = field.required ? "required" : "";
  const span = field.span === 2 || field.type === "json" || field.type === "textarea" ? " span-2" : "";
  return `<div class="admin-field${span}">
    <label for="admin-${esc(field.name)}">${esc(field.label)}${field.required ? " *" : ""}</label>
    ${renderAdminInput(field, value, required)}
  </div>`;
}

function renderAdminInput(field, value, required) {
  if (field.type === "boolean") {
    return `<select id="admin-${esc(field.name)}" name="${esc(field.name)}" ${required}>
      <option value="true" ${value === true ? "selected" : ""}>Si</option>
      <option value="false" ${value === false ? "selected" : ""}>No</option>
    </select>`;
  }
  if (field.type === "campaign") {
    return `<select id="admin-${esc(field.name)}" name="${esc(field.name)}" ${required}>
      <option value="">Selecciona una campana</option>
      ${state.campaigns.map((campaign) => `<option value="${esc(campaign.id)}" ${Number(value) === Number(campaign.id) ? "selected" : ""}>${esc(campaignLabel(campaign))}</option>`).join("")}
    </select>`;
  }
  if (field.type === "select") {
    return `<select id="admin-${esc(field.name)}" name="${esc(field.name)}" ${required}>
      ${(field.options || []).map(([optionValue, label]) => `<option value="${esc(optionValue)}" ${String(value ?? "") === String(optionValue) ? "selected" : ""}>${esc(label)}</option>`).join("")}
    </select>`;
  }
  if (field.type === "textarea" || field.type === "json") {
    const text = field.type === "json" && typeof value === "object"
      ? JSON.stringify(value, null, 2)
      : String(value ?? "");
    return `<textarea id="admin-${esc(field.name)}" name="${esc(field.name)}" ${required}>${esc(text)}</textarea>`;
  }
  const type = field.type === "number" ? "number" : "text";
  const pattern = field.pattern ? `pattern="${esc(field.pattern)}"` : "";
  const title = field.title ? `title="${esc(field.title)}"` : "";
  const placeholder = field.placeholder ? `placeholder="${esc(field.placeholder)}"` : "";
  return `<input id="admin-${esc(field.name)}" name="${esc(field.name)}" type="${type}" value="${esc(value ?? "")}" ${pattern} ${title} ${placeholder} ${required}>`;
}

function buildAdminPayload(form) {
  const config = ADMIN_RESOURCES[state.admin.resource];
  const data = new FormData(form);
  const payload = {};
  for (const field of config.fields) {
    const raw = data.get(field.name);
    if (raw === null || raw === "") {
      if (field.required) payload[field.name] = raw;
      if (field.type === "json") {
        payload[field.name] = {};
        continue;
      }
      if (state.admin.editingId && !field.required) payload[field.name] = null;
      continue;
    }
    if (field.type === "number" || field.type === "campaign") {
      payload[field.name] = Number(raw);
    } else if (field.type === "boolean") {
      payload[field.name] = raw === "true";
    } else if (field.type === "json") {
      try {
        payload[field.name] = JSON.parse(raw);
      } catch (error) {
        throw new Error(`JSON invalido en ${field.label}: ${error.message}`);
      }
    } else {
      payload[field.name] = String(raw).trim();
    }
  }
  return payload;
}

async function saveAdminRecord(event) {
  event.preventDefault();
  const config = ADMIN_RESOURCES[state.admin.resource];
  try {
    const payload = buildAdminPayload(event.currentTarget);
    const path = state.admin.editingId
      ? `/seo/admin/${config.endpoint}/${state.admin.editingId}`
      : `/seo/admin/${config.endpoint}`;
    const method = state.admin.editingId ? "PUT" : "POST";
    const result = await api(path, { method, body: JSON.stringify(payload) });
    toast(`Registro ${result.record.id} guardado`);
    await loadCampaigns();
    await loadAdminRecords();
  } catch (error) {
    toast(error.message, true);
  }
}

async function deleteAdminRecord(recordId = state.admin.editingId) {
  if (!recordId) return;
  const config = ADMIN_RESOURCES[state.admin.resource];
  if (!confirm(`Borrar registro ${recordId} de ${config.label}?`)) return;
  try {
    await api(`/seo/admin/${config.endpoint}/${recordId}`, { method: "DELETE" });
    toast(`Registro ${recordId} borrado`);
    await loadCampaigns();
    await loadAdminRecords();
  } catch (error) {
    toast(error.message, true);
  }
}

function editAdminRecord(recordId) {
  const record = state.admin.records.find((item) => Number(item.id) === Number(recordId));
  if (!record) return toast("Registro no encontrado", true);
  renderAdminForm(record);
}

function switchMainView(view) {
  $$(".workspace-tab").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".workspace-view").forEach((panel) => panel.classList.toggle("active", panel.id === `view-${view}`));
  if (view === "admin-data" && !state.admin.records.length) {
    renderAdminResourceTabs();
    loadAdminRecords();
  }
  if (view === "post-groups" && !state.postGroups.loaded) loadPostGroups();
  if (view === "post-monitor") loadPostMonitor();
}

async function loadPostGroups() {
  try {
    state.postGroups.records = await api(`/seo/post-groups${buildQuery({
      campaign_id: $("#group-campaign").value,
      post_status: $("#group-post-status").value,
      state: $("#group-state").value.trim(),
      search: $("#group-search").value.trim(),
      limit: 1000,
    })}`);
    state.postGroups.loaded = true;
    $("#group-message").innerHTML = "";
  } catch (error) {
    $("#group-message").innerHTML = `<div class="notice error">${esc(error.message)}</div>`;
    state.postGroups.records = [];
  }
  renderPostGroups();
}

function renderPostGroups() {
  const body = $("#group-body");
  const groups = state.postGroups.records;
  if (!groups.length) {
    body.innerHTML = `<tr><td colspan="9" class="helper">No hay grupos para los filtros seleccionados.</td></tr>`;
    return;
  }
  body.innerHTML = groups.map((group) => {
    const cities = Array.isArray(group.cities) ? group.cities : [];
    const shown = cities.slice(0, 6)
      .map((city) => `<span class="group-city">${esc(city.city)}</span>`)
      .join("");
    const rest = cities.length > 6 ? `<span class="group-city">+${cities.length - 6}</span>` : "";
    return `<tr class="${Number(state.postGroups.editingId) === Number(group.id) ? "row-active" : ""}">
      <td>${esc(group.id)}</td>
      <td><strong>${esc(group.campaign_name || group.campaign_slug || group.campaign_id)}</strong></td>
      <td><strong>${esc(group.region_name)}</strong><div class="muted">${esc(group.state)}</div></td>
      <td>${esc(group.group_type)}</td>
      <td><div class="group-cities">${shown || `<span class="muted">Sin ciudades</span>`}${rest}</div></td>
      <td>${esc(shorten(group.post_title || "—", 60))}
        <div class="muted">${group.post_url ? `<a href="${esc(group.post_url)}" target="_blank" rel="noopener">Ver post</a>` : esc(group.keyphrase || "")}</div>
      </td>
      <td><span class="pill ${esc(group.post_status)}">${esc(group.post_status)}</span>
        <div class="muted">${esc(group.status)}</div>
      </td>
      <td>${esc(group.priority)}</td>
      <td><div class="inline-actions">
        <button class="button secondary group-edit" data-id="${esc(group.id)}">Editar</button>
        <button class="button danger group-delete-row" data-id="${esc(group.id)}">Borrar</button>
      </div></td>
    </tr>`;
  }).join("");
}

function resetPostGroupForm() {
  const form = $("#group-form");
  form.reset();
  state.postGroups.editingId = null;
  $("#group-form-id").value = "";
  $("#group-form-title").textContent = "Nuevo grupo de posts";
  $("#group-form-mode").textContent = "insertar";
  $("#group-delete").disabled = true;
  $("#group-form-campaign").value = $("#group-campaign").value || "";
  renderPostGroups();
}

function editPostGroup(groupId) {
  const group = state.postGroups.records.find((item) => Number(item.id) === Number(groupId));
  if (!group) return toast("Grupo no encontrado", true);
  const form = $("#group-form");
  state.postGroups.editingId = Number(group.id);
  $("#group-form-id").value = group.id;
  $("#group-form-title").textContent = `Editar grupo ${group.id}`;
  $("#group-form-mode").textContent = "actualizar";
  $("#group-delete").disabled = false;
  [
    "campaign_id", "state", "region_name", "group_type", "priority", "status",
    "post_title", "keyphrase", "slug", "post_category", "post_status", "post_url",
  ].forEach((name) => {
    if (form.elements[name]) form.elements[name].value = group[name] ?? "";
  });
  $("#group-form-cities").value = (group.cities || [])
    .map((city) => `${city.city}, ${city.state}`)
    .join("\n");
  renderPostGroups();
}

function parseGroupCities(raw, defaultState) {
  return String(raw || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [city, cityState] = line.split(",").map((part) => part.trim());
      return { city, state: cityState || defaultState || null };
    })
    .filter((item) => item.city);
}

async function savePostGroup(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const groupState = String(data.get("state") || "").trim().toUpperCase();
  const payload = {
    state: groupState,
    region_name: data.get("region_name"),
    group_type: data.get("group_type"),
    priority: Number(data.get("priority") || 100),
    status: data.get("status"),
    post_title: data.get("post_title") || null,
    keyphrase: data.get("keyphrase") || null,
    slug: data.get("slug") || null,
    post_category: data.get("post_category") || null,
    post_url: data.get("post_url") || null,
    post_status: data.get("post_status"),
    cities: parseGroupCities(data.get("cities"), groupState),
  };
  const groupId = $("#group-form-id").value;
  try {
    if (groupId) {
      await api(`/seo/post-groups/${encodeURIComponent(groupId)}`, {
        method: "PUT",
        body: JSON.stringify({ ...payload, campaign_id: Number(data.get("campaign_id")) }),
      });
      toast(`Grupo ${groupId} actualizado`);
    } else {
      const result = await api("/seo/post-groups", {
        method: "POST",
        body: JSON.stringify({ ...payload, campaign_id: Number(data.get("campaign_id")) }),
      });
      toast(`Grupo ${result.post_group.id} creado`);
    }
    resetPostGroupForm();
    await loadPostGroups();
  } catch (error) {
    toast(`No se pudo guardar el grupo: ${error.message}`, true);
  }
}

async function deletePostGroup(groupId = state.postGroups.editingId) {
  if (!groupId) return;
  if (!confirm(`Se borrará el grupo ${groupId} y sus ciudades. ¿Continuar?`)) return;
  try {
    await api(`/seo/post-groups/${encodeURIComponent(groupId)}`, { method: "DELETE" });
    toast(`Grupo ${groupId} borrado`);
    resetPostGroupForm();
    await loadPostGroups();
  } catch (error) {
    toast(`No se pudo borrar: ${error.message}`, true);
  }
}

async function loadPostMonitor() {
  const alertStatus = $("#post-alert-status").value;
  const alertSeverity = $("#post-alert-severity").value;
  const runStatus = $("#post-run-status").value;
  try {
    const [overview, runs, alerts] = await Promise.all([
      api("/post-monitor/overview"),
      api(`/post-monitor/runs${buildQuery({ status: runStatus, limit: 100 })}`),
      api(`/post-monitor/alerts${buildQuery({
        status: alertStatus,
        severity: alertSeverity,
        limit: 100,
      })}`),
    ]);
    state.postMonitor = { loaded: true, overview, runs, alerts };
    renderPostMonitor();
    $("#post-monitor-message").innerHTML = "";
  } catch (error) {
    $("#post-monitor-message").innerHTML = `<div class="notice error">${esc(error.message)}</div>`;
  }
}

function renderPostMonitor() {
  const overview = state.postMonitor.overview || {};
  const runs = overview.runs || {};
  const alerts = overview.alerts || {};
  const bot = overview.bot;
  $("#post-stat-runs").textContent = runs.last_24h || 0;
  $("#post-stat-success").textContent = runs.succeeded || 0;
  $("#post-stat-failed").textContent = runs.failed || 0;
  $("#post-stat-alerts").textContent = alerts.open || 0;
  $("#post-stat-critical").textContent = alerts.critical || 0;

  if (!bot) {
    $("#post-monitor-status").innerHTML = `<span class="helper">El bot todavía no se ha registrado.</span>`;
  } else {
    const connection = bot.connection_status || "offline";
    $("#post-monitor-status").innerHTML = `
      <div><span class="pill ${connection === "online" ? "success" : "failed"}">${esc(connection)}</span></div>
      <div><span>Bot</span><strong>${esc(bot.name || bot.bot_key)}</strong></div>
      <div><span>Versión</span><strong>${esc(bot.version || "—")}</strong></div>
      <div><span>Estado reportado</span><strong>${esc(bot.reported_status || "—")}</strong></div>
      <div><span>Último heartbeat</span><strong>${esc(formatDate(bot.last_seen_at) || "—")}</strong></div>
      <div><span>Trabajos propios</span><strong>${esc(bot.current_jobs || 0)}</strong></div>
      <div><span>Outbox pendiente</span><strong>${esc(bot.outbox_pending || 0)}</strong></div>`;
  }
  renderPostMonitorAlerts();
  renderPostMonitorRuns();
}

function renderPostMonitorAlerts() {
  const body = $("#post-alerts-body");
  const alerts = state.postMonitor.alerts || [];
  if (!alerts.length) {
    body.innerHTML = `<tr><td colspan="8" class="helper">No hay alertas para los filtros seleccionados.</td></tr>`;
    return;
  }
  body.innerHTML = alerts.map((alert) => {
    const target = alert.target || {};
    const canAcknowledge = alert.status === "open";
    const canResolve = ["open", "acknowledged"].includes(alert.status);
    return `<tr>
      <td>${esc(formatDate(alert.occurred_at))}</td>
      <td><span class="pill severity-${esc(alert.severity)}">${esc(alert.severity)}</span></td>
      <td><strong>${esc(target.title || target.external_id || "—")}</strong><div class="muted">${esc(shorten(target.url, 70))}</div></td>
      <td>${esc(alert.metric)}</td>
      <td><strong>${esc(alert.observed_value)}</strong> ${esc(alert.operator)} ${esc(alert.threshold)} ${esc(alert.unit || "")}</td>
      <td title="${esc(alert.message)}">${esc(shorten(alert.message, 100))}</td>
      <td><span class="pill ${alert.status === "open" ? "failed" : "neutral-soft"}">${esc(alert.status)}</span></td>
      <td><div class="inline-actions">
        ${canAcknowledge ? `<button class="button secondary post-alert-action" data-id="${esc(alert.alert_id)}" data-status="acknowledged">Reconocer</button>` : ""}
        ${canResolve ? `<button class="button primary post-alert-action" data-id="${esc(alert.alert_id)}" data-status="resolved">Resolver</button>` : ""}
      </div></td>
    </tr>`;
  }).join("");
}

function renderPostMonitorRuns() {
  const body = $("#post-runs-body");
  const runs = state.postMonitor.runs || [];
  if (!runs.length) {
    body.innerHTML = `<tr><td colspan="7" class="helper">El bot todavía no ha reportado ejecuciones.</td></tr>`;
    return;
  }
  body.innerHTML = runs.map((run) => {
    const target = run.target || {};
    const error = run.error?.message || "";
    const metrics = Object.keys(run.metrics || {}).length ? JSON.stringify(run.metrics) : "—";
    const duration = run.duration_ms === null || run.duration_ms === undefined
      ? "—"
      : `${(Number(run.duration_ms) / 1000).toFixed(1)} s`;
    return `<tr>
      <td>${esc(formatDate(run.finished_at))}</td>
      <td><span class="pill ${run.status === "succeeded" ? "success" : run.status === "partial" ? "pending" : "failed"}">${esc(run.status)}</span></td>
      <td><strong>${esc(target.title || target.external_id || "—")}</strong><div class="muted">${esc(shorten(target.url, 70))}</div></td>
      <td>${esc(duration)}</td>
      <td title="${esc(run.summary || "")}">${esc(shorten(run.summary, 100) || "—")}</td>
      <td><code title="${esc(metrics)}">${esc(shorten(metrics, 100))}</code></td>
      <td title="${esc(error)}">${esc(shorten(error, 100) || "—")}</td>
    </tr>`;
  }).join("");
}

async function updatePostMonitorAlert(alertId, status) {
  try {
    await api(`/post-monitor/alerts/${encodeURIComponent(alertId)}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    toast(status === "resolved" ? "Alerta resuelta" : "Alerta reconocida");
    await loadPostMonitor();
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadPages() {
  const campaignId = $("#global-campaign").value;
  const pageType = $("#global-page-type").value;
  state.pages = await api(`/seo/pages${buildQuery({
    campaign_id: campaignId,
    page_type: pageType,
    limit: 1000,
  })}`);
  renderPages();
}

function filteredPages() {
  const search = $("#page-search").value.trim().toLowerCase();
  if (!search) return state.pages;
  return state.pages.filter((page) => [
    page.slug,
    page.primary_keyword,
    page.url,
    page.campaign_name,
    page.campaign_slug,
  ].some((value) => String(value || "").toLowerCase().includes(search)));
}

function renderPages() {
  const pages = filteredPages();
  $("#stat-pages").textContent = pages.length;
  syncSelectAllPages(pages);
  const body = $("#pages-body");
  if (!pages.length) {
    body.innerHTML = `<tr><td colspan="9" class="helper">No hay páginas para los filtros seleccionados.</td></tr>`;
    return;
  }
  body.innerHTML = pages.map((page) => {
    const status = page.page_display_status || page.status || "pending";
    const hasActiveExecution = Number(page.active_queue_count || 0) > 0;
    const rank = state.rankPositions[page.id];
    const location = page.target_location_name
      || [page.city, page.parent_city, page.state].filter(Boolean).join(", ")
      || "—";
    return `<tr class="${Number(state.editingPageId) === Number(page.id) ? "row-active" : ""}">
      <td><input class="page-check" type="checkbox" value="${esc(page.id)}" ${state.selectedPageIds.has(Number(page.id)) ? "checked" : ""}></td>
      <td>${esc(page.id)}</td>
      <td><strong>${esc(page.campaign_name || page.campaign_slug || page.campaign_id)}</strong></td>
      <td><strong>${esc(page.slug)}</strong><div class="muted">${esc(page.url)}</div></td>
      <td>${esc(page.primary_keyword || "")}<div class="muted">${esc(page.service_name || "")}</div></td>
      <td>${esc(page.page_type || "")}</td>
      <td>${esc(location)}</td>
      <td><span class="pill ${esc(status)}">${esc(status)}</span>
        <div class="muted">${Number(page.failed_count || 0)} fallos · ${Number(page.active_queue_count || 0)} activas</div>
      </td>
      <td><div class="inline-actions">
        ${renderRankPosition(rank)}
        <button class="button position check-position" data-id="${esc(page.id)}"
          ${rank?.status === "loading" ? "disabled" : ""}
          title="Consultar la posición orgánica actual">
          ${rank?.status === "loading" ? "Consultando…" : rank?.status === "success" ? "Actualizar" : "Consultar posición"}
        </button>
        <button class="button secondary edit-page" data-id="${esc(page.id)}">Editar</button>
        <button class="button secondary run-page" data-id="${esc(page.id)}"
          ${hasActiveExecution ? 'disabled title="Esta página ya tiene una ejecución en cola o en curso"' : ""}>
          ${hasActiveExecution ? "Ejecución activa" : "Ejecutar"}</button>
        ${page.last_queue_id ? `<button class="button ghost inspect-execution" data-id="${esc(page.last_queue_id)}">Última ejecución</button>` : ""}
      </div></td>
    </tr>`;
  }).join("");
}

function renderRankPosition(rank) {
  if (!rank) return "";
  if (rank.status === "loading") {
    return `<span class="rank-position loading">Consultando…</span>`;
  }
  if (rank.status === "error") {
    return `<span class="rank-position error" title="${esc(rank.message)}">Error</span>`;
  }
  if (rank.position === null || rank.position === undefined) {
    return `<span class="rank-position outside">Fuera del top ${esc(rank.maxResults)}</span>`;
  }
  return `<span class="rank-position found">Posición: ${esc(rank.position)}</span>`;
}

function selectedPageIds() {
  return [...state.selectedPageIds];
}

function syncSelectAllPages(pages = filteredPages()) {
  const selectAll = $("#select-all-pages");
  if (!selectAll) return;
  const visibleIds = pages.map((page) => Number(page.id));
  const selectedVisible = visibleIds.filter((id) => state.selectedPageIds.has(id));
  selectAll.checked = visibleIds.length > 0 && selectedVisible.length === visibleIds.length;
  selectAll.indeterminate = selectedVisible.length > 0 && selectedVisible.length < visibleIds.length;
}

function defaultScheduleDate() {
  return new Date().toISOString().slice(0, 10);
}

async function checkRankPosition(pageId) {
  if (!confirm("Esta consulta consume un crédito del proveedor de búsqueda. ¿Continuar?")) return;
  state.rankPositions[pageId] = { status: "loading" };
  renderPages();
  try {
    const result = await api(`/seo/pages/${encodeURIComponent(pageId)}/rank-position`, {
      method: "POST",
      body: "{}",
    });
    state.rankPositions[pageId] = {
      status: "success",
      position: result.position,
      maxResults: result.max_results,
      checkedAt: result.checked_at,
    };
    toast(result.position === null
      ? `La página no aparece en el top ${result.max_results}`
      : `Posición orgánica actual: ${result.position}`);
  } catch (error) {
    state.rankPositions[pageId] = { status: "error", message: error.message };
    toast(`No se pudo consultar la posición: ${error.message}`, true);
  }
  renderPages();
}

async function loadQueue() {
  const campaignId = $("#global-campaign").value;
  const pageType = $("#global-page-type").value;
  const view = $("#queue-view").value;
  state.queue = await api(`/seo/execution-queue${buildQuery({
    campaign_id: campaignId,
    page_type: pageType,
    view,
    limit: 500,
  })}`);
  renderQueue();
}

function renderQueue() {
  const body = $("#queue-body");
  const counts = { queued: 0, running: 0, success: 0, failed: 0 };
  state.queue.forEach((item) => {
    if (Object.hasOwn(counts, item.status)) counts[item.status] += 1;
  });
  $("#stat-queued").textContent = counts.queued;
  $("#stat-running").textContent = counts.running;
  $("#stat-success").textContent = counts.success;
  $("#stat-failed").textContent = counts.failed;

  if (!state.queue.length) {
    body.innerHTML = `<tr><td colspan="11" class="helper">No hay ejecuciones.</td></tr>`;
    return;
  }
  body.innerHTML = state.queue.map((item) => {
    const canCancel = item.status === "queued";
    const canRetry = ["failed", "cancelled"].includes(item.status);
    return `<tr>
      <td>${esc(item.id)}</td>
      <td>${esc(item.campaign_name || item.campaign_slug || item.campaign_id)}</td>
      <td><strong>${esc(item.page_slug || item.campaign_page_id)}</strong><div class="muted">${esc(item.primary_keyword || "")}</div></td>
      <td>${esc(item.trigger_type || "")}</td>
      <td>${esc(item.scheduled_for || "")}</td>
      <td><span class="pill ${esc(item.status)}">${esc(item.status)}</span></td>
      <td>${esc(item.result_status || "—")}${item.status === "success" && item.error_message ? '<div><span class="pill severity-warning">Advertencia</span></div>' : ""}</td>
      <td>${esc(item.attempts || 0)}/${esc(item.max_attempts || 1)}</td>
      <td><div class="muted">${esc(formatDate(item.started_at))}</div><div class="muted">${esc(formatDate(item.finished_at))}</div></td>
      <td title="${esc(item.error_message || "")}">${esc(shorten(item.error_message, 90))}</td>
      <td><div class="inline-actions">
        <button class="button secondary inspect-execution" data-id="${esc(item.id)}">Resultados</button>
        ${canCancel ? `<button class="button danger cancel-execution" data-id="${esc(item.id)}">Cancelar</button>` : ""}
        ${canRetry ? `<button class="button secondary retry-execution" data-id="${esc(item.id)}">Reintentar</button>` : ""}
      </div></td>
    </tr>`;
  }).join("");
}

function shorten(value, max) {
  const text = String(value || "");
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function formatDate(value) {
  return value ? String(value).replace("T", " ").slice(0, 19) : "";
}

async function savePage(event) {
  event.preventDefault();
  const pageForm = event.currentTarget;
  const form = new FormData(pageForm);
  const nullableBoolean = (name) => {
    const value = form.get(name);
    return value === "" ? null : value === "true";
  };
  const text = (name) => form.get(name) || null;
  const keywords = String(form.get("secondary_keywords") || "")
    .split(/\n|,/)
    .map((value) => value.trim())
    .filter(Boolean);
  const payload = {
    service_id: form.get("service_id") ? Number(form.get("service_id")) : null,
    wp_page_id: form.get("wp_page_id") ? Number(form.get("wp_page_id")) : null,
    url: form.get("url"),
    slug: text("slug"),
    page_type: form.get("page_type"),
    language: form.get("language"),
    primary_keyword: form.get("primary_keyword"),
    secondary_keywords: keywords,
    service_scope: form.get("service_scope"),
    customer_segment: form.get("customer_segment"),
    city: text("city"),
    state: text("state"),
    country: form.get("country") || "US",
    postal_code: text("postal_code"),
    target_location_name: text("target_location_name"),
    target_google_maps_url: text("target_google_maps_url"),
    location_type: form.get("location_type"),
    parent_city: text("parent_city"),
    delivery_mode: form.get("delivery_mode"),
    allows_remote: nullableBoolean("allows_remote"),
    allows_onsite: nullableBoolean("allows_onsite"),
    physical_visit_required: nullableBoolean("physical_visit_required"),
    page_template: form.get("page_template") || "elementor_header_footer",
    layout_id: form.get("layout_id") ? Number(form.get("layout_id")) : null,
    layout_branch: text("layout_branch"),
    parent_campaign_page_id: form.get("parent_campaign_page_id")
      ? Number(form.get("parent_campaign_page_id"))
      : null,
    parent_slug: text("parent_slug"),
    parent_required: form.get("parent_required") === "true",
    elementor_form_id: text("elementor_form_id"),
    youtube_channel_id: text("youtube_channel_id"),
    allow_publish: form.get("allow_publish") === "true",
    status: form.get("status"),
  };
  const pageId = $("#page-form-id").value;
  try {
    if (pageId) {
      await api(`/seo/pages/${encodeURIComponent(pageId)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      toast(`Página ${pageId} actualizada`);
    } else {
      const result = await api("/seo/pages", {
        method: "POST",
        body: JSON.stringify({ ...payload, campaign_id: Number(form.get("campaign_id")) }),
      });
      toast(`Página ${result.page.id} registrada`);
    }
    resetPageForm();
    await loadPages();
  } catch (error) {
    toast(`No se pudo guardar: ${error.message}`, true);
  }
}

function resetPageForm() {
  const form = $("#page-form");
  form.reset();
  state.editingPageId = null;
  $("#page-form-id").value = "";
  $("#page-form-icon").textContent = "➕";
  $("#page-form-title").textContent = "Agregar página a campaign_pages";
  $("#page-form-mode").textContent = "* requerido";
  $("#page-form-submit").textContent = "Guardar página →";
  $("#page-cancel-edit").hidden = true;
  $("#form-campaign").disabled = false;
  $("#form-parent-page").innerHTML = `<option value="">Sin página padre</option>`;
  syncToggleButtons();
  updateLocationFields();
  renderPages();
}

async function editPage(pageId) {
  const page = state.pages.find((item) => Number(item.id) === Number(pageId));
  if (!page) return toast("Página no encontrada", true);
  const form = $("#page-form");
  state.editingPageId = Number(page.id);
  $("#page-form-id").value = page.id;
  $("#page-form-icon").textContent = "✏️";
  $("#page-form-title").textContent = `Editar página ${page.id}`;
  $("#page-form-mode").textContent = "actualizar";
  $("#page-form-submit").textContent = "Actualizar página →";
  $("#page-cancel-edit").hidden = false;

  $("#form-campaign").value = page.campaign_id ?? "";
  $("#form-campaign").disabled = true;
  await loadServices(page.campaign_id);
  [
    "service_id", "wp_page_id", "url", "slug", "page_type", "language", "status",
    "primary_keyword", "service_scope", "customer_segment", "city", "state",
    "country", "postal_code", "target_location_name", "target_google_maps_url",
    "location_type", "parent_city", "delivery_mode", "page_template",
    "layout_id", "layout_branch", "parent_slug", "elementor_form_id",
    "youtube_channel_id",
  ].forEach((name) => {
    if (form.elements[name]) form.elements[name].value = page[name] ?? "";
  });
  form.elements.secondary_keywords.value = (page.secondary_keywords || []).join("\n");
  [
    ["form-allows-remote", page.allows_remote],
    ["form-allows-onsite", page.allows_onsite],
    ["form-physical", page.physical_visit_required],
    ["form-allow-publish", page.allow_publish],
    ["form-parent-required", page.parent_required],
  ].forEach(([id, value]) => {
    document.getElementById(id).value = value === null || value === undefined ? "" : String(value);
  });
  syncToggleButtons();
  updateLocationFields();
  await loadParentPageOptions(page.campaign_id, page.parent_campaign_page_id || "");
  renderPages();
  form.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function scheduleSelected() {
  const ids = selectedPageIds();
  if (!ids.length) return toast("Selecciona al menos una página", true);
  try {
    const result = await api("/seo/execution-queue/schedule", {
      method: "POST",
      body: JSON.stringify({
        campaign_page_ids: ids,
        scheduled_for: $("#schedule-date").value || defaultScheduleDate(),
        notes: $("#schedule-notes").value,
        ...supportPostsPreference(),
      }),
    });
    result.inserted.forEach((item) => state.selectedPageIds.delete(Number(item.campaign_page_id)));
    toast(
      `En cola: ${result.inserted_count}. Omitidas: ${result.skipped.length}`,
      Boolean(result.error_count),
    );
    await Promise.all([loadPages(), loadQueue()]);
  } catch (error) {
    toast(error.message, true);
  }
}

async function runPage(pageId) {
  if (!confirm("Esta acción inicia la auditoría SEO. ¿Continuar?")) return;
  try {
    const result = await api("/seo/execution-queue/run-now", {
      method: "POST",
      body: JSON.stringify({
        campaign_page_id: Number(pageId),
        ...supportPostsPreference(),
      }),
    });
    if (result.ok === false) return toast(result.error, true);
    toast(`Ejecución ${result.queue.id} creada. Despacho: ${result.dispatch_status}`);
    await Promise.all([loadPages(), loadQueue()]);
  } catch (error) {
    toast(error.message, true);
  }
}

async function queueAction(action, queueId) {
  if (!confirm(`¿Confirmas ${action} para la ejecución ${queueId}?`)) return;
  try {
    const result = await api(`/seo/execution-queue/${queueId}/${action}`, {
      method: "POST",
      body: JSON.stringify(action === "retry" ? supportPostsPreference() : {}),
    });
    toast(action === "retry"
      ? `Reintento creado: ${result.queue.id}`
      : `Ejecución ${queueId} cancelada`);
    await Promise.all([loadPages(), loadQueue()]);
  } catch (error) {
    toast(error.message, true);
  }
}

async function runDaily() {
  if (!confirm("Se despacharán ejecuciones programadas que ya estén vencidas. ¿Continuar?")) return;
  try {
    const result = await api("/seo/execution-queue/run-daily-now", {
      method: "POST",
      body: JSON.stringify({
        confirm: true,
        daily_limit: Number($("#daily-limit").value || 10),
        ...supportPostsPreference(),
      }),
    });
    toast(
      `Daily: ${result.dispatched_count || 0} enviadas, ` +
      `${result.pending_bot_count || 0} esperando bot, ` +
      `${result.already_started_count || 0} ya iniciadas, ` +
      `${result.error_count || 0} errores`,
      Boolean(result.error_count),
    );
    $("#queue-message").innerHTML = (result.errors || []).length
      ? `<div class="notice error">${result.errors.map((item) =>
        `#${esc(item.queue_execution_id)}: ${esc(item.error)}`).join("<br>")}</div>`
      : "";
    await loadQueue();
  } catch (error) {
    $("#queue-message").innerHTML = `<div class="notice error">${esc(error.message)}</div>`;
    toast(error.message, true);
  }
}

async function openExecution(queueId) {
  state.currentQueueId = Number(queueId);
  state.currentArtifact = null;
  switchTab("artifacts");
  $("#execution-title").textContent = `Ejecución #${queueId}`;
  $("#artifact-list").innerHTML = `<p class="helper">Cargando archivos…</p>`;
  $("#artifact-json").textContent = "No hay un artefacto seleccionado.";
  $("#artifact-rendered").innerHTML = `<p class="helper">No hay un artefacto seleccionado.</p>`;
  $("#execution-log").textContent = "Cargando…";
  $("#execution-dialog").showModal();
  try {
    await api(`/page-executions/${queueId}/sync`, { method: "POST" });
    const [execution, artifacts] = await Promise.all([
      api(`/page-executions/${queueId}`),
      api(`/page-executions/${queueId}/artifacts`),
    ]);
    $("#execution-meta").textContent = `${execution.campaign_name} · ${execution.page_slug} · ${execution.status || ""}`;
    $("#execution-summary").innerHTML = renderDynamicJson(execution);
    await renderArtifacts(artifacts.items || []);
    await loadExecutionLog();
  } catch (error) {
    $("#artifact-list").innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
    $("#artifact-rendered").innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
    $("#execution-summary").innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
  }
}

async function renderArtifacts(items) {
  const list = $("#artifact-list");
  if (!items.length) {
    list.innerHTML = `<p class="helper">Esta ejecución todavía no tiene archivos JSON guardados.</p>`;
    $("#artifact-rendered").innerHTML = `<p class="helper">Esta ejecución todavía no tiene documentos guardados en MongoDB.</p>`;
    return;
  }
  list.innerHTML = items.map((item) => `<button class="artifact-item" data-filename="${esc(item.filename)}">
    <strong>${esc(item.filename)}</strong>
    <div class="muted">${Number(item.size_bytes || 0).toLocaleString()} bytes · ${esc(formatDate(item.updated_at))}</div>
  </button>`).join("");
  const firstButton = list.querySelector(".artifact-item");
  if (firstButton) await loadArtifact(firstButton.dataset.filename, firstButton);
}

async function loadArtifact(filename, button) {
  try {
    $$(".artifact-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    const artifact = await api(`/page-executions/${state.currentQueueId}/artifacts/${encodeURIComponent(filename)}`);
    state.currentArtifact = artifact.payload;
    $("#artifact-title").textContent = filename;
    $("#artifact-json").textContent = JSON.stringify(artifact.payload, null, 2);
    $("#artifact-rendered").innerHTML = renderDynamicJson(artifact.payload);
  } catch (error) {
    toast(error.message, true);
  }
}

function humanizeKey(key) {
  return String(key || "")
    .replaceAll("_", " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function renderDynamicJson(value) {
  if (isPageSpeedResult(value)) {
    return renderPageSpeedResult(value);
  }
  if (value === null || value === undefined) {
    return `<span class="dynamic-null">Sin valor</span>`;
  }
  if (Array.isArray(value)) {
    if (!value.length) return `<span class="dynamic-null">Lista vacía</span>`;
    const primitive = value.every((item) => item === null || typeof item !== "object");
    if (primitive) {
      return `<div class="dynamic-chips">${value
        .map((item) => `<span class="dynamic-chip">${esc(item ?? "null")}</span>`)
        .join("")}</div>`;
    }
    return value.map((item, index) => `<details class="dynamic-card" open>
      <summary>Elemento ${index + 1}</summary>
      ${renderDynamicJson(item)}
    </details>`).join("");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) return `<span class="dynamic-null">Objeto vacío</span>`;
    return entries.map(([key, item]) => {
      const nested = item !== null && typeof item === "object";
      if (nested) {
        return `<details class="dynamic-card" open>
          <summary>${esc(humanizeKey(key))}</summary>
          ${renderDynamicJson(item)}
        </details>`;
      }
      return `<div class="dynamic-row">
        <div class="dynamic-key">${esc(humanizeKey(key))}</div>
        <div class="dynamic-value">${renderDynamicJson(item)}</div>
      </div>`;
    }).join("");
  }
  if (typeof value === "boolean") {
    return `<span class="pill ${value ? "success" : "failed"}">${value ? "Sí" : "No"}</span>`;
  }
  return `<span>${esc(value)}</span>`;
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isPageSpeedResult(value) {
  return getPageSpeedData(value) !== null;
}

function getPageSpeedData(value) {
  if (!isPlainObject(value)) return null;
  const candidates = [
    value,
    value.payload,
    value.result,
    value.pagespeed,
    value.page_speed,
    value.data,
  ].filter(isPlainObject);
  const core = candidates.find((candidate) => (
    hasPageSpeedProfiles(candidate) && hasPageSpeedSignals(candidate, value)
  ));
  if (!core) return null;
  if (core === value) return value;
  const metadata = Object.fromEntries(Object.entries(value)
    .filter(([key]) => !["payload", "result", "pagespeed", "page_speed", "data", "mobile", "desktop"].includes(key)));
  return { ...core, ...metadata };
}

function hasPageSpeedProfiles(value) {
  return isPlainObject(value)
    && isPlainObject(value.mobile)
    && isPlainObject(value.desktop);
}

function hasPageSpeedSignals(core, wrapper) {
  const schema = String(core.schema_version || wrapper.schema_version || "");
  return core.stage === "pagespeed"
    || wrapper.stage === "pagespeed"
    || schema.includes("pagespeed")
    || "can_index" in core.mobile
    || "can_index" in core.desktop
    || "lighthouseResult" in core.mobile
    || "lighthouseResult" in core.desktop
    || "lighthouse_result" in core.mobile
    || "lighthouse_result" in core.desktop
    || "performance_score" in core.mobile
    || "performance_score" in core.desktop;
}

function renderPageSpeedResult(result) {
  const data = getPageSpeedData(result) || result;
  const profiles = ["mobile", "desktop"].map((profile) => ({
    key: profile,
    label: profile === "mobile" ? "Mobile" : "Desktop",
    data: data[profile] || {},
  }));
  const scores = profiles
    .map((profile) => getPageSpeedScore(profile.data))
    .filter((score) => Number.isFinite(score));
  const averageScore = scores.length
    ? Math.round(scores.reduce((total, score) => total + score, 0) / scores.length)
    : null;
  const canIndex = profiles.every((profile) => profile.data.can_index === true);
  const rejected = profiles
    .filter((profile) => profile.data.can_index === false)
    .map((profile) => profile.label)
    .join(", ");
  const statusClass = rejected ? "blocked" : canIndex ? "ok" : "unknown";
  const pageUrl = data.url || data.page_url || data.final_url || "Resultado de auditoria";
  const summaryText = typeof data.summary === "string" ? data.summary : "";
  const extra = Object.fromEntries(Object.entries(data)
    .filter(([key]) => ![
      "mobile",
      "desktop",
      "url",
      "page_url",
      "final_url",
      "summary",
      "stage",
      "schema_version",
      "execution_id",
      "flow_id",
      "campaign_page_id",
      "queue_execution_id",
      "orchestrator_status",
      "orchestrator_error",
    ].includes(key)));

  return `<section class="pagespeed-report ${statusClass}">
    <div class="pagespeed-hero ${statusClass}">
      <div class="pagespeed-hero-copy">
        <span class="json-kicker">PAGESPEED</span>
        <h3>${esc(pageUrl)}</h3>
        ${summaryText ? `<p>${esc(summaryText)}</p>` : ""}
        ${data.orchestrator_error ? `<p class="pagespeed-warning">${esc(data.orchestrator_error)}</p>` : ""}
      </div>
      <div class="pagespeed-verdict">
        ${renderScoreGauge(averageScore, "large")}
        <span class="pagespeed-status ${statusClass}">
          ${canIndex ? "Indexacion permitida" : rejected ? `Indexacion bloqueada: ${esc(rejected)}` : "Decision pendiente"}
        </span>
      </div>
    </div>
    ${renderPageSpeedHighlights(profiles, averageScore, data)}
    <div class="pagespeed-profiles">
      ${profiles.map(renderPageSpeedProfile).join("")}
    </div>
    ${Object.keys(extra).length ? `<details class="dynamic-card pagespeed-extra">
      <summary>Datos adicionales</summary>
      ${renderDynamicJson(extra)}
    </details>` : ""}
  </section>`;
}

function renderPageSpeedHighlights(profiles, averageScore, data) {
  const blocked = profiles.some((profile) => profile.data.can_index === false);
  const statusTone = blocked || data.orchestrator_status === "failed" ? "bad"
    : data.orchestrator_status === "succeeded" ? "good"
      : "unknown";
  const highlights = [
    ["Score promedio", Number.isFinite(averageScore) ? averageScore : "--", scoreTone(averageScore)],
    ["Mobile", scoreLabel(getPageSpeedScore(profiles[0].data)), scoreTone(getPageSpeedScore(profiles[0].data))],
    ["Desktop", scoreLabel(getPageSpeedScore(profiles[1].data)), scoreTone(getPageSpeedScore(profiles[1].data))],
    ["Estado", data.orchestrator_status || "recibido", statusTone],
  ];
  return `<div class="pagespeed-highlights">${highlights.map(([label, value, tone]) => `
    <div class="pagespeed-highlight ${tone}">
      <span>${esc(label)}</span>
      <strong>${esc(value)}</strong>
    </div>`).join("")}</div>`;
}

function renderPageSpeedProfile(profile) {
  const score = getPageSpeedScore(profile.data);
  const statusClass = profile.data.can_index === true ? "ok"
    : profile.data.can_index === false ? "blocked"
      : "unknown";
  return `<article class="pagespeed-profile ${statusClass}">
    <div class="pagespeed-profile-head">
      <div>
        <span class="pagespeed-device">${esc(profile.label)}</span>
        <span class="pagespeed-index ${statusClass}">${renderCanIndexText(profile.data.can_index)}</span>
      </div>
      ${renderScoreGauge(score)}
    </div>
    ${renderPageSpeedMetrics(profile.data)}
    ${renderPageSpeedOpportunities(profile.data)}
    ${renderProfileNotes(profile.data)}
  </article>`;
}

function renderCanIndexText(value) {
  if (value === true) return "Puede indexar";
  if (value === false) return "No indexar";
  return "Sin decision";
}

function getPageSpeedScore(profile) {
  const candidates = [
    profile.performance_score,
    profile.performanceScore,
    profile.score,
    profile.performance,
    profile.performance?.score,
    profile.scores?.performance,
    profile.scores?.performance_score,
    profile.category_scores?.performance,
    profile.categories?.performance?.score,
    profile.metrics?.performance_score,
    profile.metrics?.performanceScore,
    profile.metrics?.performance,
    profile.lighthouseResult?.categories?.performance?.score,
    profile.lighthouse_result?.categories?.performance?.score,
    profile.lighthouse?.categories?.performance?.score,
    profile.result?.lighthouseResult?.categories?.performance?.score,
    profile.data?.lighthouseResult?.categories?.performance?.score,
  ];
  const raw = candidates.find((item) => (
    item !== null
    && item !== ""
    && typeof item !== "object"
    && Number.isFinite(Number(item))
  ));
  if (raw === undefined) return null;
  const numeric = Number(raw);
  return Math.round(numeric <= 1 ? numeric * 100 : numeric);
}

function renderScoreGauge(score, variant = "") {
  if (!Number.isFinite(score)) {
    return `<div class="pagespeed-score ${variant} empty"><strong>--</strong><span>Score</span></div>`;
  }
  const clamped = Math.max(0, Math.min(100, score));
  const tone = scoreTone(clamped);
  return `<div class="pagespeed-score ${variant} ${tone}" style="--score:${clamped}">
    <strong>${clamped}</strong><span>Score</span>
  </div>`;
}

function scoreTone(score) {
  if (!Number.isFinite(score)) return "unknown";
  return score >= 90 ? "good" : score >= 50 ? "warn" : "bad";
}

function scoreLabel(score) {
  return Number.isFinite(score) ? String(score) : "--";
}

function renderPageSpeedMetrics(profile) {
  const metrics = [
    ["FCP", firstDefined([
      profile.fcp,
      profile.first_contentful_paint,
      profile.metrics?.fcp,
      profile.metrics?.first_contentful_paint,
      auditDisplay(profile, "first-contentful-paint"),
    ])],
    ["LCP", firstDefined([
      profile.lcp,
      profile.largest_contentful_paint,
      profile.metrics?.lcp,
      profile.metrics?.largest_contentful_paint,
      auditDisplay(profile, "largest-contentful-paint"),
    ])],
    ["CLS", firstDefined([
      profile.cls,
      profile.cumulative_layout_shift,
      profile.metrics?.cls,
      profile.metrics?.cumulative_layout_shift,
      auditDisplay(profile, "cumulative-layout-shift"),
    ])],
    ["TBT", firstDefined([
      profile.tbt,
      profile.total_blocking_time,
      profile.metrics?.tbt,
      profile.metrics?.total_blocking_time,
      auditDisplay(profile, "total-blocking-time"),
    ])],
    ["SI", firstDefined([
      profile.speed_index,
      profile.metrics?.speed_index,
      auditDisplay(profile, "speed-index"),
    ])],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");

  if (!metrics.length) {
    return `<p class="pagespeed-empty">Sin metricas numericas reportadas.</p>`;
  }
  return `<div class="pagespeed-metrics">${metrics.map(([label, value]) => `
    <div class="pagespeed-metric ${metricTone(label, value)}">
      <span>${esc(label)}</span>
      <strong>${esc(formatMetricValue(value))}</strong>
    </div>`).join("")}</div>`;
}

function auditDisplay(profile, key) {
  const audits = profile.audits
    || profile.lighthouseResult?.audits
    || profile.lighthouse_result?.audits;
  return audits?.[key]?.displayValue ?? audits?.[key]?.numericValue;
}

function firstDefined(values) {
  return values.find((value) => value !== undefined && value !== null && value !== "");
}

function formatMetricValue(value) {
  if (typeof value === "number") {
    if (value > 1000) return `${(value / 1000).toFixed(1)} s`;
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return value;
}

function metricTone(label, value) {
  const numeric = metricNumber(value);
  if (!Number.isFinite(numeric)) return "unknown";
  if (label === "CLS") {
    return numeric <= 0.1 ? "good" : numeric <= 0.25 ? "warn" : "bad";
  }
  if (label === "TBT") {
    const ms = numeric < 10 ? numeric * 1000 : numeric;
    return ms <= 200 ? "good" : ms <= 600 ? "warn" : "bad";
  }
  const seconds = numeric > 100 ? numeric / 1000 : numeric;
  const thresholds = {
    FCP: [1.8, 3],
    LCP: [2.5, 4],
    SI: [3.4, 5.8],
  }[label] || [2.5, 4];
  return seconds <= thresholds[0] ? "good" : seconds <= thresholds[1] ? "warn" : "bad";
}

function metricNumber(value) {
  if (typeof value === "number") return value;
  if (typeof value !== "string") return NaN;
  const match = value.replace(",", ".").match(/[\d.]+/);
  return match ? Number(match[0]) : NaN;
}

function renderPageSpeedOpportunities(profile) {
  const opportunities = collectOpportunities(profile).slice(0, 5);
  if (!opportunities.length) return "";
  return `<div class="pagespeed-opportunities">
    <span class="pagespeed-section-title">Oportunidades principales</span>
    ${opportunities.map((item) => `<div class="pagespeed-opportunity">
      <strong>${esc(item.title)}</strong>
      ${item.saving ? `<span>${esc(item.saving)}</span>` : ""}
    </div>`).join("")}
  </div>`;
}

function collectOpportunities(profile) {
  if (Array.isArray(profile.opportunities)) {
    return profile.opportunities.map((item) => ({
      title: item.title || item.id || item.name || "Oportunidad",
      saving: item.displayValue || item.saving || item.estimated_savings || "",
      rank: Number(item.numericValue || item.wastedMs || item.wastedBytes || 0),
    })).sort((a, b) => b.rank - a.rank);
  }
  const audits = profile.audits
    || profile.lighthouseResult?.audits
    || profile.lighthouse_result?.audits
    || {};
  return Object.entries(audits)
    .filter(([, audit]) => isPlainObject(audit)
      && (audit.details?.type === "opportunity"
        || (audit.score !== null && audit.score !== undefined && Number(audit.score) < 1))
      && audit.title)
    .map(([, audit]) => ({
      title: audit.title,
      saving: audit.displayValue || "",
      rank: Number(audit.numericValue || audit.details?.overallSavingsMs || audit.details?.overallSavingsBytes || 0),
    }))
    .sort((a, b) => b.rank - a.rank);
}

function renderProfileNotes(profile) {
  const notes = [
    profile.reason,
    profile.indexing_reason,
    profile.summary,
    profile.error,
  ].filter(Boolean);
  if (!notes.length) return "";
  return `<div class="pagespeed-notes">${notes
    .map((note) => `<p>${esc(note)}</p>`)
    .join("")}</div>`;
}

function syncToggleButtons() {
  $$(".toggle-option").forEach((button) => {
    const input = document.getElementById(button.dataset.target);
    const active = input && input.value === button.dataset.value;
    button.classList.toggle("active-yes", active && button.dataset.value === "true");
    button.classList.toggle("active-no", active && button.dataset.value === "false");
    button.classList.toggle("active-null", active && button.dataset.value === "");
  });
}

function updateLocationFields() {
  const neighborhood = $("#form-location-type").value === "neighborhood";
  $("#form-parent-city").required = neighborhood;
  $("#form-parent-city-wrap").classList.toggle("hidden", !neighborhood);
}

async function loadExecutionLog() {
  if (!state.currentQueueId) return;
  try {
    const log = await api(`/page-executions/${state.currentQueueId}/log`);
    $("#execution-log").textContent = formatExecutionLog(log);
  } catch (error) {
    $("#execution-log").textContent = `Log no disponible: ${error.message}`;
  }
}

function formatExecutionLog(log) {
  if (Array.isArray(log.entries)) {
    if (!log.entries.length) return "No hay entradas de log acumuladas.";
    return log.entries.map((entry, index) => {
      const when = formatDate(entry.created_at || log.updated_at) || "sin fecha";
      const execution = entry.queue_execution_id ? `ejecucion #${entry.queue_execution_id}` : "ejecucion";
      return `[${index + 1}] ${when} · ${execution}\n${formatLogPayload(entry.payload)}`;
    }).join("\n\n");
  }
  return typeof log.payload === "string"
    ? log.payload
    : JSON.stringify(log, null, 2);
}

function formatLogPayload(payload) {
  if (typeof payload === "string") return payload;
  if (Array.isArray(payload)) {
    return payload.map((item) => formatLogPayload(item)).join("\n");
  }
  if (payload && typeof payload === "object") {
    const text = payload.message || payload.msg || payload.line || payload.log;
    if (text) return String(text);
    return JSON.stringify(payload, null, 2);
  }
  return String(payload ?? "");
}

async function processXlsx(dryRun) {
  const file = $("#xlsx-file").files[0];
  if (!file) return toast("Selecciona un archivo .xlsx", true);
  const base64 = await fileToBase64(file);
  try {
    const result = await api("/seo/pages/import-xlsx", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, xlsx_base64: base64, dry_run: dryRun }),
    });
    $("#xlsx-result").innerHTML = `<div class="notice ${result.error_count ? "error" : ""}">
      Filas: ${esc(result.total_rows)} · Nuevas: ${esc(result.created_pages_count)}
      · Actualizadas: ${esc(result.updated_pages_count)} · Programadas: ${esc(result.inserted_queue_count)}
      · Omitidas: ${esc(result.skipped_count)} · Errores: ${esc(result.error_count)}
    </div>`;
    if (!dryRun) await Promise.all([loadPages(), loadQueue()]);
  } catch (error) {
    $("#xlsx-result").innerHTML = `<div class="notice error">${esc(error.message)}</div>`;
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(new Error("No se pudo leer el archivo"));
    reader.readAsDataURL(file);
  });
}

function switchTab(tab) {
  $$(".tab").forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tab}`));
}

async function loadAll() {
  try {
    $("#api-status").textContent = "API conectada";
    await loadCampaigns();
    renderAdminResourceTabs();
    renderAdminForm();
    await Promise.all([loadPages(), loadQueue()]);
    $("#api-status").className = "pill success";
  } catch (error) {
    $("#api-status").textContent = "API no disponible";
    $("#api-status").className = "pill failed";
    toast(error.message, true);
  }
}

document.addEventListener("click", (event) => {
  const pageCheckbox = event.target.closest(".page-check");
  if (pageCheckbox) {
    const pageId = Number(pageCheckbox.value);
    if (pageCheckbox.checked) {
      state.selectedPageIds.add(pageId);
    } else {
      state.selectedPageIds.delete(pageId);
    }
    syncSelectAllPages();
  }
  const toggleButton = event.target.closest(".toggle-option");
  if (toggleButton) {
    const input = document.getElementById(toggleButton.dataset.target);
    if (input) {
      input.value = toggleButton.dataset.value;
      syncToggleButtons();
    }
  }
  const positionButton = event.target.closest(".check-position");
  if (positionButton) checkRankPosition(positionButton.dataset.id);
  const editPageButton = event.target.closest(".edit-page");
  if (editPageButton) editPage(editPageButton.dataset.id);
  const runButton = event.target.closest(".run-page");
  if (runButton) runPage(runButton.dataset.id);
  const groupEditButton = event.target.closest(".group-edit");
  if (groupEditButton) editPostGroup(groupEditButton.dataset.id);
  const groupDeleteRowButton = event.target.closest(".group-delete-row");
  if (groupDeleteRowButton) deletePostGroup(groupDeleteRowButton.dataset.id);
  const inspectButton = event.target.closest(".inspect-execution");
  if (inspectButton) openExecution(inspectButton.dataset.id);
  const cancelButton = event.target.closest(".cancel-execution");
  if (cancelButton) queueAction("cancel", cancelButton.dataset.id);
  const retryButton = event.target.closest(".retry-execution");
  if (retryButton) queueAction("retry", retryButton.dataset.id);
  const artifactButton = event.target.closest(".artifact-item");
  if (artifactButton) loadArtifact(artifactButton.dataset.filename, artifactButton);
  const workspaceTab = event.target.closest(".workspace-tab");
  if (workspaceTab) switchMainView(workspaceTab.dataset.view);
  const postAlertAction = event.target.closest(".post-alert-action");
  if (postAlertAction) {
    updatePostMonitorAlert(postAlertAction.dataset.id, postAlertAction.dataset.status);
  }
  const adminResourceTab = event.target.closest(".admin-resource-tab");
  if (adminResourceTab) {
    state.admin.resource = adminResourceTab.dataset.resource;
    state.admin.records = [];
    renderAdminResourceTabs();
    loadAdminRecords();
  }
  const adminEditButton = event.target.closest(".admin-edit");
  if (adminEditButton) editAdminRecord(adminEditButton.dataset.id);
  const adminDeleteRowButton = event.target.closest(".admin-delete-row");
  if (adminDeleteRowButton) deleteAdminRecord(adminDeleteRowButton.dataset.id);
  const tab = event.target.closest(".tab");
  if (tab) switchTab(tab.dataset.tab);
});

$("#global-campaign").addEventListener("change", () => Promise.all([loadPages(), loadQueue()]));
$("#global-page-type").addEventListener("change", () => Promise.all([loadPages(), loadQueue()]));
$("#page-search").addEventListener("input", renderPages);
$("#clear-filters").addEventListener("click", () => {
  $("#global-campaign").value = "";
  $("#global-page-type").value = "";
  $("#page-search").value = "";
  Promise.all([loadPages(), loadQueue()]);
});
$("#reload-all").addEventListener("click", loadAll);
$("#post-monitor-reload").addEventListener("click", loadPostMonitor);
$("#post-alert-status").addEventListener("change", loadPostMonitor);
$("#post-alert-severity").addEventListener("change", loadPostMonitor);
$("#post-run-status").addEventListener("change", loadPostMonitor);
$("#reload-pages").addEventListener("click", loadPages);
$("#reload-queue").addEventListener("click", loadQueue);
$("#queue-view").addEventListener("change", loadQueue);
$("#select-all-pages").addEventListener("change", (event) => {
  filteredPages().forEach((page) => {
    const pageId = Number(page.id);
    if (event.target.checked) {
      state.selectedPageIds.add(pageId);
    } else {
      state.selectedPageIds.delete(pageId);
    }
  });
  renderPages();
});
$("#schedule-selected").addEventListener("click", scheduleSelected);
$("#run-daily").addEventListener("click", runDaily);
$("#form-campaign").addEventListener("change", (event) => {
  loadServices(event.target.value);
  loadParentPageOptions(event.target.value);
});
$("#form-location-type").addEventListener("change", updateLocationFields);
$("#form-url").addEventListener("blur", (event) => {
  if ($("#form-slug").value.trim()) return;
  try {
    $("#form-slug").value = new URL(event.target.value).pathname
      .split("/")
      .filter(Boolean)
      .at(-1) || "";
  } catch {
    $("#form-slug").value = "";
  }
});
$("#page-form").addEventListener("submit", savePage);
$("#page-cancel-edit").addEventListener("click", resetPageForm);
$("#group-form").addEventListener("submit", savePostGroup);
$("#group-new").addEventListener("click", resetPostGroupForm);
$("#group-reload").addEventListener("click", loadPostGroups);
$("#group-cancel-edit").addEventListener("click", resetPostGroupForm);
$("#group-delete").addEventListener("click", () => deletePostGroup());
$("#group-campaign").addEventListener("change", loadPostGroups);
$("#group-post-status").addEventListener("change", loadPostGroups);
$("#group-state").addEventListener("change", loadPostGroups);
$("#group-search").addEventListener("input", debounce(loadPostGroups, 350));
$("#group-clear-filters").addEventListener("click", () => {
  $("#group-campaign").value = "";
  $("#group-post-status").value = "";
  $("#group-state").value = "";
  $("#group-search").value = "";
  loadPostGroups();
});
$("#admin-form").addEventListener("submit", saveAdminRecord);
$("#admin-new").addEventListener("click", resetAdminForm);
$("#admin-reload").addEventListener("click", loadAdminRecords);
$("#admin-cancel-edit").addEventListener("click", resetAdminForm);
$("#admin-delete").addEventListener("click", () => deleteAdminRecord());
$("#validate-xlsx").addEventListener("click", () => processXlsx(true));
$("#import-xlsx").addEventListener("click", () => {
  if (confirm("Se crearán o actualizarán páginas y programaciones. ¿Continuar?")) processXlsx(false);
});
$("#close-execution").addEventListener("click", () => $("#execution-dialog").close());
$("#reload-log").addEventListener("click", loadExecutionLog);
$("#copy-json").addEventListener("click", async () => {
  if (state.currentArtifact === null) return;
  await navigator.clipboard.writeText(JSON.stringify(state.currentArtifact, null, 2));
  toast("JSON copiado");
});

$("#schedule-date").value = defaultScheduleDate();
syncToggleButtons();
updateLocationFields();
loadAll();
setInterval(loadQueue, 30000);
setInterval(() => {
  if ($("#view-post-monitor").classList.contains("active")) loadPostMonitor();
}, 15000);
