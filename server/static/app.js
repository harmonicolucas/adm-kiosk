"use strict";

/* ADM Kiosk - Administração remota dos equipamentos (Harmonico Lucas) */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

const state = {
  meta: null,
  devices: [],
  now: 0,
  selected: new Set(),
  filters: { platform: "", terminal: "", type: "", state: "", text: "" },
  openDevice: null,
  timers: [],
};

const PAGE_STATES = {
  ok: ["Apresentada", "ok"],
  loading: ["A carregar", "warn"],
  error: ["Erro na página", "bad"],
  offline: ["Sem rede", "bad"],
  nolinks: ["Sem página", "warn"],
  paused: ["No ambiente de trabalho", "warn"],
};
const CMD_STATUS = {
  pending: ["Pendente", "warn"],
  sent: ["Enviado", "warn"],
  ok: ["Concluído", "ok"],
  failed: ["Falhou", "bad"],
  expired: ["Expirado", "none"],
};

// ------------------------------------------------------------------ utilitários

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(method, path, body) {
  const opt = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(path, opt);
  let data = {};
  try { data = await res.json(); } catch (_) { /* sem corpo */ }
  if (res.status === 401 && path !== "/api/login") {
    showLogin();
    throw new Error(data.error || "Sessão expirada");
  }
  if (!res.ok) throw new Error(data.error || ("Erro " + res.status));
  return data;
}

function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (bad ? " bad" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 3500);
}

function ago(ts) {
  if (!ts) return "nunca";
  const s = Math.max(0, Math.round((state.now || Date.now() / 1000) - ts));
  if (s < 60) return `há ${s} s`;
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  return new Date(ts * 1000).toLocaleString("pt-PT");
}

function fmtDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleString("pt-PT") : "-";
}

function fmtUptime(sec) {
  if (!sec) return "-";
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  return (d ? d + " d " : "") + h + " h " + m + " min";
}

function terminalBadge(t) {
  if (t === "DPT") return '<span class="badge dpt">DPT - Doméstico</span>';
  if (t === "IPT") return '<span class="badge ipt">IPT - Internacional</span>';
  return '<span class="badge none">Por classificar</span>';
}

function typeBadge(t) {
  const label = state.meta?.screenTypes?.[t];
  return label ? `<span class="badge type">${esc(label)}</span>` : '<span class="badge none">-</span>';
}

function platformBadge(d) {
  if (d.platform === "windows") return '<span class="badge pc">Computador / Netbox - Windows</span>';
  if (d.platform === "linux") return '<span class="badge pc">Computador / Netbox - Linux</span>';
  return '<span class="badge tv">Smart TV / Android</span>';
}

function pageBadge(d) {
  if (!d.online) return '<span class="badge none">Offline</span>';
  const [label, cls] = PAGE_STATES[d.state?.page] || ["-", "none"];
  return `<span class="badge ${cls}" title="${esc(d.state?.error || d.state?.url || "")}">${label}</span>`;
}

function statusDot(d) {
  if (!d.online) return '<span class="dot off"></span>Offline';
  if (["error", "offline"].includes(d.state?.page)) return '<span class="dot err"></span>Online';
  return '<span class="dot on"></span>Online';
}

// ------------------------------------------------------------------ sessão

function showLogin() {
  state.timers.forEach(clearInterval);
  state.timers = [];
  if (typeof closeLive === "function" && live.id) closeLive();
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
  $("#modal").classList.add("hidden");
  setTimeout(() => $("#login-password").focus(), 50);
}

async function showApp(mustChange) {
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  state.meta = await api("GET", "/api/meta");
  $("#discovery-port").textContent = state.meta.discoveryPort;
  $$(".discovery-port").forEach(el => { el.textContent = state.meta.discoveryPort; });
  $("#server-addresses").innerHTML = state.meta.addresses.map(a => `<li class="mono">${esc(a)}</li>`).join("");
  await loadNetSettings();
  await loadDevices();
  state.timers.push(setInterval(loadDevices, 5000));
  state.timers.push(setInterval(refreshOpenDevice, 4000));
  $("#password-notice").classList.toggle("hidden", !mustChange);
}

$("#login-form").addEventListener("submit", async e => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    const r = await api("POST", "/api/login", { password: $("#login-password").value });
    $("#login-password").value = "";
    showApp(r.mustChange);
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

// ------------------------------------------------------------------ endereço do servidor

async function loadNetSettings() {
  let s;
  try { s = await api("GET", "/api/server-settings"); } catch (err) { toast(err.message, true); return; }
  state.net = s;
  $("#server-addresses").innerHTML = s.addresses.map(a => `<li class="mono">${esc(a)}</li>`).join("");
  const f = $("#net-form");
  const known = s.localIps.includes(s.publicAddress);
  const mode = !s.publicAddress ? "" : known ? s.publicAddress : "custom";
  $("#net-mode").innerHTML =
    `<option value="">Automático (recomendado)</option>` +
    s.localIps.map(ip => `<option value="${esc(ip)}">${esc(ip)}</option>`).join("") +
    `<option value="custom">Outro endereço…</option>`;
  $("#net-mode").value = mode;
  f.custom.value = mode === "custom" ? s.publicAddress : "";
  f.port.value = s.port;
  f.discovery.checked = s.discovery;
  $("#net-custom-wrap").classList.toggle("hidden", mode !== "custom");
  $("#net-error").textContent = "";
  updateNetHint();
}

function updateNetHint() {
  const s = state.net;
  if (!s) return;
  const port = +$("#net-form").port.value || s.port;
  const mode = $("#net-mode").value;
  const parts = [mode === ""
    ? "Cada equipamento recebe o IP deste servidor na sua rede."
    : "Os equipamentos que procuram o servidor passam a receber este endereço."];
  parts.push(`Portas ativas: ${s.ports.join(", ")}.`);
  if (port !== s.port && !s.ports.includes(port)) {
    parts.push(`A porta ${port} será acrescentada; ${s.ports.join(", ")} continua${s.ports.length > 1 ? "m" : ""} a funcionar.`);
    parts.push(s.os === "windows"
      ? "No Windows, a nova porta é aberta na firewall automaticamente (servidor instalado)."
      : `No Linux com firewall ativa, abra a nova porta: sudo ufw allow ${port}/tcp`);
  }
  $("#net-hint").textContent = parts.join(" ");
}

$("#net-mode").addEventListener("change", e => {
  $("#net-custom-wrap").classList.toggle("hidden", e.target.value !== "custom");
  if (e.target.value === "custom") $("#net-form").custom.focus();
  updateNetHint();
});
$("#net-form").port.addEventListener("input", updateNetHint);

$("#net-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target;
  const mode = $("#net-mode").value;
  const body = {
    publicAddress: mode === "custom" ? f.custom.value.trim() : mode,
    port: +f.port.value,
    discovery: f.discovery.checked,
  };
  $("#net-error").textContent = "";
  if (mode === "custom" && !body.publicAddress) { $("#net-error").textContent = "Indique o endereço."; return; }
  const portAdded = !state.net.ports.includes(body.port);
  if (portAdded && !confirm(`Acrescentar a porta ${body.port} e torná-la a porta principal?\n\n` +
    `As portas atuais (${state.net.ports.join(", ")}) continuam a funcionar, por isso os equipamentos ` +
    "com o endereço antigo não são afetados.")) return;
  try {
    await api("PUT", "/api/server-settings", body);
  } catch (err) { $("#net-error").textContent = err.message; return; }
  toast(portAdded ? `Porta ${body.port} acrescentada` : "Endereço do servidor guardado");
  await loadNetSettings();
  state.meta.addresses = state.net.addresses;
});

$("#logout-btn").addEventListener("click", async () => {
  try { await api("POST", "/api/logout"); } catch (_) { /* ignorar */ }
  showLogin();
});

// ------------------------------------------------------------------ separadores

function showTab(name) {
  $$("#tabs button").forEach(x => x.classList.toggle("active", x.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.add("hidden"));
  $("#tab-" + name).classList.remove("hidden");
  $("main").scrollTop = 0;
  if (name === "profiles") loadProfiles();
  if (name === "events") loadEvents();
  if (name === "settings") loadNetSettings();
  if (name === "wall") { renderWall(); captureAll(); }
}
$$("#tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

/** Abre a lista de equipamentos já filtrada (usado pelos cartões da visão geral). */
function showDevicesFiltered(filters) {
  Object.assign(state.filters, { platform: "", terminal: "", type: "", state: "", text: "" }, filters);
  for (const k of ["platform", "terminal", "type", "state", "text"]) $("#filter-" + k).value = state.filters[k];
  renderDevices();
  showTab("devices");
}

// ------------------------------------------------------------------ televisores

async function loadDevices() {
  try {
    const r = await api("GET", "/api/devices");
    state.devices = r.devices;
    state.now = r.now;
    for (const id of Array.from(state.selected)) {
      if (!state.devices.some(d => d.id === id)) state.selected.delete(id);
    }
    renderSummary();
    renderOverview();
    renderDevices();
    if (wallVisible()) renderWall();
  } catch (err) {
    console.warn(err);
  }
}

function hasPageError(d) {
  return d.online && ["error", "offline"].includes(d.state?.page);
}

function renderSummary() {
  const ds = state.devices;
  const online = ds.filter(d => d.online).length;
  const offline = ds.length - online;
  const err = ds.filter(hasPageError).length;
  const pending = ds.filter(d => !d.config_applied).length;
  const tvs = ds.filter(d => d.platform === "android").length;
  const pcs = ds.length - tvs;
  const stats = [
    ["Registados", ds.length, "", {}, `${tvs} ${tvs === 1 ? "TV" : "TVs"}, ${pcs} ${pcs === 1 ? "computador" : "computadores"}`],
    ["Online", online, "", { state: "online" }, ds.length ? `${Math.round(online * 100 / ds.length)}% da rede` : ""],
    ["Offline", offline, offline ? "bad" : "", { state: "offline" }, ""],
    ["Com erro na página", err, err ? "warn" : "", { state: "error" }, pending ? `${pending} com configuração pendente` : ""],
  ];
  $("#summary").innerHTML = stats.map(([l, n, c, , sub], i) =>
    `<button class="stat ${c}" data-stat="${i}"><span class="l">${l}</span><span class="n">${n}</span><span class="s">${esc(sub)}</span></button>`).join("");
  $$("#summary [data-stat]").forEach(b => b.addEventListener("click", () => showDevicesFiltered(stats[+b.dataset.stat][3])));
  const nav = $("#nav-count");
  nav.textContent = ds.length || "";
  nav.classList.toggle("alert", offline + err > 0);
}

function renderOverview() {
  const ds = state.devices;
  const issues = [];
  for (const d of ds) {
    if (!d.online) issues.push([d, 0, "bad", "Offline"]);
    else if (hasPageError(d)) issues.push([d, 1, "warn", PAGE_STATES[d.state.page][0]]);
    else if (!d.config_applied) issues.push([d, 2, "info", "Configuração pendente"]);
    else if (!d.terminal || !d.screen_type) issues.push([d, 3, "info", "Por classificar"]);
  }
  issues.sort((a, b) => a[1] - b[1] || (b[0].last_seen || 0) - (a[0].last_seen || 0));
  $("#attention-count").textContent = issues.length ? String(issues.length) : "";
  $("#attention").innerHTML = issues.length ? issues.slice(0, 15).map(([d, , cls, title]) => `
    <tr class="clickable" data-id="${esc(d.id)}">
      <td><span class="st ${cls}">${esc(title)}</span></td>
      <td><b>${esc(d.label)}</b>${d.location ? `<small>${esc(d.location)}</small>` : ""}</td>
      <td class="mono">${esc(d.network?.ip || d.seen_ip || "-")}</td>
      <td title="${esc(fmtDate(d.last_seen))}">${ago(d.last_seen)}</td>
    </tr>`).join("") + (issues.length > 15
      ? `<tr><td colspan="4" class="muted">Mais ${issues.length - 15} em Equipamentos.</td></tr>` : "")
    : '<tr><td colspan="4" class="muted">Sem ocorrências.</td></tr>';
  $$("#attention [data-id]").forEach(r => r.addEventListener("click", () => openDevice(r.dataset.id)));

  const meta = state.meta || {};
  const terms = [...Object.keys(meta.terminals || {}).map(k => [k, k, meta.terminals[k]]), ["-", "Sem terminal", "Sem terminal"]];
  const types = [...Object.entries(meta.screenTypes || {}).map(([k, v]) => [k, v.replace(/^FIDS\s+/i, "")]),
    ...(ds.some(d => !d.screen_type) ? [["-", "Sem tipo"]] : [])];
  const match = (d, t, s) => (t === "-" ? !d.terminal : d.terminal === t) && (s === "-" ? !d.screen_type : d.screen_type === s);
  const cell = (list, f, tag = "td") => {
    const on = list.filter(d => d.online).length;
    if (!list.length) return `<${tag} class="num muted">-</${tag}>`;
    return `<${tag} class="num"><a href="#" data-f='${esc(JSON.stringify(f))}'><span class="${on < list.length ? "short" : ""}">${on}</span>/${list.length}</a></${tag}>`;
  };
  const rows = terms.filter(([t]) => t !== "-" || ds.some(d => !d.terminal)).map(([t, tl, full]) => {
    const inTerm = ds.filter(d => t === "-" ? !d.terminal : d.terminal === t);
    return `<tr><th scope="row" title="${esc(full)}">${esc(tl)}</th>${types.map(([s]) =>
      cell(ds.filter(d => match(d, t, s)), { terminal: t, type: s })).join("")}${cell(inTerm, { terminal: t })}</tr>`;
  }).join("");
  const plat = [["android", "Smart TVs"], ["windows", "Windows"], ["linux", "Linux"]]
    .map(([k, l]) => `<a href="#" data-f='${esc(JSON.stringify({ platform: k }))}'>${l} <b>${ds.filter(d => d.platform === k).length}</b></a>`).join("");
  $("#distribution").innerHTML = `
    <div class="matrix-wrap"><table class="grid compact matrix">
      <thead><tr><th></th>${types.map(([, l]) => `<th class="num">${esc(l)}</th>`).join("")}<th class="num">Total</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><th scope="row">Total</th>${types.map(([s]) =>
        cell(ds.filter(d => s === "-" ? !d.screen_type : d.screen_type === s), { type: s }, "th")).join("")}${cell(ds, {}, "th")}</tr></tfoot>
    </table></div>
    <div class="platforms">${plat}</div>`;
  $$("#distribution [data-f]").forEach(a => a.addEventListener("click", e => {
    e.preventDefault();
    showDevicesFiltered(JSON.parse(a.dataset.f));
  }));
}

function platformShort(d) {
  if (d.platform === "windows") return "Windows";
  if (d.platform === "linux") return "Linux";
  return "Smart TV";
}

function filteredDevices() {
  const f = state.filters;
  const text = f.text.trim().toLowerCase();
  return state.devices.filter(d => {
    if (f.platform === "pc" && d.platform === "android") return false;
    if (f.platform && f.platform !== "pc" && d.platform !== f.platform) return false;
    if (f.terminal === "-" && d.terminal) return false;
    if (f.terminal && f.terminal !== "-" && d.terminal !== f.terminal) return false;
    if (f.type === "-" && d.screen_type) return false;
    if (f.type && f.type !== "-" && d.screen_type !== f.type) return false;
    if (f.state === "online" && !d.online) return false;
    if (f.state === "offline" && d.online) return false;
    if (f.state === "error" && !(d.online && ["error", "offline"].includes(d.state?.page))) return false;
    if (f.state === "pending" && d.config_applied) return false;
    if (text) {
      const hay = [d.label, d.location, d.gate, d.network?.ip, d.network?.mac, d.network?.gateway,
        d.device?.model, d.device?.manufacturer, d.device?.hostname, d.id, d.seen_ip].join(" ").toLowerCase();
      if (!hay.includes(text)) return false;
    }
    return true;
  });
}

function renderDevices() {
  const list = filteredDevices();
  const tbody = $("#devices-table tbody");
  tbody.innerHTML = list.map(d => `
    <tr class="clickable ${d.online ? "" : "is-off"}" data-id="${esc(d.id)}">
      <td class="w-check"><input type="checkbox" class="sel" data-id="${esc(d.id)}" ${state.selected.has(d.id) ? "checked" : ""}></td>
      <td>
        <div class="cell-main">
          <span class="dot ${!d.online ? "off" : hasPageError(d) ? "err" : "on"}" title="${d.online ? "Online" : "Offline"}"></span>
          <div><b>${esc(d.label)}</b>${d.config_applied ? "" : ' <span class="pill warn" title="A aguardar que o equipamento aplique a configuração">pendente</span>'}
            <small>${esc([platformShort(d), d.location || d.device?.hostname].filter(Boolean).join(" · "))}</small></div>
        </div>
      </td>
      <td>${d.terminal ? `<b class="tag">${esc(d.terminal)}</b>` : ""}${d.screen_type ? esc(state.meta?.screenTypes?.[d.screen_type] || d.screen_type) : '<span class="muted">Por classificar</span>'}${d.gate ? ` <span class="muted">· Gate ${esc(d.gate)}</span>` : ""}</td>
      <td><span class="mono">${esc(d.network?.ip || d.seen_ip || "-")}</span>${d.network?.mac ? `<small class="mono">${esc(d.network.mac)}</small>` : ""}</td>
      <td>${pageBadge(d)}</td>
      <td title="${esc(fmtDate(d.last_seen))}">${ago(d.last_seen)}</td>
      <td class="w-actions">
        <button class="btn small primary" data-live="${esc(d.id)}" title="Ver e controlar o ecrã"><svg><use href="#i-play"/></svg>Ao vivo</button>
        <button class="btn small ghost" data-act="identify" data-id="${esc(d.id)}" title="Mostrar nome e IP no próprio ecrã">Identificar</button>
        <button class="btn small ghost" data-act="reload" data-id="${esc(d.id)}" title="Recarregar a página">Recarregar</button>
        ${d.platform !== "android" ? `<button class="btn small danger" data-act="reboot" data-id="${esc(d.id)}" title="Forçar o reinício do Windows ou do Linux">Reiniciar</button>` : ""}
        <button class="btn small ghost danger-text" data-remove="${esc(d.id)}" title="Remover do inventário"><svg><use href="#i-trash"/></svg></button>
      </td>
    </tr>`).join("");
  $("#devices-empty").classList.toggle("hidden", list.length > 0);
  $("#select-all").checked = list.length > 0 && list.every(d => state.selected.has(d.id));
  renderBulkbar();
}

function renderBulkbar() {
  const n = state.selected.size;
  $("#bulkbar").classList.toggle("hidden", n === 0);
  $("#bulk-count").textContent = `${n} selecionado(s)`;
}

$("#devices-table tbody").addEventListener("click", async e => {
  const cb = e.target.closest("input.sel");
  if (cb) {
    cb.checked ? state.selected.add(cb.dataset.id) : state.selected.delete(cb.dataset.id);
    renderBulkbar();
    e.stopPropagation();
    return;
  }
  const liveBtn = e.target.closest("button[data-live]");
  if (liveBtn) {
    e.stopPropagation();
    openLive(liveBtn.dataset.live);
    return;
  }
  const removeBtn = e.target.closest("button[data-remove]");
  if (removeBtn) {
    e.stopPropagation();
    await removeDevices([removeBtn.dataset.remove]);
    return;
  }
  const btn = e.target.closest("button[data-act]");
  if (btn) {
    e.stopPropagation();
    if (btn.dataset.act === "reboot") {
      const name = state.devices.find(d => d.id === btn.dataset.id)?.label || "este computador";
      if (!confirm(`Forçar o reinício de ${name}?\n\nO Windows ou o Linux reinicia e os programas abertos são fechados.`)) return;
    }
    await sendCommand(btn.dataset.id, btn.dataset.act);
    return;
  }
  const row = e.target.closest("tr[data-id]");
  if (row) openDevice(row.dataset.id);
});

$("#select-all").addEventListener("change", e => {
  filteredDevices().forEach(d => e.target.checked ? state.selected.add(d.id) : state.selected.delete(d.id));
  renderDevices();
});

for (const key of ["platform", "terminal", "type", "state"]) {
  $("#filter-" + key).addEventListener("change", e => { state.filters[key] = e.target.value; renderDevices(); });
}
$("#filter-text").addEventListener("input", e => { state.filters.text = e.target.value; renderDevices(); });

/** Remove do inventário; devolve true se algum equipamento foi removido. */
async function removeDevices(ids) {
  const names = ids.map(id => state.devices.find(d => d.id === id)?.label || id);
  const what = ids.length === 1 ? `"${names[0]}"` : `${ids.length} equipamentos`;
  if (!confirm(`Remover ${what} do inventário?\n` +
    "Se o equipamento continuar ligado, volta a registar-se automaticamente.")) return false;
  let removed = 0;
  for (const id of ids) {
    try {
      await api("DELETE", `/api/devices/${id}`);
      state.selected.delete(id);
      removed++;
    } catch (err) { toast(err.message, true); }
  }
  if (removed) toast(removed === 1 ? "Equipamento removido do inventário" : `${removed} equipamentos removidos do inventário`);
  await loadDevices();
  return removed > 0;
}

$("#bulk-remove").addEventListener("click", () => removeDevices(Array.from(state.selected)));
$("#bulk-clear").addEventListener("click", () => { state.selected.clear(); renderDevices(); });
$$("#bulkbar [data-bulk]").forEach(b => b.addEventListener("click", async () => {
  let ids = Array.from(state.selected);
  if (b.dataset.bulk === "reboot") {
    ids = ids.filter(id => {
      const d = state.devices.find(x => x.id === id);
      return d && d.platform !== "android";
    });
    if (!ids.length) { toast("Selecione computadores Windows ou Linux.", true); return; }
    if (!confirm(`Forçar o reinício de ${ids.length} computador(es)?\n\nO Windows ou o Linux reinicia e os programas abertos são fechados.`)) return;
  }
  try {
    const r = await api("POST", "/api/commands/bulk", { ids, type: b.dataset.bulk, payload: {} });
    toast(`Comando enviado a ${r.count} equipamento(s)` + (r.skipped ? ` (${r.skipped} não suportam este comando)` : ""));
  } catch (err) { toast(err.message, true); }
}));
$("#bulk-config-btn").addEventListener("click", openBulkConfig);

$$("[data-reload-all]").forEach(b => b.addEventListener("click", async () => {
  const ids = state.devices.filter(d => d.online).map(d => d.id);
  if (!ids.length) { toast("Não há equipamentos online para recarregar.", true); return; }
  if (!confirm(`Recarregar a página de todos os equipamentos online (${ids.length})?`)) return;
  try {
    const r = await api("POST", "/api/commands/bulk", { ids, type: "reload", payload: {} });
    toast(`Recarregamento enviado a ${r.count} equipamento(s)`);
  } catch (err) { toast(err.message, true); }
}));

function tickClock() {
  $("#clock").textContent = new Date().toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
}
tickClock();
setInterval(tickClock, 1000);

// ------------------------------------------------------------------ comandos

async function sendCommand(id, type, payload = {}) {
  try {
    await api("POST", `/api/devices/${id}/commands`, { type, payload });
    toast(`${state.meta.commands[type]}: enviado ao equipamento`);
    if (state.openDevice === id) refreshOpenDevice();
  } catch (err) { toast(err.message, true); }
}

// ------------------------------------------------------------------ detalhe do televisor

function openModal(html) {
  $("#modal-content").innerHTML = html;
  $("#modal").classList.remove("hidden");
}

function closeModal() {
  $("#modal").classList.add("hidden");
  state.openDevice = null;
}
$("#modal-close").addEventListener("click", closeModal);
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

function options(map, value, emptyLabel) {
  return `<option value="">${esc(emptyLabel)}</option>` +
    Object.entries(map).map(([k, v]) => `<option value="${k}" ${k === value ? "selected" : ""}>${esc(v)}</option>`).join("");
}

const REFRESH_OPTIONS = [[0, "Desativada"], [30, "30 s"], [60, "1 min"], [120, "2 min"], [300, "5 min"],
  [600, "10 min"], [900, "15 min"], [1800, "30 min"], [3600, "1 h"]];

function refreshSelect(value) {
  const opts = REFRESH_OPTIONS.some(([v]) => v === value) ? REFRESH_OPTIONS : [...REFRESH_OPTIONS, [value, value + " s"]];
  return opts.map(([v, l]) => `<option value="${v}" ${v === value ? "selected" : ""}>${l}</option>`).join("");
}

async function openDevice(id, keepPane = false) {
  state.openDevice = id;
  if (!keepPane) state.devicePane = "summary";
  let d;
  try { d = await api("GET", `/api/devices/${id}`); } catch (err) { toast(err.message, true); return; }
  const dv = d.device || {};
  const isPc = d.platform !== "android";
  openModal(`
    <div class="detail-head">
      <div>
        <h2>${esc(d.label)}</h2>
        <div class="badges">
          <span id="dh-status" class="status">${statusDot(d)}</span>
          ${platformBadge(d)} ${terminalBadge(d.terminal)} ${d.screen_type ? typeBadge(d.screen_type) : ""}
          ${d.gate ? `<span class="badge none">Gate ${esc(d.gate)}</span>` : ""}
        </div>
      </div>
      <div class="detail-actions">
        ${isPc ? `<button class="btn danger" id="dev-reboot">Forçar reinício</button>` : ""}
        <button class="btn primary" id="dev-live"><svg><use href="#i-play"/></svg>Ver ao vivo e controlar</button>
      </div>
    </div>
    <p class="muted small" id="dh-applied">${appliedText(d)}</p>

    <div class="mtabs" role="tablist">
      <button class="active" data-pane="summary">Resumo</button>
      <button data-pane="config">Configuração</button>
      <button data-pane="commands">Comandos</button>
    </div>

    <div class="pane" data-pane="summary">
      <div class="detail-grid">
        <div class="box">
          <h3>Captura de ecrã</h3>
          <div id="shot-wrap">${shotHtml(d)}</div>
        </div>
        <div class="box">
          <h3>Página apresentada</h3>
          <dl class="kv" id="page-kv">${pageKv(d)}</dl>
        </div>
        <div class="box">
          <h3>Rede</h3>
          <dl class="kv" id="net-kv">${netKv(d)}</dl>
        </div>
        <div class="box">
          <h3>Equipamento</h3>
          <dl class="kv">
            <dt>Fabricante</dt><dd>${esc(dv.manufacturer || "-")}</dd>
            <dt>Modelo</dt><dd>${esc(dv.model || "-")}</dd>
            ${isPc ? `
            <dt>Sistema</dt><dd>${esc(dv.os || "-")}</dd>
            <dt>Nome na rede</dt><dd class="mono">${esc(dv.hostname || "-")}</dd>
            <dt>Utilizador</dt><dd>${esc(dv.user || "-")}</dd>
            <dt>Navegador</dt><dd>${esc(dv.browserName || "-")}</dd>
            ${dv.session ? `<dt>Sessão gráfica</dt><dd>${esc(dv.session)}${dv.session === "Wayland" ? ' <span class="badge warn">sem controlo remoto</span>' : ""}</dd>` : ""}
            ${dv.capture ? `<dt>Captura / controlo</dt><dd>${esc(dv.capture)} / ${esc(dv.control || "-")}</dd>` : ""}
            ` : `
            <dt>Android</dt><dd>${esc(dv.android || "-")} ${dv.sdk ? "(API " + esc(dv.sdk) + ")" : ""}</dd>
            `}
            <dt>Resolução</dt><dd>${esc(dv.resolution || "-")}</dd>
            <dt>Versão</dt><dd>${esc(dv.appVersion || "-")}</dd>
            <dt>Arranque automático</dt><dd>${dv.isLauncher ? '<span class="badge ok">Sim</span>' : '<span class="badge warn">Não (definir como launcher)</span>'}</dd>
            ${isPc ? "" : `<dt>Device Owner</dt><dd>${dv.deviceOwner ? "Sim" : "Não"}</dd>`}
            <dt>Ligado há</dt><dd>${fmtUptime(dv.uptimeSec)}</dd>
            <dt>Registado em</dt><dd>${fmtDate(d.first_seen)}</dd>
            <dt>ID</dt><dd class="mono">${esc(d.id)}</dd>
          </dl>
        </div>
      </div>
    </div>

    <div class="pane hidden" data-pane="config">
          <form id="dev-form" class="form">
            <label>Nome do equipamento <input name="name" value="${esc(d.name)}" maxlength="80" placeholder="ex.: FIDS Partidas 01"></label>
            <label>Localização <input name="location" value="${esc(d.location)}" maxlength="120" placeholder="ex.: Sala de embarque, piso 1"></label>
            <label>Terminal
              <select name="terminal">${options(state.meta.terminals, d.terminal, "Por classificar")}</select></label>
            <label>Tipo de ecrã
              <select name="screen_type">${options(state.meta.screenTypes, d.screen_type, "Por classificar")}</select></label>
            <label>Gate (ecrãs de gate) <input name="gate" value="${esc(d.gate)}" maxlength="16" placeholder="ex.: 3"></label>
            <label>Zoom (%) <small>sem alterar a disposição do texto</small>
              <input name="zoom" type="number" min="25" max="400" step="10" value="${d.zoom}"></label>
            <label class="full">URL próprio <small>vazio = usa a página do tipo de ecrã${d.url ? "" : (d.effective_url ? ": " + esc(d.effective_url) : " (não definida)")}</small>
              <input name="url" value="${esc(d.url)}" placeholder="http://, https:// ou IP"></label>
            <label>Atualização automática
              <select name="refresh_seconds">${refreshSelect(d.refresh_seconds)}</select></label>
            ${isPc ? `
            <label>Navegador
              <select name="browser">${Object.entries(state.meta.browsers).map(([k, v]) =>
                `<option value="${k}" ${k === (d.browser || "") ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
            ` : `
            <label>Tempo de cada ecrã de voos (s)
              <input name="auto_scroll_seconds" type="number" min="3" max="300" value="${d.auto_scroll_seconds}"></label>
            <label class="check"><input type="checkbox" name="auto_scroll" ${d.auto_scroll ? "checked" : ""}> Rodar automaticamente os voos cortados</label>
            `}
            <label class="check"><input type="checkbox" name="kiosk_enabled" ${d.kiosk_enabled ? "checked" : ""}> ${isPc ? "Navegador em modo kiosk (ecrã inteiro)" : "Modo Kiosk ativo"}</label>
            <label class="check"><input type="checkbox" name="reload_on_error" ${d.reload_on_error ? "checked" : ""}> Recarregar em caso de falha</label>
            <label>Nova tentativa após falha (s)
              <input name="retry_delay_seconds" type="number" min="3" max="300" value="${d.retry_delay_seconds}"></label>
            <label class="full">Notas <textarea name="notes" rows="2" maxlength="500">${esc(d.notes)}</textarea></label>
            <div class="actions full" style="grid-column:1/-1">
              <button class="btn primary" type="submit">Guardar e enviar ao equipamento</button>
            </div>
          </form>
    </div>

    <div class="pane hidden" data-pane="commands">
      <div class="cmds">
        ${(d.allowed_commands || Object.keys(state.meta.commands)).map(k =>
          `<button class="btn ${k === "reboot" ? "danger" : ""}" data-cmd="${k}">${esc(state.meta.commands[k])}</button>`).join("")}
      </div>
      <h3 class="sub">Histórico de comandos</h3>
      <div class="cmd-hist" id="cmd-hist">${commandHistory(d.commands)}</div>
    </div>

    <div class="detail-foot">
      <button class="btn danger" data-dev-delete><svg><use href="#i-trash"/></svg>Remover do inventário</button>
    </div>`);

  $("#dev-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target;
    const body = {
      name: f.name.value, location: f.location.value, terminal: f.terminal.value,
      screen_type: f.screen_type.value, gate: f.gate.value, url: f.url.value,
      zoom: +f.zoom.value, refresh_seconds: +f.refresh_seconds.value,
      kiosk_enabled: f.kiosk_enabled.checked, reload_on_error: f.reload_on_error.checked,
      retry_delay_seconds: +f.retry_delay_seconds.value, notes: f.notes.value,
    };
    if (!confirmUrls([body.url])) return;
    if (isPc) {
      body.browser = f.browser.value;
    } else {
      body.auto_scroll = f.auto_scroll.checked;
      body.auto_scroll_seconds = +f.auto_scroll_seconds.value;
    }
    try {
      await api("PUT", `/api/devices/${id}`, body);
      toast("Configuração guardada e enviada ao equipamento.");
      loadDevices();
      openDevice(id, true);
    } catch (err) { toast(err.message, true); }
  });

  $("#dev-live").addEventListener("click", () => openLive(id));
  $("#dev-reboot")?.addEventListener("click", async () => {
    if (!confirm(`Forçar o reinício de ${d.label}?\n\nO Windows ou o Linux reinicia e os programas abertos são fechados.`)) return;
    await sendCommand(id, "reboot");
  });

  $$(".mtabs button", $("#modal-content")).forEach(b => b.addEventListener("click", () => {
    state.devicePane = b.dataset.pane;
    $$(".mtabs button", $("#modal-content")).forEach(x => x.classList.toggle("active", x === b));
    $$(".pane", $("#modal-content")).forEach(p => p.classList.toggle("hidden", p.dataset.pane !== b.dataset.pane));
  }));
  if (keepPane && state.devicePane) $(`.mtabs button[data-pane="${state.devicePane}"]`, $("#modal-content"))?.click();

  $$("[data-dev-delete]", $("#modal-content")).forEach(b => b.addEventListener("click", async () => {
    if (await removeDevices([id])) closeModal();
  }));

  $$("[data-cmd]", $("#modal-content")).forEach(b => b.addEventListener("click", async () => {
    const type = b.dataset.cmd;
    let payload = {};
    if (type === "set_pin") {
      const pin = prompt("Novo código de acesso do televisor (4 dígitos):");
      if (pin === null) return;
      if (!/^\d{4}$/.test(pin)) { toast("O código deve ter 4 dígitos", true); return; }
      payload = { pin };
    }
    if (type === "reboot" && !confirm(isPc ? "Reiniciar o computador?" : "Reiniciar o televisor? (exige Device Owner)")) return;
    if (type === "restart_app" && !confirm(isPc ? "Reiniciar o navegador no computador?" : "Reiniciar a aplicação no televisor?")) return;
    await sendCommand(id, type, payload);
  }));
}

function appliedText(d) {
  if (d.config_version === 0) return "Configuração original do equipamento (ainda não alterada remotamente).";
  return d.config_applied
    ? `Configuração v${d.config_version} aplicada no equipamento.`
    : `Configuração v${d.config_version} a aguardar aplicação (o equipamento tem a v${d.applied_version}).`;
}

function netKv(d) {
  const n = d.network || {};
  return `
    <dt>Endereço IP</dt><dd class="mono">${esc(n.ip || "-")}</dd>
    <dt>Máscara</dt><dd class="mono">${esc(n.mask || "-")}${n.prefix ? " (/" + esc(n.prefix) + ")" : ""}</dd>
    <dt>Gateway</dt><dd class="mono">${esc(n.gateway || "-")}</dd>
    <dt>DNS</dt><dd class="mono">${esc((n.dns || []).join(", ") || "-")}</dd>
    <dt>MAC</dt><dd class="mono">${esc(n.mac || "não disponibilizado pelo Android")}</dd>
    <dt>Ligação</dt><dd>${esc(n.transport || "-")} ${n.iface ? "(" + esc(n.iface) + ")" : ""}</dd>
    <dt>IP visto pelo servidor</dt><dd class="mono">${esc(d.seen_ip || "-")}</dd>
    <dt>Última comunicação</dt><dd>${ago(d.last_seen)}</dd>`;
}

function pageKv(d) {
  const st = d.state || {};
  const [label, cls] = PAGE_STATES[st.page] || ["-", "none"];
  return `
    <dt>Estado</dt><dd>${d.online ? `<span class="badge ${cls}">${label}</span>` : '<span class="badge none">Offline</span>'}</dd>
    <dt>URL</dt><dd>${st.url ? `<a href="${esc(st.url)}" target="_blank" rel="noopener">${esc(st.url)}</a>` : "-"}</dd>
    ${st.error ? `<dt>Erro</dt><dd>${esc(st.error)}</dd>` : ""}`;
}

function shotHtml(d) {
  if (!d.shot_ts) return '<p class="muted">Sem captura. Use o comando "Captura de ecrã".</p>';
  return `<a href="/api/screenshots/${esc(d.id)}.jpg?t=${d.shot_ts}" target="_blank">
            <img class="shot" src="/api/screenshots/${esc(d.id)}.jpg?t=${d.shot_ts}" alt="Captura"></a>
          <small class="muted">Capturado ${ago(d.shot_ts)} (${fmtDate(d.shot_ts)})</small>`;
}

function commandHistory(cmds) {
  if (!cmds || !cmds.length) return '<p class="muted">Sem comandos enviados.</p>';
  return `<table class="grid"><tbody>${cmds.map(c => {
    const [label, cls] = CMD_STATUS[c.status] || [c.status, "none"];
    return `<tr><td>${fmtDate(c.created)}</td><td>${esc(state.meta.commands[c.type] || c.type)}</td>
      <td><span class="badge ${cls}">${label}</span></td><td class="muted">${esc(c.message)}</td></tr>`;
  }).join("")}</tbody></table>`;
}

async function refreshOpenDevice() {
  const id = state.openDevice;
  if (!id || $("#modal").classList.contains("hidden")) return;
  try {
    const d = await api("GET", `/api/devices/${id}`);
    if (state.openDevice !== id) return;
    $("#dh-status").innerHTML = statusDot(d);
    $("#dh-applied").textContent = appliedText(d);
    $("#cmd-hist").innerHTML = commandHistory(d.commands);
    $("#net-kv").innerHTML = netKv(d);
    $("#page-kv").innerHTML = pageKv(d);
    const img = $("#shot-wrap img");
    const cur = img ? Number(new URL(img.src).searchParams.get("t")) : 0;
    if (d.shot_ts && d.shot_ts !== cur) $("#shot-wrap").innerHTML = shotHtml(d);
  } catch (_) { /* ignorar */ }
}

// ------------------------------------------------------------------ mural de ecrãs

function wallVisible() {
  return !$("#tab-wall").classList.contains("hidden");
}

function renderWall() {
  const wall = $("#wall");
  const list = state.devices;
  const seen = new Set();
  for (const d of list) {
    seen.add(d.id);
    let tile = wall.querySelector(`.tile[data-id="${CSS.escape(d.id)}"]`);
    if (!tile) {
      tile = document.createElement("div");
      tile.className = "tile";
      tile.dataset.id = d.id;
      tile.innerHTML = '<div class="screen"><span class="muted">Sem captura</span><span class="play"><svg><use href="#i-play"/></svg>Ao vivo</span></div><div class="info"></div>';
      tile.addEventListener("click", () => openLive(d.id));
      wall.appendChild(tile);
    }
    tile.classList.toggle("offline", !d.online);
    if (d.shot_ts && tile.dataset.ts !== String(d.shot_ts)) {
      tile.dataset.ts = String(d.shot_ts);
      tile.querySelector(".screen").innerHTML =
        `<img src="/api/screenshots/${encodeURIComponent(d.id)}.jpg?t=${d.shot_ts}" alt=""><span class="play"><svg><use href="#i-play"/></svg>Ao vivo</span>`;
    }
    tile.querySelector(".info").innerHTML = `
      <span class="dot ${!d.online ? "off" : hasPageError(d) ? "err" : "on"}"></span>
      <div class="grow"><b>${esc(d.label)}</b>
        <small>${esc([platformShort(d), state.meta?.screenTypes?.[d.screen_type], d.terminal].filter(Boolean).join(" · "))}</small></div>
      <small class="muted">${d.shot_ts ? ago(d.shot_ts) : ""}</small>`;
  }
  wall.querySelectorAll(".tile").forEach(t => { if (!seen.has(t.dataset.id)) t.remove(); });
  wall.querySelector(".empty")?.remove();
  if (!list.length) wall.innerHTML = '<div class="empty"><h3>Nenhum equipamento registado</h3><p>Os ecrãs aparecem aqui quando se registam no servidor.</p></div>';
}

async function captureAll() {
  const ids = state.devices.filter(d => d.online).map(d => d.id);
  if (!ids.length) return;
  try {
    await api("POST", "/api/commands/bulk", { ids, type: "screenshot", payload: {} });
  } catch (err) { console.warn(err); }
}

$("#wall-refresh").addEventListener("click", async () => {
  await captureAll();
  toast("Pedido enviado. As imagens chegam dentro de segundos.");
});

setInterval(() => {
  if (wallVisible() && $("#wall-auto").checked && !$("#app-view").classList.contains("hidden")) captureAll();
}, 60000);

// ------------------------------------------------------------------ sessão ao vivo (ver e controlar)

const live = {
  id: null, frameTimer: null, statusTimer: null, renewTimer: null, flushTimer: null,
  pending: [], sending: false, gotFrame: false, buttons: 0, moveAt: 0,
};

async function openLive(id) {
  let d = state.devices.find(x => x.id === id);
  if (!d) { try { d = await api("GET", `/api/devices/${id}`); } catch (err) { toast(err.message, true); return; } }
  if (!d.online && !confirm(`${d.label} está offline. Tentar ligar mesmo assim?`)) return;
  closeModal();
  live.id = id;
  live.pending = [];
  live.gotFrame = false;
  live.buttons = 0;
  live.openedAt = Date.now();
  $("#live-img").classList.remove("ready");
  $("#live-wait").textContent = "A ligar ao equipamento…";
  $("#live-title").textContent = d.label;
  const isTv = d.platform === "android";
  $$("#live [data-only]").forEach(b => b.classList.toggle("hidden", (b.dataset.only === "android") !== isTv));
  $("#live-status").textContent = "A ligar…";
  $("#live-wait").classList.remove("hidden");
  $("#live").classList.remove("hidden");
  $("#live-stage").focus();
  await renewLive();
  live.renewTimer = setInterval(renewLive, 60000);
  live.statusTimer = setInterval(updateLiveStatus, 1500);
  live.flushTimer = setInterval(flushInputs, 40);
  connectStream();
}

async function renewLive() {
  if (!live.id) return;
  try {
    await api("POST", `/api/devices/${live.id}/live`, {
      seconds: 120, intervalMs: +$("#live-speed").value, quality: $("#live-quality").value,
    });
  } catch (err) { toast(err.message, true); }
}

async function closeLive() {
  if (!live.id) return;
  const id = live.id;
  live.id = null;
  [live.renewTimer, live.statusTimer, live.flushTimer].forEach(clearInterval);
  clearTimeout(live.frameTimer);
  $("#live-img").src = "data:,";
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  $("#live").classList.add("hidden");
  try { await api("POST", `/api/devices/${id}/live`, { seconds: 0 }); } catch (_) { /* ignorar */ }
}

// Fluxo contínuo (MJPEG): o navegador mostra cada imagem assim que o servidor a recebe.
function connectStream() {
  if (!live.id) return;
  clearTimeout(live.frameTimer);
  $("#live-img").src = `/api/live/${encodeURIComponent(live.id)}.mjpg?t=${Date.now()}`;
}

$("#live-img").addEventListener("load", () => {
  if (!live.id) return;
  live.gotFrame = true;
  $("#live-img").classList.add("ready");
  $("#live-wait").classList.add("hidden");
});
$("#live-img").addEventListener("error", () => {
  if (live.id) live.frameTimer = setTimeout(connectStream, 1500);
});

// Explica porque é que a imagem não chega, em vez de ficar indefinidamente em "A ligar…".
function liveDiagnosis(d) {
  const waited = (Date.now() - live.openedAt) / 1000;
  const version = d.device.appVersion || "desconhecida";
  const update = d.platform === "android" ? "Instale o ADM Kiosk 2.4.4 nesta TV."
    : "Reinstale o agente ADM Kiosk 2.5.1 neste computador.";
  if (!d.online) return "O equipamento está offline (sem contacto com o servidor).";
  if (d.live_support === "none") return `Esta TV tem uma versão antiga do ADM Kiosk (${version}) que não permite ver o ecrã ao vivo. ${update}`;
  const dv = d.device || {};
  if (d.platform === "linux" && dv.session === "Wayland") return "Este computador Linux está numa sessão Wayland, onde o sistema não permite ver nem controlar o ecrã " +
    "(o Ubuntu 25.10 / 26.04 com GNOME só tem Wayland). Volte a executar o instalador do agente (sudo sh instalar.sh) e aceite instalar a sessão XFCE (X11).";
  if (d.platform === "linux" && dv.capture === "indisponível") return "O computador respondeu, mas não tem nenhuma ferramenta de captura do ecrã. Volte a executar o instalador do agente (instala o ffmpeg).";
  if (d.live_status === "noscreen") return "A TV respondeu, mas não está a mostrar o ecrã ADM Kiosk (está nas definições, noutra aplicação ou no menu do Android). A tentar abri-lo…";
  if (d.live_status === "capture") return d.platform === "android"
    ? "A TV respondeu, mas não consegue capturar o ecrã. Experimente o comando \"Reiniciar aplicação\"."
    : "O computador respondeu, mas não consegue capturar o ecrã (ver o registo do agente). No Linux é necessária uma sessão X11 (Xorg/XFCE).";
  if (d.live_contact_age == null && waited > 12) return `O equipamento ainda não respondeu ao pedido de sessão. Versão instalada: ${version}. ${update} Se já estiver atualizado, verifique a rede entre o equipamento e o servidor.`;
  return "A ligar ao equipamento…";
}

async function updateLiveStatus() {
  if (!live.id) return;
  try {
    const d = await api("GET", `/api/devices/${live.id}`);
    const slow = d.live_support === "slow" ? " (versão antiga: imagem lenta e sem arrastar - atualize)" : "";
    $("#live-status").textContent = !d.online ? "Equipamento offline"
      : !d.live ? "Sessão terminada no equipamento - a renovar…"
      : d.live_fps > 0 ? `Ao vivo - ${String(d.live_fps).replace(".", ",")} imagens/s${slow}`
      : live.gotFrame ? `Ao vivo - ecrã sem alterações${slow}`
      : "A aguardar a primeira imagem…";
    if (!live.gotFrame) $("#live-wait").textContent = liveDiagnosis(d);
    if (!d.live && d.online) renewLive();
  } catch (_) { /* ignorar */ }
}

function liveControlOn() {
  return $("#live-control").checked;
}

function queueInput(ev) {
  if (!live.id || !liveControlOn()) return;
  const last = live.pending[live.pending.length - 1];
  if (ev.type === "move" && last && last.type === "move") live.pending[live.pending.length - 1] = ev;
  else live.pending.push(ev);
}

async function flushInputs() {
  if (!live.id || !live.pending.length || live.sending) return;
  const events = live.pending.splice(0, 100);
  live.sending = true;
  try {
    await api("POST", `/api/devices/${live.id}/input`, { events });
  } catch (err) {
    $("#live-status").textContent = err.message;
  } finally {
    live.sending = false;
  }
}

function relPos(e) {
  const r = $("#live-img").getBoundingClientRect();
  return {
    x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
    y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
  };
}

// Rato real: premir, mover e largar são enviados em separado (permite arrastar e duplo clique nativo).
const liveImg = $("#live-img");
liveImg.addEventListener("mousedown", e => {
  if (e.button !== 0 && e.button !== 2) return;
  e.preventDefault();
  $("#live-stage").focus();
  live.buttons |= 1 << e.button;
  queueInput({ type: "down", button: e.button === 2 ? "right" : "left", ...relPos(e) });
});
liveImg.addEventListener("mousemove", e => {
  const now = Date.now();
  if (now - live.moveAt < 40) return;
  live.moveAt = now;
  queueInput({ type: "move", ...relPos(e) });
});
window.addEventListener("mouseup", e => {
  if (!live.id || !(live.buttons & (1 << e.button))) return;
  live.buttons &= ~(1 << e.button);
  queueInput({ type: "up", button: e.button === 2 ? "right" : "left", ...relPos(e) });
});
liveImg.addEventListener("contextmenu", e => e.preventDefault());
let wheelAt = 0;
liveImg.addEventListener("wheel", e => {
  e.preventDefault();
  const now = Date.now();
  if (now - wheelAt < 120) return;
  wheelAt = now;
  const dy = Math.sign(e.deltaY) * Math.max(1, Math.min(10, Math.round(Math.abs(e.deltaY) / 100)));
  queueInput({ type: "scroll", dy, ...relPos(e) });
}, { passive: false });

$("#live-stage").addEventListener("keydown", e => {
  if (!live.id || !liveControlOn()) return;
  if (["Control", "Alt", "Shift", "AltGraph"].includes(e.key)) return;
  e.preventDefault();
  e.stopPropagation();
  queueInput({ type: "key", key: e.key, ctrl: e.ctrlKey, alt: e.altKey, shift: e.shiftKey && e.key.length > 1 });
});

$("#live-text").addEventListener("keydown", e => {
  e.stopPropagation();
  if (e.key === "Enter" && e.target.value) {
    queueInput({ type: "text", text: e.target.value });
    e.target.value = "";
  }
});

$$("#live [data-key]").forEach(b => b.addEventListener("click", () => {
  queueInput({ type: "key", key: b.dataset.key, alt: !!b.dataset.alt });
  $("#live-stage").focus();
}));
$("#live-control").addEventListener("change", e => {
  $("#live-stage").classList.toggle("view-only", !e.target.checked);
});
$("#live-speed").addEventListener("change", renewLive);
$("#live-quality").addEventListener("change", renewLive);
$("#live-full").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else $("#live").requestFullscreen().catch(() => {});
});
$("#live-close").addEventListener("click", closeLive);
window.addEventListener("beforeunload", () => {
  if (!live.id) return;
  fetch(`/api/devices/${live.id}/live`, {
    method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ seconds: 0 }),
  });
});

// ------------------------------------------------------------------ configuração em massa

function openBulkConfig() {
  const ids = Array.from(state.selected);
  openModal(`
    <h2>Configurar ${ids.length} equipamento(s)</h2>
    <p class="muted">Apenas os campos marcados são alterados nos equipamentos selecionados.</p>
    <form id="bulk-form" class="form">
      ${bulkField("terminal", "Terminal", `<select name="terminal">${options(state.meta.terminals, "", "Por classificar")}</select>`)}
      ${bulkField("screen_type", "Tipo de ecrã", `<select name="screen_type">${options(state.meta.screenTypes, "", "Por classificar")}</select>`)}
      ${bulkField("url", "URL próprio (vazio = página do tipo de ecrã)", `<input name="url" placeholder="http://…">`)}
      ${bulkField("zoom", "Zoom (%)", `<input name="zoom" type="number" min="25" max="400" step="10" value="100">`)}
      ${bulkField("refresh_seconds", "Atualização automática", `<select name="refresh_seconds">${refreshSelect(0)}</select>`)}
      ${bulkField("auto_scroll", "Rodar voos cortados", `<select name="auto_scroll"><option value="1">Ativo</option><option value="0">Desativado</option></select>`)}
      ${bulkField("auto_scroll_seconds", "Tempo de cada ecrã de voos (s)", `<input name="auto_scroll_seconds" type="number" min="3" max="300" value="10">`)}
      ${bulkField("kiosk_enabled", "Modo Kiosk", `<select name="kiosk_enabled"><option value="1">Ativo</option><option value="0">Desativado</option></select>`)}
      <div class="actions" style="grid-column:1/-1">
        <button class="btn primary" type="submit">Aplicar aos selecionados</button>
      </div>
    </form>`);
  $("#bulk-form").addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target, fields = {};
    $$("input.use", f).forEach(cb => {
      if (!cb.checked) return;
      const el = f.elements[cb.dataset.field];
      let v = el.value;
      if (["zoom", "refresh_seconds", "auto_scroll_seconds"].includes(cb.dataset.field)) v = +v;
      if (["auto_scroll", "kiosk_enabled"].includes(cb.dataset.field)) v = v === "1";
      fields[cb.dataset.field] = v;
    });
    if (!Object.keys(fields).length) { toast("Marque pelo menos um campo", true); return; }
    if ("url" in fields && !confirmUrls([fields.url])) return;
    try {
      const r = await api("POST", "/api/devices/bulk-config", { ids, fields });
      toast(`Configuração enviada a ${r.count} equipamento(s)`);
      closeModal();
      loadDevices();
    } catch (err) { toast(err.message, true); }
  });
}

function bulkField(name, label, control) {
  return `<label><span><input type="checkbox" class="use" data-field="${name}"> ${esc(label)}</span>${control}</label>`;
}

/** Um nome sem ponto nem porta (ex.: "admin") quase sempre é um engano: pede confirmação. */
function confirmUrls(urls) {
  const odd = urls.map(u => (u || "").trim()).filter(u => {
    if (!u) return false;
    const host = u.replace(/^https?:\/\//i, "").replace(/[/?#].*$/, "");
    return !/[.:]/.test(host) && host.toLowerCase() !== "localhost";
  });
  return !odd.length || confirm(`"${odd[0]}" não parece um endereço de página (ex.: http://10.10.5.20/fids).\n` +
    "O equipamento vai mostrar \"site não encontrado\". Guardar mesmo assim?");
}

// ------------------------------------------------------------------ perfis

async function loadProfiles() {
  const r = await api("GET", "/api/profiles");
  const get = (t, s) => r.profiles.find(p => p.terminal === t && p.screen_type === s) || { url: "", devices: 0 };
  const types = Object.entries(state.meta.screenTypes);
  let html = '<div class="h">Terminal</div>' + types.map(([, l]) => `<div class="h">${esc(l)}</div>`).join("");
  for (const [t, tl] of Object.entries(state.meta.terminals)) {
    html += `<div class="t">${esc(tl)}</div>`;
    for (const [s] of types) {
      const p = get(t, s);
      html += `<div><input data-t="${t}" data-s="${s}" value="${esc(p.url)}" placeholder="http://…">
        <small>${p.devices} equipamento(s) a usar esta página</small></div>`;
    }
  }
  $("#profiles-grid").innerHTML = html;
  $("#profiles-msg").textContent = "";
}

$("#profiles-save").addEventListener("click", async () => {
  const profiles = $$("#profiles-grid input").map(i => ({ terminal: i.dataset.t, screen_type: i.dataset.s, url: i.value }));
  if (!confirmUrls(profiles.map(p => p.url))) return;
  try {
    const r = await api("PUT", "/api/profiles", { profiles });
    $("#profiles-msg").textContent = `Guardado. ${r.devices} equipamento(s) vão atualizar a página.`;
    loadProfiles();
    loadDevices();
  } catch (err) { toast(err.message, true); }
});

// ------------------------------------------------------------------ eventos

async function loadEvents() {
  const r = await api("GET", "/api/events?limit=300");
  $("#events-body").innerHTML = r.events.map(e => `
    <tr><td style="white-space:nowrap">${fmtDate(e.ts)}</td><td>${esc(e.device || "-")}</td>
    <td>${e.level === "warn" ? '<span class="badge warn">!</span> ' : ""}${esc(e.message)}</td></tr>`).join("")
    || '<tr><td colspan="3" class="muted">Sem eventos.</td></tr>';
}

// ------------------------------------------------------------------ palavra-passe

async function changePassword(form, errEl) {
  errEl.textContent = "";
  if (form.new.value !== form.confirm.value) { errEl.textContent = "A confirmação não coincide"; return false; }
  try {
    await api("POST", "/api/password", { current: form.current.value, new: form.new.value });
    form.reset();
    $("#password-notice").classList.add("hidden");
    toast("Palavra-passe alterada");
    return true;
  } catch (err) {
    errEl.textContent = err.message;
    return false;
  }
}

$("#password-form").addEventListener("submit", e => {
  e.preventDefault();
  changePassword(e.target, $("#password-error"));
});

// ------------------------------------------------------------------ arranque

(async function init() {
  try {
    const me = await api("GET", "/api/me");
    if (me.authenticated) showApp(me.mustChange); else showLogin();
  } catch (_) {
    showLogin();
  }
})();
