/* B站之眼 · 设置中心
 * 无构建、无外部依赖；通过 AstrBot Plugin View 桥接调用后端。
 */

const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const CLEAR = "__clear__";

const ICONS = {
  overview: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></svg>',
  login: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="8" r="4"/><path d="M4.5 20c1.6-3.4 4.2-5 7.5-5s5.9 1.6 7.5 5"/></svg>',
  videos: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3V9Z"/></svg>',
  transcript: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>',
  cache: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 3 7.5 12 12l9-4.5L12 3Z"/><path d="m3 12 9 4.5 9-4.5M3 16.5 12 21l9-4.5"/></svg>',
  diagnostics: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h4l2.5-6 4 12 2.5-6H21"/></svg>',
  config: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-1.8 1.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-2.6v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L7.5 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H6v-2.6h.3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L7.5 7l1.8-1.8.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6v-.2h2.6V4a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1 1.8 1.8-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v2.6h-.2a1.7 1.7 0 0 0-1.6 1Z"/></svg>',
};

const state = {
  status: null,
  groups: [],
  values: {},
  secrets: {},
  original: {},
  secretsOriginal: {},
  dirty: new Set(),
  active: "overview",
  videos: [],
  cache: null,
  diagnostics: null,
  detail: null,
  login: { key: "", url: "", image: "", state: "idle", message: "", timer: null, countdown: null, expiresAt: 0 },
  saving: false,
};

const NAV_META = {
  overview: { title: "概览", desc: "插件运行状态、登录情况与最近观看。" },
  login: { title: "登录", desc: "扫码绑定 B 站账号，解锁更高画质与更稳的字幕/评论接口。" },
  videos: { title: "视频记录", desc: "最近观看、笔记与原文记录。" },
  transcript: { title: "原文检索", desc: "直接读取官方字幕、B站 AI、内嵌 OCR 与 ASR 原文。" },
  cache: { title: "缓存", desc: "笔记、原文、帧与临时音频缓存。" },
  diagnostics: { title: "诊断", desc: "运行环境、接口注册与路径信息。" },
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
function fmtBytes(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = n / 1024;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[index]}`;
}
function fmtAge(seconds) {
  const s = Math.max(0, Number(seconds || 0));
  if (s < 60) return `${s} 秒前`;
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  return `${Math.floor(s / 86400)} 天前`;
}
function modeLabel(mode) {
  return { normal: "普通", enhanced: "增强", extreme: "极致", "": "未记录" }[mode] || mode || "未知";
}
function sourceLabel(source) {
  return { official: "官方人工", ai: "B站 AI", ocr: "内嵌 OCR", asr: "ASR", guest: "游客", qr: "扫码", config: "配置 SESSDATA" }[source] || source || "未知";
}

async function apiGet(endpoint, params = {}) {
  if (!bridge) throw new Error("AstrBot 插件页桥接未注入");
  const result = await bridge.apiGet(endpoint, params);
  if (result?.success === false) throw new Error(result.error || "请求失败");
  return result || {};
}
async function apiPost(endpoint, body = {}) {
  if (!bridge) throw new Error("AstrBot 插件页桥接未注入");
  const result = await bridge.apiPost(endpoint, body);
  if (result?.success === false) throw new Error(result.error || "请求失败");
  return result || {};
}
function showAlert(message) {
  const el = $("#alert");
  if (!message) { el.hidden = true; el.textContent = ""; return; }
  el.hidden = false; el.textContent = String(message);
  console.error("[B站之眼 WebUI]", message);
}
function toast(message, kind = "ok") {
  const box = $("#toasts");
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  box.appendChild(node);
  window.setTimeout(() => node.remove(), 4200);
}
function copyText(text) {
  if (!text) return;
  const fallback = () => {
    const input = document.createElement("textarea");
    input.value = text; input.style.position = "fixed"; input.style.opacity = "0";
    document.body.appendChild(input); input.select();
    try { document.execCommand("copy"); } catch { /* ignore */ }
    input.remove();
  };
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).catch(fallback);
  else fallback();
}
function confirmDialog(title, body, okText = "确认") {
  return new Promise((resolve) => {
    const modal = $("#modal");
    $("#modal-title").textContent = title;
    $("#modal-body").textContent = body;
    $("#modal-ok").textContent = okText;
    modal.hidden = false;
    const close = (value) => { modal.hidden = true; resolve(value); };
    $("#modal-ok").onclick = () => close(true);
    $("#modal-cancel").onclick = () => close(false);
    modal.querySelector("[data-close]")?.addEventListener("click", () => close(false), { once: true });
    window.setTimeout(() => $("#modal-ok").focus(), 20);
  });
}

async function boot() {
  if (!bridge) {
    showAlert("未检测到 AstrBot 插件页桥接，请从 AstrBot 插件管理页打开本页面。");
    $("#page-title").textContent = "无法加载";
    return;
  }
  try {
    const context = await bridge.ready();
    applyTheme(context?.isDark);
    bridge.onContext?.((ctx) => applyTheme(ctx?.isDark));
  } catch { /* bridge ready 可选 */ }
  bindShell();
  try { await refreshAll(); showView("overview"); }
  catch (error) { showAlert(`初始化失败：${error.message || error}`); }
}
function applyTheme(isDark) { document.documentElement.dataset.theme = isDark ? "dark" : "light"; }

function bindShell() {
  $("#btn-reload").addEventListener("click", async () => {
    if (state.dirty.size && !(await confirmDialog("放弃未保存更改？", "刷新会丢弃尚未保存的配置修改。", "刷新"))) return;
    await refreshAll(); toast("已刷新");
  });
  $("#btn-save").addEventListener("click", saveSettings);
  $("#btn-save-2").addEventListener("click", saveSettings);
  $("#btn-discard").addEventListener("click", () => {
    state.values = structuredCloneSafe(state.original);
    state.secrets = structuredCloneSafe(state.secretsOriginal);
    state.dirty.clear(); renderSettings(); updateSaveBar(); renderNav();
    toast("已放弃未保存修改");
  });
  $("#nav").addEventListener("click", (event) => {
    const button = event.target.closest("[data-nav]");
    if (button) showView(button.dataset.nav);
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (state.dirty.size) saveSettings();
    }
  });
}
function structuredCloneSafe(value) {
  try { return structuredClone(value); } catch { return JSON.parse(JSON.stringify(value)); }
}

async function refreshAll() {
  showAlert("");
  const statusResult = await apiGet("status").catch(() => null);
  const settingsResult = await apiGet("settings").catch((error) => { showAlert(`设置加载失败：${error.message}`); return null; });
  if (statusResult?.status) state.status = statusResult.status;
  if (settingsResult) {
    state.groups = settingsResult.groups || [];
    state.values = settingsResult.values || {};
    state.secrets = settingsResult.secrets_present || {};
    state.original = structuredCloneSafe(state.values);
    state.secretsOriginal = structuredCloneSafe(state.secrets);
    state.dirty.clear();
  }
  try { state.videos = (await apiGet("videos", { limit: 80 })).rows || []; } catch { state.videos = []; }
  try { state.cache = await apiGet("cache"); } catch { state.cache = null; }
  renderAll();
}
function renderAll() {
  renderNav();
  renderOverview();
  renderVideos();
  renderSettings();
  renderLogin();
  renderTranscript();
  renderCache();
  renderDiagnostics();
  renderDetail();
  renderSidebar();
  updateLoginPill();
  updateSaveBar();
  showView(state.active);
}
function renderSidebar() {
  const status = state.status || {};
  $("#side-version").textContent = `v${status.version || "—"}`;
  $("#side-path").textContent = status.data_dir || "—";
  $("#side-path").title = status.data_dir || "";
  $("#side-dot").classList.toggle("warn", !status.login?.logged_in);
}
function updateLoginPill() {
  const pill = $("#login-pill");
  const login = state.status?.login;
  if (!login) { pill.className = "pill"; pill.textContent = "读取中…"; return; }
  if (login.logged_in) {
    pill.className = "pill ok";
    pill.textContent = login.account?.uname ? `已登录 · ${login.account.uname}` : `已登录 · ${sourceLabel(login.source)}`;
  } else { pill.className = "pill warn"; pill.textContent = "游客模式"; }
}
function updateSaveBar() {
  const dirty = state.dirty.size;
  $("#savebar").hidden = !dirty;
  $("#dirty-note").textContent = `有 ${dirty} 项未保存更改`;
  $("#btn-save").disabled = !dirty;
  $("#btn-save-2").disabled = !dirty;
}

function navItems() {
  const items = [
    { id: "overview", ...NAV_META.overview, icon: ICONS.overview },
    { id: "login", ...NAV_META.login, icon: ICONS.login },
    { id: "videos", ...NAV_META.videos, icon: ICONS.videos },
    { id: "transcript", ...NAV_META.transcript, icon: ICONS.transcript },
  ];
  state.groups.forEach((group) => items.push({ id: `group-${group.id}`, title: group.title, desc: group.desc || "", group, icon: ICONS.config }));
  items.push({ id: "cache", ...NAV_META.cache, icon: ICONS.cache });
  items.push({ id: "diagnostics", ...NAV_META.diagnostics, icon: ICONS.diagnostics });
  return items;
}
function renderNav() {
  const items = navItems();
  let html = "";
  items.forEach((item, index) => {
    if (item.group && !items[index - 1]?.group) html += '<div class="nav-sep">配置</div>';
    const active = state.active === item.id ? " active" : "";
    const dirty = item.group ? groupDirtyCount(item.group) : 0;
    html += `<button class="nav-item${active}" type="button" data-nav="${esc(item.id)}"><span class="icon">${item.icon}</span><span>${esc(item.title)}</span>${dirty ? `<span class="badge-count">${dirty}</span>` : ""}</button>`;
  });
  $("#nav").innerHTML = html;
}
function groupDirtyCount(group) {
  return (group.fields || []).filter((field) => state.dirty.has(field.key)).length;
}
function showView(id) {
  state.active = id;
  const item = navItems().find((entry) => entry.id === id);
  $$(".view").forEach((node) => node.classList.toggle("active", node.dataset.view === id));
  if (id === "login") renderLogin();
  if (id === "videos") renderVideos();
  if (id === "transcript") loadTranscriptVideos();
  if (id === "cache") loadCachePage();
  if (id === "diagnostics") loadDiagnostics();
  $("#page-title").textContent = item?.title || "设置";
  $("#page-desc").textContent = item?.desc || "";
  renderNav();
  updateSaveBar();
}

function renderOverview() {
  const host = $("#view-overview");
  const status = state.status;
  if (!status) { host.innerHTML = `<div class="card"><div class="empty">正在读取插件状态…</div></div>`; return; }
  const login = status.login || {};
  const cache = status.cache || {};
  const stats = [
    { k: "B站登录", v: login.logged_in ? (login.account?.uname || "已登录") : "游客", ok: login.logged_in, s: login.logged_in ? `来源：${sourceLabel(login.source)}${login.sessdata_tail ? ` · ${login.sessdata_tail}` : ""}` : "未登录只能取 360P/480P，字幕接口更易风控" },
    { k: "当前模式", v: modeLabel(status.video_mode), s: "普通 / 增强 / 极致" },
    { k: "视觉子代理", v: status.vision_provider_id || "跟随全局默认模型", muted: !status.vision_provider_id, s: status.vision_provider_id ? "设置页指定了视觉 Provider" : "可在配置中单独指定" },
    { k: "文本证据", v: status.ocr?.enabled ? "官方/AI/OCR 优先" : "官方/AI 优先", s: `OCR ${status.ocr?.enabled ? "已启用" : "未启用"} · ASR ${status.asr?.enabled ? "已启用" : "未启用"}` },
    { k: "缓存", v: fmtBytes(cache.notes?.bytes || 0), s: `${cache.notes?.count || 0} 条笔记 · ${cache.frames?.count || 0} 个帧文件` },
    { k: "FFmpeg", v: status.ffmpeg?.available ? "可用" : "未找到", ok: status.ffmpeg?.available, s: status.ffmpeg?.path || "视觉截帧与 ASR 依赖 ffmpeg" },
  ];
  const runtime = [["插件版本", `v${status.version || "—"}`], ["数据目录", status.data_dir || "—"], ["服务时间", status.server_time ? new Date(status.server_time * 1000).toLocaleString() : "—"], ["已注册接口", `${(status.registered_apis || []).length} 个`]];
  host.innerHTML = `<div class="stat-grid">${stats.map(statCard).join("")}</div>
    <div class="card"><div class="card-head"><div><h2>最近观看</h2><p>展示笔记与原文记录，点击进入详情。</p></div><div class="card-actions"><button class="btn small ghost" data-nav-jump="videos" type="button">全部记录</button></div></div>${renderVideoTable(state.videos.slice(0, 8))}</div>
    <div class="card"><div class="card-head"><div><h2>运行信息</h2><p>排查问题时优先看这里。</p></div><div class="card-actions"><button class="btn small ghost" data-copy="${esc(status.data_dir || "")}" type="button">复制数据目录</button></div></div><dl class="kv">${runtime.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>`;
  host.querySelectorAll("[data-nav-jump]").forEach((node) => node.addEventListener("click", () => showView(node.dataset.navJump)));
  host.querySelectorAll("[data-copy]").forEach((node) => node.addEventListener("click", () => { copyText(node.dataset.copy); toast("已复制"); }));
  host.querySelectorAll("[data-bvid]").forEach((row) => row.addEventListener("click", () => openDetail(row.dataset.bvid, row.dataset.page)));
}
function statCard(item) {
  const cls = item.ok === true ? "ok" : item.ok === false ? "warn" : item.muted ? "muted" : "";
  return `<div class="stat"><div class="k">${esc(item.k)}</div><div class="v ${cls}">${esc(item.v)}</div><div class="s">${esc(item.s || "")}</div></div>`;
}
function renderVideoTable(rows) {
  if (!rows.length) return `<div class="empty"><div class="big">🕒</div>还没有观看记录</div>`;
  return `<div class="table-wrap"><table class="table"><thead><tr><th>标题</th><th>BV</th><th>模式</th><th>来源</th><th>时间</th></tr></thead><tbody>${rows.map((item) => `<tr data-bvid="${esc(item.bvid)}" data-page="${esc(item.page || 1)}"><td class="t-title" title="${esc(item.title)}">${esc(item.title || "（无标题）")}</td><td><code>${esc(item.bvid)}</code></td><td><span class="tag">${esc(modeLabel(item.mode))}</span></td><td>${item.text_origin ? `<span class="tag brand">${esc(sourceLabel(item.text_origin))}</span>` : `<span class="muted">—</span>`}</td><td>${esc(fmtAge(Math.max(0, Date.now() / 1000 - Number(item.created || 0))))}</td></tr>`).join("")}</tbody></table></div>`;
}

function renderSettings() {
  const host = $("#settings-views");
  if (!state.groups.length) { host.innerHTML = `<section class="view" data-view="settings-empty"><div class="card"><div class="empty">正在读取配置项…</div></div></section>`; return; }
  host.innerHTML = state.groups.map((group) => renderGroup(group)).join("");
  host.querySelectorAll("[data-field]").forEach((input) => { input.addEventListener("input", onFieldInput); input.addEventListener("change", onFieldInput); });
  host.querySelectorAll("[data-action]").forEach((node) => node.addEventListener("click", handleSettingsAction));
  $$(".view", host).forEach((node) => node.classList.toggle("active", node.dataset.view === state.active));
}
function renderGroup(group) {
  const dirty = groupDirtyCount(group);
  const normal = group.fields.filter((field) => !field.wide);
  const wide = group.fields.filter((field) => field.wide);
  return `<section class="view" data-view="group-${esc(group.id)}"><div class="card form-group"><div class="group-head"><div><h2>${esc(group.title)}</h2><p>${esc(group.desc || "")}</p></div><div class="card-actions">${dirty ? `<span class="tag warn">${dirty} 项待保存</span>` : ""}<button class="btn small ghost" type="button" data-action="reset-group" data-group="${esc(group.id)}">恢复本组默认</button></div></div><div class="fields">${normal.map((field) => renderField(field)).join("")}${wide.map((field) => renderField(field)).join("")}</div></div></section>`;
}
function fieldValue(key) { return state.values[key] ?? ""; }
function renderField(field) {
  const id = `f_${field.key}`;
  const value = fieldValue(field.key);
  const hint = field.hint ? `<div class="hint">${esc(field.hint)}</div>` : "";
  if (field.kind === "bool") return `<div class="field wide"><div class="bool-row"><div class="bool-text"><b>${esc(field.label)}</b><small>${esc(field.hint || "")}</small></div><label class="switch"><input type="checkbox" id="${id}" data-field="${esc(field.key)}" ${value ? "checked" : ""} /><span></span></label></div></div>`;
  if (field.kind === "secret") {
    const present = Boolean(state.secrets[field.key]);
    return `<div class="field"><label for="${id}">${esc(field.label)}</label><div class="secret-box"><div class="secret-top"><span>${present ? "已配置；留空表示保持当前值" : "尚未配置"}</span>${present ? `<button class="btn link" type="button" data-action="clear-secret" data-key="${esc(field.key)}">清除</button>` : ""}</div><input type="password" id="${id}" data-field="${esc(field.key)}" data-kind="secret" autocomplete="new-password" placeholder="${present ? "输入新值" : "输入凭据"}" /></div>${hint}</div>`;
  }
  if (field.kind === "select") {
    const options = (field.options || []).map((opt) => `<option value="${esc(opt.value)}" ${String(value) === String(opt.value) ? "selected" : ""}>${esc(opt.label)}</option>`).join("");
    return `<div class="field"><label for="${id}">${esc(field.label)}</label><select id="${id}" data-field="${esc(field.key)}">${options}</select>${hint}</div>`;
  }
  if (field.kind === "list") {
    const text = Array.isArray(value) ? value.join("\n") : String(value || "");
    return `<div class="field wide"><label for="${id}">${esc(field.label)}</label><textarea id="${id}" data-field="${esc(field.key)}" data-kind="list" placeholder="每行一个，或用逗号分隔">${esc(text)}</textarea>${hint}</div>`;
  }
  if (field.kind === "text") return `<div class="field wide"><label for="${id}">${esc(field.label)}</label><textarea id="${id}" data-field="${esc(field.key)}" data-kind="text">${esc(value)}</textarea>${hint}</div>`;
  const type = field.kind === "int" || field.kind === "float" ? "number" : "text";
  const step = field.kind === "float" ? ' step="any"' : "";
  return `<div class="field"><label for="${id}">${esc(field.label)}</label><input type="${type}"${step} id="${id}" data-field="${esc(field.key)}" value="${esc(value)}" />${hint}</div>`;
}
function onFieldInput(event) {
  const input = event.target;
  const key = input.dataset.field;
  if (!key) return;
  if (input.dataset.kind === "secret") {
    if (input.value.trim()) { state.values[key] = input.value; state.dirty.add(key); }
    else { state.values[key] = ""; state.dirty.delete(key); }
  } else if (input.type === "checkbox") { state.values[key] = Boolean(input.checked); state.dirty.add(key); }
  else { state.values[key] = input.value; state.dirty.add(key); }
  renderNav(); updateSaveBar();
}
async function handleSettingsAction(event) {
  const action = event.currentTarget.dataset.action;
  if (action === "clear-secret") {
    const key = event.currentTarget.dataset.key;
    state.values[key] = CLEAR; state.dirty.add(key);
    toast("已标记清除，保存后生效"); renderNav(); updateSaveBar();
  }
  if (action === "reset-group") {
    const group = event.currentTarget.dataset.group;
    if (!(await confirmDialog("恢复本组默认？", "本组所有字段会恢复为默认值，保存后立即生效。", "恢复默认"))) return;
    try {
      const result = await apiPost("settings/reset", { group });
      state.values = result.values || state.values; state.secrets = result.secrets_present || state.secrets;
      state.original = structuredCloneSafe(state.values); state.secretsOriginal = structuredCloneSafe(state.secrets); state.dirty.clear();
      renderSettings(); renderNav(); updateSaveBar(); toast(result.message || "已恢复默认");
    } catch (error) { showAlert(`恢复默认失败：${error.message}`); }
  }
}
async function saveSettings() {
  if (!state.dirty.size || state.saving) return;
  state.saving = true; $("#btn-save").disabled = true; $("#btn-save-2").disabled = true;
  const payload = {};
  for (const key of state.dirty) {
    const field = findField(key); if (!field) continue;
    if (field.kind === "secret") {
      if (state.values[key] === CLEAR) payload[key] = CLEAR;
      else if (String(state.values[key] || "").trim()) payload[key] = state.values[key];
    } else payload[key] = state.values[key];
  }
  try {
    const result = await apiPost("settings/save", { values: payload });
    state.values = result.values || state.values; state.secrets = result.secrets_present || state.secrets;
    state.original = structuredCloneSafe(state.values); state.secretsOriginal = structuredCloneSafe(state.secrets);
    state.dirty.clear(); renderSettings(); renderNav(); updateSaveBar(); updateLoginPill();
    toast(result.message || "设置已保存");
    if (result.restart_required) toast("线程池相关设置需要重载插件后生效", "err");
    if (payload.sessdata !== undefined) await refreshAll();
  } catch (error) { showAlert(`保存失败：${error.message}`); }
  finally { state.saving = false; }
}
function findField(key) {
  for (const group of state.groups) for (const field of group.fields || []) if (field.key === key) return field;
  return null;
}

function stopLoginTimers() {
  if (state.login.timer) window.clearInterval(state.login.timer);
  if (state.login.countdown) window.clearInterval(state.login.countdown);
  state.login.timer = null; state.login.countdown = null;
}
function renderLogin() {
  const host = $("#view-login");
  const login = state.status?.login || {};
  const account = login.account || {};
  const loggedIn = Boolean(login.logged_in);
  const qr = state.login;
  const avatar = account.avatar ? `<img src="${esc(account.avatar)}" alt="${esc(account.uname || "B站头像")}" />` : esc((account.uname || "B").slice(0, 1).toUpperCase());
  const accountHtml = loggedIn
    ? `<div class="account-card"><div class="avatar">${avatar}</div><div class="account-meta"><h3>${esc(account.uname || "已登录")}</h3><p>UID ${esc(account.mid || "—")} · LV${esc(account.level ?? "—")}${account.vip ? " · 大会员" : ""}</p><p>凭据来源：${esc(sourceLabel(login.source))}${login.sessdata_tail ? ` · ${esc(login.sessdata_tail)}` : ""}</p></div><div class="account-side"><span class="tag ok">已登录</span><button class="btn small ghost" data-action="logout" type="button">退出登录</button></div></div>`
    : `<div class="account-card"><div class="avatar">?</div><div class="account-meta"><h3>游客模式</h3><p>只能取 360P/480P，字幕与评论接口更易触发风控。</p></div><div class="account-side"><span class="tag warn">未登录</span></div></div>`;
  const qrImage = qr.image ? `<img src="${esc(qr.image)}" alt="B站登录二维码" />` : `<div class="empty">${qr.key ? "二维码图片不可用" : "点击生成登录二维码"}</div>`;
  const mask = qr.state === "confirmed" ? `<div class="mask">登录成功</div>` : qr.state === "expired" ? `<div class="mask">二维码已过期<br/>请刷新</div>` : qr.state === "error" ? `<div class="mask">${esc(qr.message || "登录失败")}</div>` : "";
  host.innerHTML = `<div class="login-grid">
    <div class="card"><div class="card-head"><div><h2>账号</h2><p>扫码凭据优先于配置中的手动 SESSDATA；退出登录会自动回退。</p></div><div class="card-actions">${loggedIn ? `<button class="btn small" data-action="start-login" type="button">重新扫码</button>` : ""}</div></div>${accountHtml}<div class="section-title">登录能带来什么</div><ul class="login-tips"><li><span class="tick">✓</span><span><b>更高画质</b>：1080P 截帧、技能卡、数字和结算界面更清楚。</span></li><li><span class="tick">✓</span><span><b>更稳的字幕/评论接口</b>：游客态常见 -101 / -352 风控。</span></li><li><span class="tick">✓</span><span><b>扫码凭据优先</b>：不会覆盖手动配置，退出后自动回退。</span></li><li><span class="tick">!</span><span><b>建议使用小号</b>：凭据以明文 JSON 保存在插件 data 目录，请勿分享。</span></li></ul></div>
    <div class="card"><div class="card-head"><div><h2>扫码登录</h2><p>使用哔哩哔哩手机客户端扫描。</p></div></div><div class="qr-panel"><div class="qr-frame">${qrImage}${mask}</div><div class="qr-status ${qr.state === "confirmed" ? "ok" : qr.state === "expired" || qr.state === "error" ? "warn" : ""}" id="qr-status">${esc(loginQrStatusText())}</div><button class="btn primary" data-action="start-login" type="button">${qr.key ? "刷新二维码" : "生成登录二维码"}</button>${qr.url ? `<div class="qr-url">${esc(qr.url)}</div><button class="btn small ghost" data-action="copy-url" type="button">复制登录链接</button>` : ""}</div></div>
  </div>`;
  host.querySelectorAll("[data-action]").forEach((node) => node.addEventListener("click", handleLoginAction));
}
function loginQrStatusText() {
  const qr = state.login;
  if (qr.state === "loading") return "正在申请二维码…";
  if (qr.state === "waiting") return `等待扫码 · 剩余 ${Math.max(0, Math.ceil(qr.expiresAt - Date.now() / 1000))}s`;
  if (qr.state === "scanned") return "已扫码，请在手机上确认";
  if (qr.state === "confirmed") return "登录成功";
  if (qr.state === "expired") return "二维码已过期，请刷新";
  if (qr.state === "error") return qr.message || "登录失败";
  return "点击下方按钮生成二维码";
}
async function handleLoginAction(event) {
  const action = event.currentTarget.dataset.action;
  if (action === "start-login") await startLogin();
  if (action === "copy-url") { copyText(state.login.url); toast("登录链接已复制"); }
  if (action === "logout") {
    if (!(await confirmDialog("退出扫码登录？", "只清除扫码凭据，配置里的手动 SESSDATA 会继续作为回退。", "退出登录"))) return;
    try {
      await apiPost("login/logout");
      state.login = { key: "", url: "", image: "", state: "idle", message: "", timer: null, countdown: null, expiresAt: 0 };
      await refreshAll(); toast("已退出扫码登录");
    } catch (error) { showAlert(`退出失败：${error.message}`); }
  }
}
async function startLogin() {
  stopLoginTimers();
  state.login = { ...state.login, state: "loading", message: "", image: "", key: "", url: "" };
  renderLogin();
  try {
    const result = await apiPost("login/qr");
    state.login.key = result.key || ""; state.login.url = result.url || ""; state.login.image = result.image || "";
    state.login.state = "waiting"; state.login.expiresAt = Date.now() / 1000 + Number(result.expires_in || 180);
    renderLogin();
    state.login.countdown = window.setInterval(() => {
      const node = $("#qr-status");
      if (node) node.textContent = loginQrStatusText();
      if (Date.now() / 1000 >= state.login.expiresAt) { state.login.state = "expired"; stopLoginTimers(); renderLogin(); }
    }, 1000);
    state.login.timer = window.setInterval(pollLogin, 2500);
  } catch (error) { state.login.state = "error"; state.login.message = error.message; renderLogin(); }
}
async function pollLogin() {
  if (!state.login.key) return;
  try {
    const result = await apiGet("login/status", { key: state.login.key });
    if (result.state === "confirmed") {
      stopLoginTimers(); state.login.state = "confirmed"; renderLogin(); toast("登录成功"); await refreshAll();
    } else if (result.state === "expired" || result.state === "error") {
      stopLoginTimers(); state.login.state = result.state; state.login.message = result.message || ""; renderLogin();
    } else if (result.state === "scanned") { state.login.state = "scanned"; renderLogin(); }
  } catch { /* 下一轮再试 */ }
}

async function loadVideos() {
  try { state.videos = (await apiGet("videos", { limit: 200 })).rows || []; renderOverview(); renderVideos(); }
  catch (error) { showAlert(`视频记录加载失败：${error.message}`); }
}
function renderVideos() {
  const host = $("#view-videos");
  host.innerHTML = `<div class="card"><div class="card-head"><div><h2>视频记录</h2><p>点击任意一行查看笔记、帧预算与原文。</p></div><div class="card-actions"><button class="btn small ghost" data-action="refresh-videos" type="button">刷新</button></div></div>${renderVideoTable(state.videos)}</div>`;
  host.querySelector("[data-action='refresh-videos']")?.addEventListener("click", loadVideos);
  host.querySelectorAll("[data-bvid]").forEach((row) => row.addEventListener("click", () => openDetail(row.dataset.bvid, row.dataset.page)));
}
async function openDetail(bvid, page) {
  showView("detail");
  $("#page-title").textContent = "视频详情"; $("#page-desc").textContent = `${bvid} · P${page}`;
  try {
    const data = await apiGet("video", { bvid, page }); state.detail = data;
    $("#detail-body").innerHTML = renderDetailContent(data); bindDetailActions();
  } catch (error) { $("#detail-body").innerHTML = `<div class="card"><div class="empty">${esc(error.message)}</div></div>`; }
}
function renderDetail() {
  const host = $("#view-detail");
  if (!host.innerHTML) host.innerHTML = `<div id="detail-body"><div class="card"><div class="empty">选择一条视频记录查看详情</div></div></div>`;
}
function renderDetailContent(data) {
  const video = data.video || {}; const meta = data.meta || {}; const note = data.note || {};
  const tracks = data.transcript?.tracks || [];
  return `<div class="card"><div class="card-head"><div><h2>${esc(video.title || "（无标题）")}</h2><p>${esc(video.bvid || "")} · P${esc(video.page || 1)} · ${esc(modeLabel(meta.mode))}${tracks.length ? ` · 字幕 ${tracks.map((track) => esc(track.lang_doc || track.origin)).join(" / ")}` : ""}</p></div><div class="card-actions"><button class="btn small ghost" data-action="back-videos" type="button">返回视频记录</button></div></div><div class="tabs"><button class="tab active" data-tab="core" type="button">核心笔记</button><button class="tab" data-tab="other" type="button">其他客观内容</button><button class="tab" data-tab="plan" type="button">帧预算</button><button class="tab" data-tab="raw" type="button">原文</button></div><pre class="pre output" data-panel="core">${esc(note.core || "暂无核心笔记")}</pre><pre class="pre output" data-panel="other" hidden>${esc(note.other || "暂无其他客观内容")}</pre><pre class="pre output" data-panel="plan" hidden>${esc(meta.frame_plan ? JSON.stringify(meta.frame_plan, null, 2) : "暂无帧预算记录")}</pre><div data-panel="raw" hidden><div class="toolbar"><label class="field"><span>关键词</span><input id="detail-query" type="search" placeholder="关键词或原话片段" /></label><label class="field"><span>来源</span><select id="detail-source"><option value="both">全部来源</option><option value="official">官方</option><option value="ai">B站 AI</option><option value="ocr">内嵌 OCR</option><option value="asr">ASR</option></select></label><label class="field"><span>语言</span><select id="detail-lang"><option value="">全部</option><option value="zh">中文</option><option value="en">English</option></select></label><button class="btn" data-action="detail-search" type="button">查询</button></div><pre class="pre output" id="detail-raw-result">输入关键词查询原文。</pre></div></div>`;
}
function bindDetailActions() {
  const host = $("#view-detail");
  host.querySelectorAll("[data-tab]").forEach((tab) => tab.addEventListener("click", () => {
    host.querySelectorAll("[data-tab]").forEach((node) => node.classList.toggle("active", node === tab));
    host.querySelectorAll("[data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== tab.dataset.tab; });
  }));
  host.querySelector("[data-action='back-videos']")?.addEventListener("click", () => showView("videos"));
  host.querySelector("[data-action='detail-search']")?.addEventListener("click", async () => {
    const data = state.detail; if (!data?.video) return;
    try {
      const result = await apiGet("transcript", { bvid: data.video.bvid, page: data.video.page, query: $("#detail-query").value, source: $("#detail-source").value, lang: $("#detail-lang").value, limit: 20 });
      $("#detail-raw-result").textContent = result.text || "没有结果";
    } catch (error) { $("#detail-raw-result").textContent = `查询失败：${error.message}`; }
  });
}

async function loadTranscriptVideos() {
  try { state.videos = (await apiGet("videos", { limit: 200 })).rows || []; renderTranscript(); }
  catch (error) { showAlert(`视频列表加载失败：${error.message}`); }
}
function renderTranscript() {
  const host = $("#view-transcript");
  const options = state.videos.map((item) => `<option value="${esc(item.bvid)}|${esc(item.page || 1)}">${esc(item.title || item.bvid)} · P${esc(item.page || 1)}</option>`).join("") || `<option value="">暂无视频记录</option>`;
  host.innerHTML = `<div class="card"><div class="card-head"><div><h2>原文检索</h2><p>直接读取官方、B站 AI、内嵌 OCR 与 ASR 字幕，不经过子代理。</p></div></div><div class="toolbar"><label class="field"><span>视频</span><select id="tr-video">${options}</select></label><label class="field"><span>关键词</span><input id="tr-query" type="search" placeholder="原话或关键词" /></label><label class="field"><span>来源</span><select id="tr-source"><option value="both">全部来源</option><option value="official">官方</option><option value="ai">B站 AI</option><option value="ocr">内嵌 OCR</option><option value="asr">ASR</option></select></label><label class="field"><span>语言</span><select id="tr-lang"><option value="">全部</option><option value="zh">中文</option><option value="en">English</option></select></label><label class="field time"><span>起</span><input id="tr-start" type="number" min="0" placeholder="秒" /></label><label class="field time"><span>止</span><input id="tr-end" type="number" min="0" placeholder="秒" /></label><button class="btn primary" id="tr-search" type="button">查询</button></div><pre class="pre output" id="tr-result">选择视频并输入关键词，或指定时间范围。</pre></div>`;
  $("#tr-search").addEventListener("click", async () => {
    const selected = $("#tr-video").value.split("|"); if (!selected[0]) return;
    try {
      const result = await apiGet("transcript", { bvid: selected[0], page: Number(selected[1] || 1), query: $("#tr-query").value, source: $("#tr-source").value, lang: $("#tr-lang").value, start: $("#tr-start").value || 0, end: $("#tr-end").value || 0, limit: 20 });
      $("#tr-result").textContent = result.text || "没有结果";
    } catch (error) { $("#tr-result").textContent = `查询失败：${error.message}`; }
  });
}

async function loadCachePage() {
  try { state.cache = await apiGet("cache"); renderCache(); }
  catch (error) { showAlert(`缓存读取失败：${error.message}`); }
}
function renderCache() {
  const host = $("#view-cache");
  const cache = state.cache || {};
  const rows = [["笔记", cache.notes], ["原文", cache.transcripts], ["帧", cache.frames]];
  const total = Math.max(1, rows.reduce((sum, [, item]) => sum + Number(item?.bytes || 0), 0));
  host.innerHTML = `<div class="cache-grid">${rows.map(([label, item]) => `<div class="stat"><div class="k">${esc(label)}</div><div class="v">${fmtBytes(item?.bytes)}</div><div class="s">${item?.count || 0} 个文件</div></div>`).join("")}</div><div class="card"><div class="card-head"><div><h2>缓存清理</h2><p>清理不可恢复；有视频处理中时不会清理帧缓存。</p></div></div>${rows.map(([label, item]) => `<div class="cache-row"><b>${esc(label)}</b><div class="cache-bar"><span style="width:${Math.round((Number(item?.bytes || 0) / total) * 100)}%"></span></div><button class="btn small danger" data-clean="${esc(label === "笔记" ? "notes" : label === "原文" ? "transcripts" : "frames")}" type="button">清理</button></div>`).join("")}<div style="display:flex;justify-content:flex-end;margin-top:14px"><button class="btn danger" data-clean="all" type="button">清理全部</button></div></div>`;
  host.querySelectorAll("[data-clean]").forEach((button) => button.addEventListener("click", async () => {
    const kind = button.dataset.clean;
    if (!(await confirmDialog("确认清理缓存？", "清理后不可恢复。", "清理"))) return;
    try { const result = await apiPost("cache/cleanup", { kind }); toast(`已清理 ${JSON.stringify(result.removed || {})}`); await loadCachePage(); await refreshAll(); }
    catch (error) { showAlert(`清理失败：${error.message}`); }
  }));
}

async function loadDiagnostics() {
  try { state.diagnostics = await apiGet("diagnostics"); renderDiagnostics(); }
  catch (error) { showAlert(`诊断读取失败：${error.message}`); }
}
function renderDiagnostics() {
  const host = $("#view-diagnostics");
  const data = state.diagnostics || {}; const status = state.status || {};
  host.innerHTML = `<div class="card"><div class="card-head"><div><h2>运行诊断</h2><p>排查优先看这里；不展示凭据。</p></div><div class="card-actions"><button class="btn small ghost" data-copy="${esc(JSON.stringify(data))}" type="button">复制诊断 JSON</button></div></div><dl class="kv"><dt>插件版本</dt><dd>v${esc(status.version || "—")}</dd><dt>数据目录</dt><dd><code>${esc(status.data_dir || "—")}</code></dd><dt>模式</dt><dd>${esc(modeLabel(status.video_mode))}</dd><dt>登录</dt><dd>${status.login?.logged_in ? "已登录" : "游客"}</dd><dt>OCR</dt><dd>${status.ocr?.enabled ? "已启用" : "未启用"}</dd><dt>已注册接口</dt><dd>${(status.registered_apis || []).length} 个</dd><dt>笔记数</dt><dd>${esc(data.notes ?? "—")}</dd><dt>原文数</dt><dd>${esc(data.transcripts ?? "—")}</dd></dl>${data.recent?.length ? `<div class="section-title">最近记录</div><div class="table-wrap"><table class="table"><thead><tr><th>BV</th><th>模式</th><th>时间</th></tr></thead><tbody>${data.recent.map((item) => `<tr><td><code>${esc(item.bvid)}</code></td><td>${esc(modeLabel(item.mode))}</td><td>${esc(item.created ? new Date(item.created * 1000).toLocaleString() : "—")}</td></tr>`).join("")}</tbody></table></div>` : ""}</div>`;
  host.querySelectorAll("[data-copy]").forEach((button) => button.addEventListener("click", () => { copyText(button.dataset.copy); toast("已复制"); }));
}

boot();
