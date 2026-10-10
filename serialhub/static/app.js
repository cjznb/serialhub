/* =============================================================================
   serialhub Web UI — vanilla JS, no build step, no npm.
   Sections:
     1. utilities            6. terminal / panes / rendering
     2. state                7. stats (rates + sparkline)
     3. toasts               8. websocket bus
     4. API client           9. filter + search
     5. theme               10. sendbar + export + toolbar wiring + init
   ========================================================================== */
"use strict";

/* 1. utilities ============================================================= */
const ANSI_RE = /\x1b\[[0-9;?]*[ -\/]*[@-~]|\x1b[@-Z\\-_]/g;
const encoder = new TextEncoder();

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.prototype.slice.call((root || document).querySelectorAll(sel));

const stripAnsi = (s) => String(s == null ? "" : s).replace(ANSI_RE, "");
const byteLen = (s) => encoder.encode(s || "").length;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function fmtTime(ms) {
  const d = new Date(ms || Date.now());
  const p2 = (n) => String(n).padStart(2, "0");
  const p3 = (n) => String(n).padStart(3, "0");
  return `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}.${p3(d.getMilliseconds())}`;
}
function fmtBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + "B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + "K";
  if (n < 1024 * 1024 * 1024) return (n / 1048576).toFixed(1) + "M";
  return (n / 1073741824).toFixed(1) + "G";
}
function fmtRate(n) { return n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(Math.round(n)); }
function fmtDuration(ms) {
  const s = Math.floor((ms || 0) / 1000);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60), ss = s % 60;
  if (d) return `${d}d${h}h`;
  if (h) return `${h}h${m}m`;
  if (m) return `${m}m${ss}s`;
  return `${ss}s`;
}
function compileRe(pattern) {
  if (!pattern) return null;
  try { return new RegExp(pattern, "i"); } catch (_e) { return null; }
}
function safeGet(key, fallback) {
  try { const v = localStorage.getItem(key); return v == null ? fallback : v; } catch (_e) { return fallback; }
}
function safeSet(key, val) {
  try { localStorage.setItem(key, val); } catch (_e) { /* storage disabled */ }
}

/* 1b. i18n ================================================================ */
/* Dependency-free dictionary + t(key, vars) with {var} interpolation.
   Fallback chain: active lang -> en -> key itself. */
const I18N = {
  en: {
    docTitle: "serialhub · serial console",
    brandSub: "persistent serial hub",
    statsAria: "server stats",
    statPorts: "ports",
    statOpen: "open",
    statUptime: "uptime",
    connIdle: "idle",
    connConnecting: "connecting\u2026",
    connLive: "live",
    connError: "disconnected",
    connReconnecting: "reconnecting\u2026",
    connUnauthorized: "unauthorized",
    tokenLabel: "token",
    tokenTitle: "Bearer token \u2014 set if the server requires auth",
    tokenPlaceholder: "optional",
    langAria: "Language",
    themeTitle: "Toggle light / dark theme",
    themeAria: "Toggle theme",
    tabsAria: "serial ports",
    bannerStrong: "xterm.js could not be loaded.",
    bannerText: " Running in degraded mode: output is shown as plain text with ANSI color codes stripped. Check your connection, then reload.",
    pauseTitle: "Pause / resume live rendering",
    pause: "Pause",
    resume: "Resume",
    autoTitle: "Toggle autoscroll to newest line",
    autoLabel: "Autoscroll",
    tsTitle: "Toggle per-line timestamp",
    tsLabel: "Time",
    clearTitle: "Clear the local view",
    clearLabel: "Clear",
    filterTitle: "Client-side regex filter over incoming lines",
    filterLabel: "filter",
    filterPlaceholder: "regex, e.g. error|warn",
    searchTitle: "Search retained lines \u2014 Enter to run, then jump between hits",
    searchLabel: "search",
    searchPlaceholder: "regex",
    prevTitle: "Previous hit",
    nextTitle: "Next hit",
    histTitle: "Search full server history",
    histLabel: "hist",
    exportGroupTitle: "Export this port's buffer (server-side)",
    exportRaw: "raw",
    exportNoansi: "noansi",
    exportJson: "json",
    sendPortTitle: "Target port",
    sendPortAria: "Target port",
    sendPlaceholder: "type a command to send\u2026  (Enter to send \u00b7 Up/Down for history)",
    eolTitle: "Line ending appended on send",
    eolAria: "Line ending",
    eolCrlf: "EOL: CRLF",
    eolLf: "EOL: LF",
    eolCr: "EOL: CR",
    eolNone: "EOL: none",
    send: "Send",
    state_closed: "closed",
    state_open: "open",
    state_reconnecting: "reconnecting",
    state_error: "error",
    rateLines: "lines/s",
    rateBytes: "B/s",
    buffer: "buffer",
    bufHint: "{n} lines / {bytes}",
    markLine: "\u2500\u2500 mark: {label} \u2500\u2500",
    toastDismiss: "Dismiss",
    toastNetworkError: "Network error: {msg}",
    toastUnauthorized: "Unauthorized \u2014 set the token in the top bar.",
    toastWsUnauthorized: "WebSocket unauthorized \u2014 set the token in the top bar.",
    toastWsError: "WebSocket error: {msg}",
    toastTokenUpdated: "Token updated \u2014 reconnecting.",
    toastResumed: "Resumed.",
    toastPaused: "Paused \u2014 new lines are buffered.",
    toastExported: "Exported {n} lines ({fmt}) \u2192 {file}",
    toastNoMatches: "No matches in server history.",
    toastOutsideBuffer: "Line #{seq} is outside the local buffer.",
  },
  zh: {
    docTitle: "serialhub · 串口控制台",
    brandSub: "常驻串口中枢",
    statsAria: "服务端统计",
    statPorts: "端口",
    statOpen: "已开",
    statUptime: "运行时长",
    connIdle: "空闲",
    connConnecting: "连接中\u2026",
    connLive: "已连接",
    connError: "已断开",
    connReconnecting: "重连中\u2026",
    connUnauthorized: "未授权",
    tokenLabel: "令牌",
    tokenTitle: "Bearer 令牌 \u2014 服务端要求鉴权时填写",
    tokenPlaceholder: "可选",
    langAria: "语言",
    themeTitle: "切换浅色 / 深色主题",
    themeAria: "切换主题",
    tabsAria: "串口",
    bannerStrong: "xterm.js 加载失败。",
    bannerText: " 已进入降级模式：输出以纯文本显示，ANSI 颜色码被去除。请检查网络后重新加载。",
    pauseTitle: "暂停 / 恢复实时渲染",
    pause: "暂停",
    resume: "继续",
    autoTitle: "自动滚动到最新行",
    autoLabel: "自动滚动",
    tsTitle: "每行时间戳开关",
    tsLabel: "时间戳",
    clearTitle: "清空本地视图",
    clearLabel: "清屏",
    filterTitle: "对进入的行做客户端正则过滤",
    filterLabel: "过滤",
    filterPlaceholder: "正则，如 error|warn",
    searchTitle: "搜索已保留的行 \u2014 回车执行，然后在各命中间跳转",
    searchLabel: "搜索",
    searchPlaceholder: "正则",
    prevTitle: "上一个命中",
    nextTitle: "下一个命中",
    histTitle: "搜索服务端全历史",
    histLabel: "全历史",
    exportGroupTitle: "导出该口缓冲（服务端）",
    exportRaw: "原样",
    exportNoansi: "纯文本",
    exportJson: "json",
    sendPortTitle: "目标端口",
    sendPortAria: "目标端口",
    sendPlaceholder: "输入要发送的命令\u2026（回车发送 \u00b7 ↑/↓ 翻阅历史）",
    eolTitle: "发送时追加的行结束符",
    eolAria: "行结束符",
    eolCrlf: "结束符: CRLF",
    eolLf: "结束符: LF",
    eolCr: "结束符: CR",
    eolNone: "结束符: 无",
    send: "发送",
    state_closed: "已关闭",
    state_open: "已连接",
    state_reconnecting: "重连中",
    state_error: "错误",
    rateLines: "线/秒",
    rateBytes: "字节/秒",
    buffer: "缓冲",
    bufHint: "{n} 行 / {bytes}",
    markLine: "\u2500\u2500 标记: {label} \u2500\u2500",
    toastDismiss: "关闭",
    toastNetworkError: "网络错误：{msg}",
    toastUnauthorized: "未授权 \u2014 请在顶栏填写令牌。",
    toastWsUnauthorized: "WebSocket 未授权 \u2014 请在顶栏填写令牌。",
    toastWsError: "WebSocket 错误：{msg}",
    toastTokenUpdated: "令牌已更新 \u2014 正在重连。",
    toastResumed: "已继续。",
    toastPaused: "已暂停 \u2014 新行将进入缓冲。",
    toastExported: "已导出 {n} 行（{fmt}）\u2192 {file}",
    toastNoMatches: "服务端历史中无匹配。",
    toastOutsideBuffer: "第 #{seq} 行不在本地缓冲内。",
  },
};

function t(key, vars) {
  const dict = I18N[state.lang] || I18N.en;
  let s = dict[key];
  if (s == null) s = I18N.en[key];
  if (s == null) s = key;
  if (vars) {
    s = s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] == null ? m : String(vars[k])));
  }
  return s;
}

function detectLang() {
  const saved = safeGet("serialhub.lang", "");
  if (saved === "en" || saved === "zh") return saved;
  const list = (navigator.languages && navigator.languages.length)
    ? navigator.languages : [navigator.language || "en"];
  return String(list[0] || "").toLowerCase().startsWith("zh") ? "zh" : "en";
}

/* Re-apply all static text to the DOM subtree rooted at `root` (default doc).
   data-i18n -> textContent, data-i18n-title -> title,
   data-i18n-aria -> aria-label, data-i18n-ph -> placeholder. */
function applyI18n(root) {
  root = root || document;
  $$("[data-i18n]", root).forEach((el) => { el.textContent = t(el.getAttribute("data-i18n")); });
  $$("[data-i18n-title]", root).forEach((el) => { el.title = t(el.getAttribute("data-i18n-title")); });
  $$("[data-i18n-aria]", root).forEach((el) => el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria"))));
  $$("[data-i18n-ph]", root).forEach((el) => { el.placeholder = t(el.getAttribute("data-i18n-ph")); });
}

/* 2. state ================================================================= */
const state = {
  config: null,
  ports: new Map(),        // name -> server-side port summary
  runtimes: new Map(),     // name -> client runtime (terminal + buffers)
  active: null,
  ws: null,
  wsBackoff: 500,
  wsBackoffMax: 12000,
  wsTimer: null,
  wsState: "idle",
  token: safeGet("serialhub.token", ""),
  theme: safeGet("serialhub.theme", ""),
  lang: detectLang(),
  timestamp: safeGet("serialhub.timestamp", "") !== "false",
  autoscroll: safeGet("serialhub.autoscroll", "") !== "false",
  paused: false,
  maxRenderLines: 5000,
  termFallback: false,
  sendHistory: [],
  sendIndex: -1,
};

/* 3. toasts ================================================================ */
const toastHost = () => $("#toasts");
function toast(message, kind, ttl) {
  const el = document.createElement("div");
  el.className = "toast " + (kind || "info");
  el.innerHTML = `<span class="t-msg">${escapeHtml(message)}</span>`;
  const close = document.createElement("button");
  close.className = "t-close";
  close.textContent = "\u00d7";
  close.setAttribute("aria-label", t("toastDismiss"));
  close.addEventListener("click", () => dismiss());
  el.appendChild(close);
  function dismiss() {
    el.classList.add("out");
    setTimeout(() => el.remove(), 200);
  }
  toastHost().appendChild(el);
  setTimeout(dismiss, ttl || (kind === "error" ? 8000 : 4000));
}

/* 4. API client ============================================================ */
function apiUrl(path, params) {
  const u = new URL(path, location.origin);
  if (params) {
    for (const k of Object.keys(params)) {
      const v = params[k];
      if (v === undefined || v === null || v === "") continue;
      u.searchParams.set(k, String(v));
    }
  }
  return u.toString();
}
async function api(method, path, opts) {
  opts = opts || {};
  const headers = {};
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const init = { method, headers };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(apiUrl(path, opts.params), init);
  } catch (e) {
    toast(t("toastNetworkError", { msg: e.message }), "error");
    return { ok: false, error: String(e) };
  }
  let data;
  try { data = await res.json(); } catch (_e) { data = { ok: false, error: "invalid JSON (HTTP " + res.status + ")" }; }
  if (!data.ok) {
    const msg = data.error || ("HTTP " + res.status);
    if (res.status === 401) toast(t("toastUnauthorized"), "error");
    else toast(msg, "error");
  }
  return data;
}

/* 5. theme ================================================================= */
const XTERM_THEME = {
  dark: {
    background: "#0b0d11", foreground: "#e8edf3", cursor: "#e8834a", cursorAccent: "#0b0d11",
    selectionBackground: "rgba(232,131,74,0.28)",
    black: "#1a1f28", red: "#ef6d6d", green: "#4fd1b0", yellow: "#e6b34a",
    blue: "#6aa6f5", magenta: "#c792ea", cyan: "#4fd1b0", white: "#c9d1dc",
    brightBlack: "#66707e", brightRed: "#ff8787", brightGreen: "#6ee7c8", brightYellow: "#f3ce74",
    brightBlue: "#8bbcf7", brightMagenta: "#d9abf5", brightCyan: "#6ee7c8", brightWhite: "#ffffff",
  },
  light: {
    background: "#ffffff", foreground: "#1b1f26", cursor: "#cf5a1e", cursorAccent: "#ffffff",
    selectionBackground: "rgba(207,90,30,0.20)",
    black: "#1b1f26", red: "#cf3b3b", green: "#109c81", yellow: "#a8790c",
    blue: "#2f6fd0", magenta: "#8a4fb0", cyan: "#109c81", white: "#5a6472",
    brightBlack: "#878f9c", brightRed: "#e05555", brightGreen: "#14b596", brightYellow: "#c08e14",
    brightBlue: "#3f82e0", brightMagenta: "#9d5fc4", brightCyan: "#14b596", brightWhite: "#1b1f26",
  },
};
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  safeSet("serialhub.theme", theme);
  state.theme = theme;
  state.runtimes.forEach((rt) => {
    if (rt.term) rt.term.options.theme = XTERM_THEME[theme] || XTERM_THEME.dark;
  });
}
function initTheme() {
  if (!state.theme) {
    const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
    state.theme = prefersLight ? "light" : "dark";
  }
  applyTheme(state.theme);
}

/* 5b. language ============================================================ */
function refreshPauseBtn() {
  const span = $("[data-pause-label]", $("#btnPause"));
  if (span) span.textContent = t(state.paused ? "resume" : "pause");
}
function updateLangSwitcher() {
  $$(".lang-btn").forEach((b) => {
    const on = b.dataset.lang === state.lang;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
  });
}
function applyLang(lang) {
  if (lang !== "en" && lang !== "zh") lang = "en";
  state.lang = lang;
  safeSet("serialhub.lang", lang);
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.title = t("docTitle");
  applyI18n(document);
  refreshPauseBtn();
  $("#connText").textContent = t(conn.key, conn.vars);
  state.runtimes.forEach((rt) => { applyI18n(rt.pane); updatePortHeader(rt); });
  updateLangSwitcher();
}

/* 6. terminal / panes / rendering ========================================== */
const termHosts = new WeakMap();

function createRuntime(name) {
  const tpl = $("#paneTemplate").content.firstElementChild.cloneNode(true);
  const rt = {
    name,
    pane: tpl,
    term: null, fit: null,
    lines: [],          // retained records for filter/search/fallback
    deferred: [],       // lines buffered while paused
    hits: [], hitIdx: -1,
    filter: "", filterRe: null,
    lineCount: 0, byteCount: 0,
    last: { lines: 0, bytes: 0 }, hist: [],
    writeIndex: 0,
    state: "closed",
    el: {
      stateDot: $(".state-dot", tpl),
      stateLabel: $(".state-label", tpl),
      name: $(".port-name", tpl),
      meta: $(".port-meta", tpl),
      spark: $(".spark", tpl),
      rateLines: $(".rate-lines", tpl),
      rateBytes: $(".rate-bytes", tpl),
      bufPct: $(".buf-pct", tpl),
      termHost: $(".term-host", tpl),
      fallback: $(".log-fallback", tpl),
    },
  };
  rt.el.name.textContent = name;
  $("#panes").appendChild(tpl);
  termHosts.set(rt.el.termHost, rt);
  createTerminal(rt);
  return rt;
}

function createTerminal(rt) {
  if (state.termFallback || typeof window.Terminal === "undefined") {
    rt.el.termHost.hidden = true;
    rt.el.fallback.hidden = false;
    return;
  }
  const term = new window.Terminal({
    fontFamily: '"IBM Plex Mono", ui-monospace, "Cascadia Code", Menlo, Consolas, monospace',
    fontSize: 12.5,
    lineHeight: 1.28,
    letterSpacing: 0,
    cursorBlink: false,
    cursorStyle: "bar",
    scrollback: Math.max(1000, state.maxRenderLines),
    convertEol: false,
    allowProposedApi: true,
    theme: XTERM_THEME[state.theme] || XTERM_THEME.dark,
  });
  rt.term = term;
  if (window.FitAddon && window.FitAddon.FitAddon) {
    rt.fit = new window.FitAddon.FitAddon();
    term.loadAddon(rt.fit);
  }
  term.open(rt.el.termHost);
  refit(rt);
  if (rt.fit) {
    const ro = new ResizeObserver(() => refit(rt));
    ro.observe(rt.el.termHost);
  }
}

function refit(rt) {
  if (!rt.fit) return;
  try {
    const box = rt.el.termHost.getBoundingClientRect();
    if (box.width > 8 && box.height > 8) rt.fit.fit();
  } catch (_e) { /* fit can throw while hidden */ }
}

function ensurePort(name) {
  if (state.runtimes.has(name)) return state.runtimes.get(name);
  const rt = createRuntime(name);
  state.runtimes.set(name, rt);
  scheduleTabsRefresh();
  return rt;
}

let tabsTimer = null;
function scheduleTabsRefresh() {
  if (tabsTimer) return;
  tabsTimer = setTimeout(() => { tabsTimer = null; buildTabs(); fillSendPorts(); }, 0);
}

function buildRecord(line) {
  const text = line.text == null ? "" : String(line.text);
  return {
    seq: line.seq,
    ts: line.ts_ms || Date.now(),
    port: line.port,
    kind: line.kind || "rx",
    text,
    plain: stripAnsi(text),
    hasAnsi: !!line.ansi || ANSI_RE.test(text),
    row: -1,
  };
}

function buildPrefix(rec) {
  let p = "";
  if (state.timestamp) p += `\x1b[2m${fmtTime(rec.ts)}\x1b[0m `;
  p += `\x1b[38;2;232;131;74m` + String(rec.seq).padStart(4, " ") + `\x1b[0m `;
  if (rec.kind === "tx") return `\x1b[38;2;230;179;74m\u25b8\x1b[0m ` + p;
  if (rec.kind === "mark") return `\x1b[38;2;106;166;245m\u2691\x1b[0m ` + p;
  return p;
}

function renderRecord(rt, rec) {
  if (rt.filterRe && !rt.filterRe.test(rec.plain)) return;
  rec.row = rt.writeIndex++;
  if (rt.term) {
    rt.term.write(buildPrefix(rec) + rec.text + "\r\n");
    if (state.autoscroll && state.active === rt.name) rt.term.scrollToBottom();
  } else {
    renderFallback(rt, rec);
  }
}

function renderFallback(rt, rec) {
  const pre = rt.el.fallback;
  const row = document.createElement("div");
  row.className = "lf-" + (rec.kind === "tx" ? "tx" : rec.kind === "mark" ? "lf-seq" : "rx");
  let html = "";
  if (state.timestamp) html += `<span class="lf-ts">${fmtTime(rec.ts)}</span> `;
  html += `<span class="lf-seq">${rec.seq}</span> ` + escapeHtml(rec.plain);
  row.innerHTML = html;
  pre.appendChild(row);
  while (pre.childElementCount > state.maxRenderLines) pre.removeChild(pre.firstChild);
  if (state.autoscroll && state.active === rt.name) pre.scrollTop = pre.scrollHeight;
}

function trimArr(arr, n) { while (arr.length > n) arr.shift(); }

function onLine(name, line) {
  const rt = ensurePort(name);
  const rec = buildRecord(line);
  rt.lineCount += 1;
  rt.byteCount += byteLen(rec.text);
  rt.lines.push(rec);
  trimArr(rt.lines, state.maxRenderLines);
  if (state.paused) {
    rt.deferred.push(rec);
    trimArr(rt.deferred, state.maxRenderLines);
  } else {
    renderRecord(rt, rec);
  }
  if (state.active === name) scheduleCounters();
}
function onMark(name, msg) {
  onLine(name, { seq: msg.seq, port: name, ts_ms: msg.ts_ms || Date.now(),
    text: t("markLine", { label: msg.label || "" }), ansi: false, kind: "mark" });
}

/* 7. stats (rates + sparkline) ============================================ */
let counterTimer = null;
function scheduleCounters() {
  if (counterTimer) return;
  counterTimer = requestAnimationFrame(() => { counterTimer = null; paintCounters(); });
}
function paintCounters() {
  const rt = state.active ? state.runtimes.get(state.active) : null;
  if (!rt) return;
  rt.el.rateLines.textContent = fmtRate(rt.hist.length ? rt.hist[rt.hist.length - 1].l : 0);
  rt.el.rateBytes.textContent = fmtRate(rt.hist.length ? rt.hist[rt.hist.length - 1].b : 0);
}

function tickRates() {
  state.runtimes.forEach((rt) => {
    const dl = rt.lineCount - rt.last.lines;
    const db = rt.byteCount - rt.last.bytes;
    rt.last = { lines: rt.lineCount, bytes: rt.byteCount };
    rt.hist.push({ l: dl, b: db });
    trimArr(rt.hist, 60);
    updatePortHeader(rt);
    drawSpark(rt);
  });
  paintCounters();
}

function updatePortHeader(rt) {
  const meta = state.ports.get(rt.name);
  const bits = [];
  if (meta && meta.device) bits.push(meta.device);
  if (meta && meta.baud) bits.push(String(meta.baud) + " baud");
  if (rt.state) bits.push(t("state_" + rt.state));
  rt.el.meta.textContent = bits.join("  \u00b7  ");
  rt.el.meta.title = bits.join(" \u00b7 ");
  rt.el.stateLabel.textContent = t("state_" + rt.state);
  rt.el.stateDot.className = "state-dot " + (rt.state === "open" ? "open" : rt.state === "reconnecting" ? "reconnecting" : rt.state === "error" ? "error" : "");
  const buf = meta && meta.buffer ? meta.buffer : null;
  const capLines = (state.portConfig(rt.name) && state.portConfig(rt.name).buffer_lines) || 20000;
  const pct = buf && capLines ? clamp((buf.count / capLines) * 100, 0, 100) : 0;
  rt.el.bufPct.textContent = Math.round(pct) + "%";
  rt.el.bufPct.title = buf ? t("bufHint", { n: buf.count, bytes: fmtBytes(buf.bytes) }) : "";
}

function drawSpark(rt) {
  const c = rt.el.spark;
  if (!c || c.offsetParent === null) return;
  const ctx = c.getContext("2d");
  const W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  const hist = rt.hist.slice(-40);
  if (!hist.length) return;
  let maxB = 1;
  for (const h of hist) maxB = Math.max(maxB, h.b);
  const css = getComputedStyle(document.documentElement);
  const col = (css.getPropertyValue("--rx").trim() || "#4fd1b0");
  const gap = 2, n = hist.length;
  const bw = Math.max(1, (W - gap * (n - 1)) / n);
  ctx.fillStyle = col;
  let x = W - (bw * n + gap * (n - 1));
  for (const h of hist) {
    const bh = Math.max(1, (h.b / maxB) * (H - 6));
    ctx.globalAlpha = 0.35 + 0.65 * (h.b / maxB);
    ctx.fillRect(x, H - bh, Math.max(1, bw - 0.5), bh);
    x += bw + gap;
  }
  ctx.globalAlpha = 1;
}

/* 8. websocket bus ======================================================== */
const CONN_DEFAULT_KEY = { idle: "connIdle", connecting: "connConnecting", open: "connLive", error: "connError" };
const conn = { state: "idle", key: "connIdle", vars: null };
function setConn(stateName, key, vars) {
  state.wsState = stateName;
  conn.state = stateName;
  conn.key = key || CONN_DEFAULT_KEY[stateName] || "connIdle";
  conn.vars = vars || null;
  const pill = $("#connPill");
  pill.setAttribute("data-state", stateName === "unauthorized" ? "error" : stateName);
  $("#connText").textContent = t(conn.key, conn.vars);
}

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let url = `${proto}://${location.host}/ws`;
  if (state.token) url += "?token=" + encodeURIComponent(state.token);
  return url;
}

function connectWS() {
  if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) return;
  if (state.wsTimer) { clearTimeout(state.wsTimer); state.wsTimer = null; }
  setConn("connecting");
  let ws;
  try { ws = new WebSocket(wsUrl()); }
  catch (e) { toast(t("toastWsError", { msg: e.message }), "error"); return scheduleReconnect(); }
  state.ws = ws;

  ws.addEventListener("open", () => {
    state.wsBackoff = 500;
    setConn("open");
    ws.send(JSON.stringify({ type: "subscribe", ports: [] })); // [] => all ports
  });
  ws.addEventListener("message", (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (_e) { return; }
    handleWsMessage(msg);
  });
  ws.addEventListener("close", () => { setConn("idle", "connReconnecting"); scheduleReconnect(); });
  ws.addEventListener("error", () => { setConn("error"); });
}

function scheduleReconnect() {
  if (state.wsTimer) return;
  const wait = state.wsBackoff;
  state.wsBackoff = Math.min(state.wsBackoffMax, Math.round(state.wsBackoff * 1.7));
  state.wsTimer = setTimeout(() => { state.wsTimer = null; connectWS(); }, wait);
}

function restartWS() {
  if (state.wsTimer) { clearTimeout(state.wsTimer); state.wsTimer = null; }
  state.wsBackoff = 500;
  if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
    try { state.ws.close(); } catch (_e) { /* ignore */ }
  } else {
    connectWS();
  }
}

function handleWsMessage(msg) {
  if (!msg || typeof msg !== "object") return;
  if (msg.ok === false && msg.error === "unauthorized") {
    setConn("unauthorized", "connUnauthorized");
    toast(t("toastWsUnauthorized"), "error");
    return;
  }
  switch (msg.type) {
    case "hello": onHello(msg.ports || []); break;
    case "line": if (msg.line) onLine(msg.port, msg.line); break;
    case "status": onStatus(msg); break;
    case "mark": onMark(msg.port, msg); break;
    case "pong": break;
    default: break;
  }
}

function onHello(ports) {
  const seen = new Set();
  ports.forEach((p) => {
    if (!p || !p.name) return;
    seen.add(p.name);
    state.ports.set(p.name, p);
    const rt = ensurePort(p.name);
    rt.state = p.open ? "open" : (p.last_error ? "error" : "closed");
    updatePortHeader(rt);
  });
  if (!state.active && ports.length) activate(ports[0].name);
  updateGlobalStats();
}

function onStatus(msg) {
  const name = msg.port;
  if (!name) return;
  const rt = ensurePort(name);
  const prev = state.ports.get(name) || {};
  const merged = Object.assign({}, prev);
  ["open", "baud", "device", "last_error", "reconnect_count", "rx_lines", "tx_lines", "buffer"].forEach((k) => {
    if (msg[k] !== undefined) merged[k] = msg[k];
  });
  state.ports.set(name, merged);
  rt.state = msg.open === undefined ? rt.state : (msg.open ? "open" : (msg.last_error ? "error" : "closed"));
  updatePortHeader(rt);
  updateTabState(name);
  updateGlobalStats();
}

/* 9. filter + search ====================================================== */
function getFilter(name) {
  const rt = state.runtimes.get(name);
  return rt ? rt.filter : "";
}
function applyFilter(pattern) {
  const rt = state.active ? state.runtimes.get(state.active) : null;
  if (!rt) return;
  rt.filter = pattern;
  rt.filterRe = pattern ? compileRe(pattern) : null;
  const fld = $("#filterInput");
  fld.classList.toggle("invalid", !!pattern && !rt.filterRe);
}
function rebuildView(rt) {
  // Re-render the retained buffer under the current filter state.
  if (rt.term) { rt.term.clear(); rt.term.reset(); }
  else { rt.el.fallback.innerHTML = ""; }
  rt.writeIndex = 0;
  rt.lines.forEach((rec) => renderRecord(rt, rec));
}

function runSearch(pattern) {
  const rt = state.active ? state.runtimes.get(state.active) : null;
  if (!rt) return;
  rt.hits = []; rt.hitIdx = -1;
  const re = compileRe(pattern);
  if (re) {
    for (let i = 0; i < rt.lines.length; i++) {
      const rec = rt.lines[i];
      if (re.test(rec.plain)) rt.hits.push(rec);
    }
  }
  renderSearchResults(rt, "local", pattern);
  if (rt.hits.length) { rt.hitIdx = 0; jumpHit(); }
  updateSearchCount();
}
function updateSearchCount() {
  const rt = state.active ? state.runtimes.get(state.active) : null;
  const el = $("#searchCount");
  if (!rt || !rt.hits.length) { el.textContent = "0/0"; return; }
  el.textContent = (rt.hitIdx + 1) + "/" + rt.hits.length;
}
function jumpHit() {
  const rt = state.active ? state.runtimes.get(state.active) : null;
  if (!rt || rt.hitIdx < 0 || !rt.hits[rt.hitIdx]) return;
  const rec = rt.hits[rt.hitIdx];
  markActiveMatch(rt, rec.seq);
  if (rt.term) {
    try { rt.term.scrollToLine(Math.max(0, rec.row)); } catch (_e) { rt.term.scrollToBottom(); }
  } else {
    const node = rt.el.fallback.children[Math.max(0, rec.row)];
    if (node) node.scrollIntoView({ block: "center" });
  }
}
function nextHit(delta) {
  const rt = state.active ? state.runtimes.get(state.active) : null;
  if (!rt || !rt.hits.length) return;
  rt.hitIdx = (rt.hitIdx + delta + rt.hits.length) % rt.hits.length;
  jumpHit(); updateSearchCount();
}
function renderSearchResults(rt, source, pattern) {
  const box = $("#searchResults");
  if (!rt.hits.length) { box.hidden = true; box.innerHTML = ""; return; }
  const re = compileRe(pattern != null ? pattern : $("#searchInput").value);
  box.innerHTML = "";
  rt.hits.slice(0, 200).forEach((rec, i) => {
    const row = document.createElement("div");
    row.className = "match-row";
    row.dataset.seq = rec.seq;
    let text = escapeHtml(rec.plain);
    if (re) text = text.replace(re, (m) => `<mark>${m}</mark>`);
    row.innerHTML = `<span class="mr-seq">${rec.seq}</span>` +
      (source === "local" ? `<span class="mr-ts">${fmtTime(rec.ts)}</span>` : "") +
      `<span class="mr-text">${text}</span>`;
    row.addEventListener("click", () => {
      rt.hitIdx = i; jumpHit(); updateSearchCount(); markActiveMatch(rt, rec.seq);
    });
    box.appendChild(row);
  });
  box.hidden = false;
}
function markActiveMatch(rt, seq) {
  $$(".match-row", $("#searchResults")).forEach((r) => r.classList.toggle("active", Number(r.dataset.seq) === seq));
}

async function serverSearch() {
  const rt = state.active ? state.runtimes.get(state.active) : null;
  const pattern = $("#searchInput").value;
  if (!rt || !pattern) return;
  const data = await api("GET", `/api/ports/${encodeURIComponent(rt.name)}/search`, {
    params: { regex: pattern, limit: 200 },
  });
  if (!data.ok) return;
  const hits = (data.hits || []).map((h) => ({
    seq: h.seq, ts: h.ts_ms, plain: h.text,
  }));
  rt.hits = hits;
  rt.hitIdx = -1;
  const box = $("#searchResults");
  box.innerHTML = "";
  if (!hits.length) { box.hidden = true; toast(t("toastNoMatches"), "info"); updateSearchCount(); return; }
  const re = compileRe(pattern);
  hits.forEach((h, i) => {
    const row = document.createElement("div");
    row.className = "match-row";
    row.dataset.seq = h.seq;
    let text = escapeHtml(h.plain);
    if (re) text = text.replace(re, (m) => `<mark>${m}</mark>`);
    row.innerHTML = `<span class="mr-seq">${h.seq}</span><span class="mr-ts">${fmtTime(h.ts)}</span><span class="mr-text">${text}</span>`;
    row.addEventListener("click", () => {
      const local = rt.lines.find((l) => l.seq === h.seq);
      if (local) { rt.hitIdx = rt.lines.indexOf(local); jumpHit(); }
      else toast(t("toastOutsideBuffer", { seq: h.seq }), "warn");
    });
    box.appendChild(row);
  });
  box.hidden = false;
  updateSearchCount();
}

/* 10. tabs, activate, sendbar, export, toolbar, polling, init ============= */
function updateTabState(name) {
  const tab = $('.tab[data-port="' + CSS.escape(name) + '"]');
  if (!tab) return;
  const rt = state.runtimes.get(name);
  const dot = $(".t-dot", tab);
  const cls = rt && rt.state === "open" ? "open" : rt && rt.state === "reconnecting" ? "reconnecting" : "closed";
  dot.className = "t-dot " + cls;
}
function buildTabs() {
  const tabs = $("#tabs");
  tabs.innerHTML = "";
  state.runtimes.forEach((rt, name) => {
    const btn = document.createElement("button");
    btn.className = "tab";
    btn.dataset.port = name;
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", String(state.active === name));
    const baud = (state.ports.get(name) || {}).baud;
    btn.innerHTML = `<span class="t-dot"></span><span>${escapeHtml(name)}</span>` +
      (baud ? `<span class="t-baud">${baud}</span>` : "");
    btn.addEventListener("click", () => activate(name));
    tabs.appendChild(btn);
    updateTabState(name);
  });
}
function activate(name) {
  if (!state.runtimes.has(name)) ensurePort(name);
  state.active = name;
  state.runtimes.forEach((rt, n) => {
    const on = n === name;
    rt.pane.hidden = !on;
    if (on) requestAnimationFrame(() => { refit(rt); if (rt.term) rt.term.scrollToBottom(); });
  });
  $$(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.port === name)));
  $("#filterInput").value = getFilter(name);
  $("#sendPort").value = name;
  const rt = state.runtimes.get(name);
  if (rt) { renderSearchResults(rt, "local"); updateSearchCount(); }
  paintCounters();
}

function send() {
  const name = $("#sendPort").value;
  const input = $("#sendInput");
  const data = input.value;
  if (!name || data === "") return;
  const eol = $("#sendEol").value;
  api("POST", `/api/ports/${encodeURIComponent(name)}/send`, { body: { data, eol } })
    .then((r) => { if (r.ok) { pushHistory(data); input.value = ""; } });
}
function pushHistory(data) {
  state.sendHistory = state.sendHistory.filter((h) => h !== data);
  state.sendHistory.unshift(data);
  state.sendHistory = state.sendHistory.slice(0, 50);
  state.sendIndex = -1;
  safeSet("serialhub.sendHistory", JSON.stringify(state.sendHistory));
}
function historyNav(delta) {
  if (!state.sendHistory.length) return;
  if (state.sendIndex === -1 && delta < 0) state.sendIndex = 0;
  else state.sendIndex = clamp(state.sendIndex + (delta < 0 ? 1 : -1), 0, state.sendHistory.length - 1);
  $("#sendInput").value = state.sendHistory[state.sendIndex] || "";
}

async function exportPort(fmt) {
  const name = $("#sendPort").value || state.active;
  if (!name) return;
  const r = await api("POST", `/api/ports/${encodeURIComponent(name)}/export`, { body: { format: fmt } });
  if (r.ok) toast(t("toastExported", { n: r.count, fmt: r.format, file: r.path }), "ok");
}

function updateGlobalStats() {
  const ports = Array.from(state.ports.values());
  $("#statPorts").textContent = String(ports.length || state.runtimes.size);
  $("#statOpen").textContent = String(ports.filter((p) => p.open).length);
}

async function pollStatus() {
  const health = await api("GET", "/health");
  if (health.ok) $("#statUptime").textContent = fmtDuration(health.uptime_ms);
  const st = await api("GET", "/api/status");
  if (!st.ok) return;
  (st.ports || []).forEach((p) => {
    if (!p || !p.name) return;
    state.ports.set(p.name, p);
    const rt = ensurePort(p.name);
    rt.state = p.open ? "open" : (p.last_error ? "error" : "closed");
    updatePortHeader(rt);
    updateTabState(p.name);
  });
  updateGlobalStats();
}

async function loadConfig() {
  const r = await api("GET", "/api/config");
  if (!r.ok || !r.config) return;
  state.config = r.config;
  const ui = r.config.ui || {};
  if (ui.max_render_lines) state.maxRenderLines = ui.max_render_lines;
  if (!safeGet("serialhub.timestamp", "")) state.timestamp = ui.timestamp !== false;
  // build port runtimes from config (ensures tabs before WS hello)
  (state.config.ports || []).forEach((p) => { if (p && p.name) ensurePort(p.name); });
}
state.portConfig = function (name) {
  const cfg = state.config;
  if (!cfg) return null;
  const list = cfg.ports || [];
  return list.find((p) => p.name === name) || null;
};

function bindUI() {
  $("#themeToggle").addEventListener("click", () => applyTheme(state.theme === "dark" ? "light" : "dark"));
  $$(".lang-btn").forEach((b) => b.addEventListener("click", () => applyLang(b.dataset.lang)));

  const tokenInput = $("#tokenInput");
  tokenInput.value = state.token;
  tokenInput.addEventListener("change", () => {
    state.token = tokenInput.value.trim();
    safeSet("serialhub.token", state.token);
    toast(t("toastTokenUpdated"), "info");
    restartWS();
  });

  $("#btnPause").addEventListener("click", (e) => {
    state.paused = !state.paused;
    e.currentTarget.classList.toggle("on", state.paused);
    refreshPauseBtn();
    if (!state.paused) {
      state.runtimes.forEach((rt) => { rt.deferred.forEach((rec) => renderRecord(rt, rec)); rt.deferred = []; });
      toast(t("toastResumed"), "info");
    } else {
      toast(t("toastPaused"), "info");
    }
  });

  $("#btnAuto").addEventListener("click", (e) => {
    state.autoscroll = !state.autoscroll;
    e.currentTarget.classList.toggle("on", state.autoscroll);
    safeSet("serialhub.autoscroll", String(state.autoscroll));
  });

  $("#btnTs").addEventListener("click", (e) => {
    state.timestamp = !state.timestamp;
    e.currentTarget.classList.toggle("on", state.timestamp);
    safeSet("serialhub.timestamp", String(state.timestamp));
    const rt = state.active ? state.runtimes.get(state.active) : null;
    if (rt) rebuildView(rt);
  });

  $("#btnClear").addEventListener("click", () => {
    const rt = state.active ? state.runtimes.get(state.active) : null;
    if (!rt) return;
    rt.lines = []; rt.deferred = []; rt.hits = []; rt.hitIdx = -1; rt.writeIndex = 0;
    if (rt.term) { rt.term.clear(); rt.term.reset(); }
    else rt.el.fallback.innerHTML = "";
    $("#searchResults").hidden = true;
    updateSearchCount();
  });

  let filterTimer = null;
  $("#filterInput").addEventListener("input", (e) => {
    clearTimeout(filterTimer);
    const val = e.target.value;
    filterTimer = setTimeout(() => applyFilter(val), 200);
  });

  $("#searchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); runSearch(e.target.value); }
    if (e.key === "Escape") { e.target.value = ""; $("#searchResults").hidden = true; }
  });
  $("#btnPrev").addEventListener("click", () => nextHit(-1));
  $("#btnNext").addEventListener("click", () => nextHit(1));
  $("#btnServerSearch").addEventListener("click", serverSearch);

  $$("[data-export]").forEach((b) => b.addEventListener("click", () => exportPort(b.dataset.export)));

  $("#sendBtn").addEventListener("click", send);
  const sendInput = $("#sendInput");
  sendInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); send(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); historyNav(-1); }
    else if (e.key === "ArrowDown") { e.preventDefault(); historyNav(1); }
  });
  $("#sendPort").addEventListener("change", (e) => { if (state.runtimes.has(e.target.value)) activate(e.target.value); });

  document.addEventListener("click", (e) => {
    const box = $("#searchResults");
    if (box.hidden) return;
    if (!e.target.closest("#searchResults") && !e.target.closest("#searchInput") &&
        !e.target.closest("#btnPrev") && !e.target.closest("#btnNext") && !e.target.closest("#btnServerSearch")) {
      box.hidden = true;
    }
  });
}

function fillSendPorts() {
  const sel = $("#sendPort");
  sel.innerHTML = "";
  state.runtimes.forEach((_rt, name) => {
    const o = document.createElement("option");
    o.value = name; o.textContent = name;
    sel.appendChild(o);
  });
  if (state.active) sel.value = state.active;
}

function detectFallback() {
  if (typeof window.Terminal === "undefined") {
    state.termFallback = true;
    $("#banner").hidden = false;
  }
}

async function init() {
  try { state.sendHistory = JSON.parse(safeGet("serialhub.sendHistory", "[]")) || []; }
  catch (_e) { state.sendHistory = []; }

  // Wait for xterm.js (local vendor -> CDN fallback) to settle before we
  // decide whether to render with the terminal or the plain-text fallback.
  if (window.__xtermReady) { try { await window.__xtermReady; } catch (_e) { /* ignore */ } }
  if (window.__fitReady) { try { await window.__fitReady; } catch (_e) { /* ignore */ } }

  initTheme();
  applyLang(state.lang);
  detectFallback();
  $("#btnAuto").classList.toggle("on", state.autoscroll);
  $("#btnTs").classList.toggle("on", state.timestamp);
  bindUI();

  await loadConfig();
  fillSendPorts();

  // Show configured ports immediately, before the WebSocket hello arrives.
  if (!state.active && state.runtimes.size) activate(state.runtimes.keys().next().value);
  buildTabs();

  connectWS();
  setInterval(tickRates, 1000);
  setInterval(pollStatus, 3000);
  setTimeout(pollStatus, 400);
  // keep the active port header fresh as buffer/state change server-side
  setInterval(() => {
    if (state.active) {
      const rt = state.runtimes.get(state.active);
      if (rt) { updatePortHeader(rt); }
    }
  }, 2000);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
