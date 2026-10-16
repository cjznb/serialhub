/* =============================================================================
   serialhub Web UI — LOCALE TEMPLATE  (copy me to add a language)
   =============================================================================

   ADDING A LANGUAGE = DROP ONE FILE. No edits to app.js or any other core file.

   Steps
   -----
   1. Copy this file to a new sibling, e.g. `static/i18n/de.js`.
      (Keep the lowercase 2-letter-ish code that you will pass to register().)

   2. Fill in the `register()` call below:
        - code  : your language tag, e.g. 'de'  (used as the registry key AND
                  the value persisted in localStorage['serialhub.lang'])
        - dict  : translate the VALUES. DO NOT rename, add, or remove KEYS —
                  the key set must stay identical to en.js so the fallback
                  chain (active -> en -> key) keeps working.
        - meta  : { label, htmlLang, name }
                    label    short switcher-button text (sits in a segmented
                             control next to EN / 中文 — keep it ~2-4 chars)
                    htmlLang the value written to <html lang>, e.g. 'de' / 'pt-BR'
                    name     human-readable language name, e.g. 'Deutsch'

   3. Add ONE line to index.html, right after the other locale scripts and
      BEFORE app.js (order among locales does not matter; the active locale is
      chosen at runtime, not by load order):

          <script src="/static/i18n/de.js"></script>

      The language switcher is built from the registry, so a new button appears
      automatically — no HTML/JS changes needed.

   placeholders
   ------------
   Values may contain {name} placeholders; t(key, vars) interpolates them.
   Keep placeholders verbatim (same spelling and braces) across translations.
   See en.js for the full key list and the current placeholder usages.
   ========================================================================== */
"use strict";

// NOTE: replace 'xx' with your real language code and translate every value on
// the right-hand side. Uncomment the block below and delete this comment when
// you are done. The keys are listed once, exactly as in en.js.
//
// window.SERIALHUB_I18N.register('xx', {
//   docTitle: "",
//   brandSub: "",
//   statsAria: "",
//   statPorts: "",
//   statOpen: "",
//   statUptime: "",
//   connIdle: "",
//   connConnecting: "",
//   connLive: "",
//   connError: "",
//   connReconnecting: "",
//   connUnauthorized: "",
//   tokenLabel: "",
//   tokenTitle: "",
//   tokenPlaceholder: "",
//   langAria: "",
//   themeTitle: "",
//   themeAria: "",
//   tabsAria: "",
//   bannerStrong: "",
//   bannerText: "",
//   pauseTitle: "",
//   pause: "",
//   resume: "",
//   autoTitle: "",
//   autoLabel: "",
//   tsTitle: "",
//   tsLabel: "",
//   clearTitle: "",
//   clearLabel: "",
//   filterTitle: "",
//   filterLabel: "",
//   filterPlaceholder: "",
//   searchTitle: "",
//   searchLabel: "",
//   searchPlaceholder: "",
//   prevTitle: "",
//   nextTitle: "",
//   histTitle: "",
//   histLabel: "",
//   exportGroupTitle: "",
//   exportRaw: "",
//   exportNoansi: "",
//   exportJson: "",
//   sendPortTitle: "",
//   sendPortAria: "",
//   sendPlaceholder: "",
//   eolTitle: "",
//   eolAria: "",
//   eolCrlf: "",
//   eolLf: "",
//   eolCr: "",
//   eolNone: "",
//   send: "",
//   state_closed: "",
//   state_open: "",
//   state_reconnecting: "",
//   state_error: "",
//   rateLines: "",
//   rateBytes: "",
//   buffer: "",
//   bufHint: "",
//   markLine: "",
//   toastDismiss: "",
//   toastNetworkError: "",
//   toastUnauthorized: "",
//   toastWsUnauthorized: "",
//   toastWsError: "",
//   toastTokenUpdated: "",
//   toastResumed: "",
//   toastPaused: "",
//   toastExported: "",
//   toastNoMatches: "",
//   toastOutsideBuffer: "",
//   copied: "",
//   "device.change": "",
//   "device.title": "",
//   "device.current": "",
//   "device.auto": "",
//   "device.refresh": "",
//   "device.refreshTitle": "",
//   "device.listAria": "",
//   "device.match_ph": "",
//   "device.matchHint": "",
//   "device.apply": "",
//   "device.mapping_only": "",
//   "device.mappingOnlyTitle": "",
//   "device.changed": "",
//   "device.error": "",
//   "device.match_invalid": "",
//   "device.noDevices": "",
//   "device.loadFailed": "",
// }, { label: 'XX', htmlLang: 'xx', name: '' });

/* A filled-in example (kept inert so shipping this template changes nothing):

window.SERIALHUB_I18N.register('de', {
  docTitle: "serialhub · serielle Konsole",
  brandSub: "dauerhafter serieller Hub",
  // ...all remaining keys...
  copied: "{n} Zeichen kopiert",
}, { label: 'DE', htmlLang: 'de', name: 'Deutsch' });
*/
