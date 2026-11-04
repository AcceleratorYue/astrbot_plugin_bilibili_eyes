const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;

const state = {
  overview: {},
  videos: [],
  selected: null,
  detail: null,
  config: {},
  diagnostics: {},
};

const $ = (id) => document.getElementById(id);
const MODE_LABEL = { normal: "普通", enhanced: "增强", extreme: "极致", "": "未记录" };
const STATUS_LABEL = {
  available: "可用",
  absent: "无",
  failed: "失败",
  disabled: "未启用",
  skipped: "已跳过",
  not_configured: "未配置",
  empty: "空",
  no_audio: "无音轨",
  unknown: "未知",
};

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fmtTime(timestamp) {
  if (!timestamp) return "—";
  const date = new Date(Number(timestamp) * 1000);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function modeLabel(mode) {
  return MODE_LABEL[mode] || mode || "—";
}

function statusTag(value) {
  const label = STATUS_LABEL[value] || value || "未知";
  const tone = value === "available" ? "ok" : ["failed", "empty", "no_audio"].includes(value) ? "bad" : ["absent", "not_configured", "skipped"].includes(value) ? "warn" : "";
  return `<span class="tag ${tone}">${esc(label)}</span>`;
}

async function requestFallback(endpoint, params = {}, body = null) {
  const url = new URL(`/astrbot_plugin_bilibili_eyes/${endpoint}`, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  });
  const response = await fetch(url, {
    credentials: "include",
    method: body === null ? "GET" : "POST",
    headers: body === null ? {} : { "Content-Type": "application/json" },
    body: body === null ? undefined : JSON.stringify(body),
  });
  let result = {};
  try { result = await response.json(); } catch { result = {}; }
  if (!response.ok || result?.success === false) {
    throw new Error(result?.error || `HTTP ${response.status}`);
  }
  return result;
}

async function apiGet(endpoint, params = {}) {
  if (!bridge) throw new Error("AstrBot 插件页桥接未注入");
  const result = bridge.apiGet
    ? await bridge.apiGet(endpoint, params)
    : await requestFallback(endpoint, params);
  if (result?.success === false) throw new Error(result.error || "请求失败");
  return result || {};
}

async function apiPost(endpoint, body = {}) {
  if (!bridge) throw new Error("AstrBot 插件页桥接未注入");
  const result = bridge.apiPost
    ? await bridge.apiPost(endpoint, body)
    : await requestFallback(endpoint, {}, body);
  if (result?.success === false) throw new Error(result.error || "请求失败");
  return result || {};
}

function showError(message) {
  $("globalErrorText").textContent = message || "加载失败";
  $("globalError").hidden = false;
}

function hideError() {
  $("globalError").hidden = true;
}

function setTitle(title, subtitle) {
  $("pageTitle").textContent = title;
  $("pageSubtitle").textContent = subtitle || "";
}

function showView(name) {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  document.querySelectorAll(".view").forEach((item) => item.classList.toggle("active", item.id === `view-${name}`));
}

function renderOverview(data) {
  const overview = data.overview || {};
  state.overview = overview;
  $("versionLabel").textContent = `v${overview.version || "0.11.0"}`;
  $("modeBadge").textContent = `模式：${modeLabel(overview.video_mode)}`;
  const cards = [
    ["视频记录", overview.counts?.videos ?? 0, "有笔记或原文的视频"],
    ["笔记缓存", overview.notes?.count ?? 0, `${(overview.notes?.bytes || 0) / 1024 | 0} KB`],
    ["原文缓存", overview.transcripts?.count ?? 0, `${(overview.transcripts?.bytes || 0) / 1024 | 0} KB`],
    ["帧缓存", overview.frames?.count ?? 0, `${(overview.frames?.bytes || 0) / 1024 | 0} KB`],
  ];
  $("overviewCards").innerHTML = cards.map(([label, value, sub]) => `
    <div class="card"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="sub">${esc(sub)}</div></div>
  `).join("");

  const last = overview.last_video;
  $("recentVideo").classList.remove("empty");
  if (!last) {
    $("recentVideo").textContent = "暂无观看记录";
    $("recentVideo").classList.add("empty");
  } else {
    $("recentVideo").innerHTML = `
      <div class="kv">
        <span class="k">标题</span><span>${esc(last.title || "（无标题）")}</span>
        <span class="k">BV / 分P</span><span>${esc(last.bvid)} / ${esc(last.page)}</span>
        <span class="k">模式</span><span>${esc(modeLabel(last.mode))}</span>
        <span class="k">观看时间</span><span>${esc(fmtTime(last.created))}</span>
        <span class="k">帧数</span><span>${esc(last.frames || 0)}</span>
        <span class="k">文本</span><span>官方 ${statusTag(last.official_status)} · ASR ${statusTag(last.asr_status)}</span>
        <span class="k">操作</span><span><button class="link-btn" data-open="${esc(last.bvid)}|${esc(last.page)}" type="button">查看详情 →</button></span>
      </div>`;
    const button = $("recentVideo").querySelector("[data-open]");
    button?.addEventListener("click", () => openDetail(last.bvid, last.page));
  }
}

function renderVideos(rows) {
  state.videos = rows;
  $("videoCount").textContent = `${rows.length} 条`;
  const body = $("videoRows");
  body.innerHTML = rows.map((item) => `
    <tr data-bvid="${esc(item.bvid)}" data-page="${esc(item.page)}">
      <td>${esc(fmtTime(item.created))}</td>
      <td>${esc(item.title || "（无标题）")}</td>
      <td>${esc(item.bvid)}<br><span class="muted">P${esc(item.page)}</span></td>
      <td><span class="tag">${esc(modeLabel(item.mode))}</span></td>
      <td>${esc(item.frames || 0)}</td>
      <td>${esc(item.core_chars || 0)} / ${esc(item.other_chars || 0)}</td>
      <td>${statusTag(item.official_status)}<br>${statusTag(item.asr_status)}</td>
    </tr>`).join("");
  $("videoEmpty").hidden = rows.length > 0;
  body.querySelectorAll("tr[data-bvid]").forEach((row) => {
    row.addEventListener("click", () => openDetail(row.dataset.bvid, Number(row.dataset.page || 1)));
  });
}

async function loadOverview() {
  try {
    const data = await apiGet("overview");
    renderOverview(data);
  } catch (error) {
    showError(`概览：${error.message}`);
  }
}

async function loadVideos() {
  try {
    const query = $("videoSearch").value.trim();
    const mode = $("videoMode").value;
    const data = await apiGet("videos", { q: query, mode, limit: 200 });
    renderVideos(data.rows || []);
    populateTranscriptVideos(data.rows || []);
  } catch (error) {
    showError(`视频记录：${error.message}`);
  }
}

function populateTranscriptVideos(rows) {
  if (!rows.length) {
    $("transcriptVideo").innerHTML = '<option value="">暂无视频</option>';
    return;
  }
  const current = $("transcriptVideo").value;
  $("transcriptVideo").innerHTML = rows.map((item) => (
    `<option value="${esc(item.bvid)}|${esc(item.page)}">${esc(item.title || item.bvid)} · P${esc(item.page)}</option>`
  )).join("");
  if (current && [...$("transcriptVideo").options].some((opt) => opt.value === current)) {
    $("transcriptVideo").value = current;
  }
}

async function openDetail(bvid, page) {
  showView("detail");
  setTitle("视频详情", "核心笔记、其他内容、帧预算和原文。");
  $("detailTitle").textContent = `${bvid} · P${page}`;
  $("detailCore").textContent = "加载中…";
  try {
    const data = await apiGet("video", { bvid, page });
    state.detail = data;
    const title = data.video?.title || "（无标题）";
    $("detailTitle").textContent = title;
    $("detailMeta").textContent = `${bvid} · P${page} · ${modeLabel(data.meta?.mode)} · ${fmtTime(data.video?.created)}`;
    $("detailCore").textContent = data.note?.core || "暂无核心笔记";
    $("detailOther").textContent = data.note?.other || "暂无其他客观内容";
    $("detailPlan").textContent = data.meta?.frame_plan
      ? JSON.stringify(data.meta.frame_plan, null, 2)
      : "暂无帧预算记录";
    $("detailRawResult").textContent = "输入关键词查询原文。";
    selectDetailTab("core");
  } catch (error) {
    $("detailCore").textContent = `加载失败：${error.message}`;
  }
}

function selectDetailTab(tab) {
  document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item.dataset.tab === tab));
  const map = { core: "detailCore", other: "detailOther", plan: "detailPlan", raw: "detailRaw" };
  Object.entries(map).forEach(([key, id]) => $(id).hidden = key !== tab);
}

async function searchTranscript(bvid, page, query, source, start, end) {
  return apiGet("transcript", {
    bvid,
    page,
    query,
    source,
    start: start || 0,
    end: end || 0,
    limit: 20,
  });
}

async function loadCache() {
  try {
    const data = await apiGet("cache-summary");
    const cards = [
      ["笔记", data.notes],
      ["原文", data.transcripts],
      ["帧", data.frames],
    ];
    $("cacheCards").innerHTML = cards.map(([label, item]) => `
      <div class="card"><div class="label">${esc(label)}</div><div class="value">${esc(item?.count || 0)}</div><div class="sub">${esc(((item?.bytes || 0) / 1024).toFixed(1))} KB</div></div>
    `).join("");
  } catch (error) {
    showError(`缓存：${error.message}`);
  }
}

async function loadConfig() {
  try {
    const data = await apiGet("config");
    state.config = data.groups || {};
    const labelMap = {
      basic: "基础与触发", bilibili: "B站连接", vision: "画面与模式",
      enhanced: "增强模式", extreme: "极致模式", audio: "音频转录",
      content: "内容采集", prompts: "提示词", runtime: "缓存与性能", waiting: "等待与反馈",
    };
    $("configGroups").innerHTML = Object.entries(state.config).map(([group, values]) => {
      const rows = Object.entries(values).map(([key, value]) => {
        let text = value;
        if (typeof value === "object") text = JSON.stringify(value);
        if (typeof value === "boolean") text = value ? "开" : "关";
        if (value === "") text = "空";
        return `<div class="config-row"><span class="k">${esc(key)}</span><span class="v">${esc(text)}</span></div>`;
      }).join("");
      return `<div class="config-group"><h3>${esc(labelMap[group] || group)}</h3>${rows}</div>`;
    }).join("");
  } catch (error) {
    showError(`配置：${error.message}`);
  }
}

async function loadDiagnostics() {
  try {
    const data = await apiGet("diagnostics");
    state.diagnostics = data;
    $("diagnosticsContent").innerHTML = `
      <span class="k">当前模式</span><span>${esc(modeLabel(data.mode))}</span>
      <span class="k">笔记缓存</span><span>${esc(data.notes || 0)} 条</span>
      <span class="k">原文缓存</span><span>${esc(data.transcripts || 0)} 条</span>
      <span class="k">最近记录</span><span>${(data.recent || []).length} 条</span>`;
  } catch (error) {
    showError(`诊断：${error.message}`);
  }
}

async function cleanup(kind) {
  if (!window.confirm(`确认清理“${kind}”缓存？此操作不可恢复。`)) return;
  try {
    const data = await apiPost("cache-cleanup", { kind });
    $("cleanupResult").hidden = false;
    $("cleanupResult").textContent = `已清理：${JSON.stringify(data.removed || {})}`;
    await loadCache();
    await loadOverview();
  } catch (error) {
    showError(`清理：${error.message}`);
  }
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      const view = item.dataset.view;
      showView(view);
      if (view === "overview") { setTitle("概览", "最近观看、笔记与原文状态。"); loadOverview(); }
      if (view === "videos") { setTitle("视频记录", "按时间查看最近观看。"); loadVideos(); }
      if (view === "transcript") { setTitle("原文检索", "直接读取官方字幕和 ASR 原文。"); loadVideos(); }
      if (view === "cache") { setTitle("缓存管理", "查看与清理笔记、原文和帧缓存。"); loadCache(); }
      if (view === "diagnostics") { setTitle("诊断", "模式、缓存与最近记录。"); loadDiagnostics(); }
      if (view === "settings") { setTitle("配置摘要", "完整配置请到 AstrBot 插件配置页修改。"); loadConfig(); }
    });
  });

  $("refreshBtn").addEventListener("click", () => window.location.reload());
  $("retryBtn").addEventListener("click", () => { hideError(); loadOverview(); loadVideos(); });
  $("videoSearch").addEventListener("input", () => { clearTimeout(window.__searchTimer); window.__searchTimer = setTimeout(loadVideos, 300); });
  $("videoMode").addEventListener("change", loadVideos);
  $("backToVideos").addEventListener("click", () => { showView("videos"); setTitle("视频记录", "按时间查看最近观看。"); loadVideos(); });
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => selectDetailTab(tab.dataset.tab)));
  $("transcriptSearchBtn").addEventListener("click", async () => {
    const selected = $("transcriptVideo").value;
    if (!selected) return;
    const [bvid, page] = selected.split("|");
    try {
      const data = await searchTranscript(bvid, Number(page), $("transcriptQuery").value.trim(), $("transcriptSource").value, $("transcriptStart").value, $("transcriptEnd").value);
      $("transcriptResult").textContent = data.text || "没有结果";
    } catch (error) {
      $("transcriptResult").textContent = `查询失败：${error.message}`;
    }
  });
  $("detailRawSearch").addEventListener("click", async () => {
    if (!state.detail?.video) return;
    const bvid = state.detail.video.bvid;
    const page = state.detail.video.page;
    try {
      const data = await searchTranscript(bvid, page, $("detailRawQuery").value.trim(), $("detailRawSource").value, 0, 0);
      $("detailRawResult").textContent = data.text || "没有结果";
    } catch (error) {
      $("detailRawResult").textContent = `查询失败：${error.message}`;
    }
  });
  document.querySelectorAll("[data-clean]").forEach((button) => button.addEventListener("click", () => cleanup(button.dataset.clean)));
}

async function init() {
  bindEvents();
  try {
    if (bridge?.ready) await bridge.ready();
    await Promise.all([loadOverview(), loadVideos()]);
    setTitle("概览", "最近观看、笔记与原文状态。");
  } catch (error) {
    showError(`初始化失败：${error.message}`);
  }
}

init();
