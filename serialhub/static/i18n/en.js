/* =============================================================================
   serialhub Web UI — English locale.
   A locale file is self-contained: it registers its dictionary + metadata with
   the shared registry (window.SERIALHUB_I18N) defined inline in index.html.
   Adding a language = drop a sibling file here and add ONE <script> line in
   index.html. No core (app.js) edits required.

   Contract:
     register(code, dict, meta)
       code  — stable BCP-ish tag used in localStorage + as the registry key
       dict  — flat map of key -> string; {var} placeholders are interpolated
       meta  — { label, htmlLang, name }
                 label    switcher button text
                 htmlLang value written to <html lang>
                 name     human-readable language name
   ========================================================================== */
"use strict";

// Language-independent label metadata. The registry renders one switcher button
// per registered locale; keep `label` short (it sits in a segmented control).
window.SERIALHUB_I18N.register('en', {
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
  copied: "Copied {n} chars",
  "device.change": "Change device",
  "device.title": "Device",
  "device.current": "current",
  "device.auto": "auto",
  "device.refresh": "Refresh",
  "device.refreshTitle": "Re-scan serial ports",
  "device.listAria": "Discovered devices",
  "device.match_ph": "description=CH340",
  "device.matchHint": "Match by property \u2014 description=CH340 or {\"vid\":0x1A86,\"pid\":0x7523}",
  "device.apply": "Apply",
  "device.mapping_only": "mapping only (do not reopen)",
  "device.mappingOnlyTitle": "Update the mapping without reopening the port",
  "device.changed": "Device \u2192 {device}",
  "device.error": "Device change failed: {msg}",
  "device.match_invalid": "Enter a JSON object or k=v pairs, e.g. description=CH340",
  "device.noDevices": "No serial devices found.",
  "device.loadFailed": "Could not list devices.",
}, { label: 'EN', htmlLang: 'en', name: 'English' });
