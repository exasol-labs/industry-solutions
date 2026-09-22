"""Server-rendered HTML for the administrative interface.

Self-contained: inline CSS and JS, no build step, dark theme matching the main
app. The dashboard fetches its data from the /api/* endpoints after load.
"""

from __future__ import annotations

import base64
import html

from app.config import APP_VERSION

# Animated brand mark (a discovered process graph with a flowing event dot),
# shared by the sign-in page and the dashboard. Matches frontend/components/Logo.tsx.
_LOGO_SVG = """<svg class="pm-logo" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <defs>
    <linearGradient id="pmBg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#3a9bff"/><stop offset="1" stop-color="#6b5cf0"/>
    </linearGradient>
    <linearGradient id="pmShine" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#fff" stop-opacity="0"/>
      <stop offset="0.5" stop-color="#fff" stop-opacity="0.5"/>
      <stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </linearGradient>
    <clipPath id="pmClip"><rect x="2" y="2" width="44" height="44" rx="12"/></clipPath>
    <filter id="pmGlow" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="1.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <g clip-path="url(#pmClip)">
    <rect x="2" y="2" width="44" height="44" rx="12" fill="url(#pmBg)"/>
    <rect x="-28" y="2" width="20" height="44" fill="url(#pmShine)" transform="skewX(-16)">
      <animate attributeName="x" values="-28;56" dur="4.2s" begin="0.5s" repeatCount="indefinite"/>
    </rect>
    <path d="M15 16 L33 16 L24 34 Z" fill="none" stroke="#fff" stroke-width="2.4"
          stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/>
    <circle cx="15" cy="16" r="4.4" fill="none" stroke="#fff" stroke-width="1.5">
      <animate attributeName="r" values="4.4;9" dur="2.8s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.55;0" dur="2.8s" repeatCount="indefinite"/>
    </circle>
    <g fill="#fff">
      <circle cx="15" cy="16" r="4.4"/><circle cx="33" cy="16" r="4.4"/><circle cx="24" cy="34" r="4.4"/>
    </g>
    <circle r="2.2" fill="#eaf3ff" filter="url(#pmGlow)">
      <animateMotion dur="2.8s" repeatCount="indefinite" calcMode="linear" path="M15 16 L33 16 L24 34 Z"/>
    </circle>
  </g>
</svg>"""

# Static one-frame version for the browser-tab favicon (favicons don't animate).
_FAVICON_SVG = (
    '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="b" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#3a9bff"/><stop offset="1" stop-color="#6b5cf0"/>'
    '</linearGradient></defs>'
    '<rect x="2" y="2" width="44" height="44" rx="12" fill="url(#b)"/>'
    '<path d="M15 16 L33 16 L24 34 Z" fill="none" stroke="#fff" stroke-width="2.6" '
    'stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>'
    '<g fill="#fff"><circle cx="15" cy="16" r="4.6"/><circle cx="33" cy="16" r="4.6"/>'
    '<circle cx="24" cy="34" r="4.6"/></g>'
    '<circle cx="24" cy="16" r="2.4" fill="#eaf3ff"/></svg>'
)
_FAVICON_LINK = (
    '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,'
    + base64.b64encode(_FAVICON_SVG.encode("utf-8")).decode("ascii")
    + '">'
)

# Resolve the persisted theme before first paint (no flash of the wrong palette).
# 'system' follows the OS; the stored value is shared with the topbar control below.
_THEME_BOOT = (
    "<script>(function(){try{var t=localStorage.getItem('pmw_admin_theme')||'system';"
    "var d=t==='system'?matchMedia('(prefers-color-scheme: dark)').matches:t==='dark';"
    "document.documentElement.dataset.theme=d?'dark':'light';}catch(e){}})();</script>"
)

_STYLE = """
#lbg_preview.drag-over { outline: 2px dashed var(--accent, #0a84ff); outline-offset: -6px; }
:root {
  /* Light is the default; the dark palette (below) mirrors the previous look and is
     applied via data-theme, matching the main app's theme mechanism. */
  --bg: #f2f2f7; --panel: #ffffff; --panel2: #eceef3; --fill: rgba(120,120,128,.12);
  --fill2: rgba(120,120,128,.2); --border: rgba(60,60,67,.29); --border-soft: rgba(60,60,67,.12);
  --text: #1c1c1e; --muted: rgba(60,60,67,.6); --tertiary: rgba(60,60,67,.3);
  --accent: #0a84ff; --green: #248a3d; --red: #d70015; --orange: #c93400; --yellow: #b25000;
  --radius: 10px; --shadow: 0 8px 30px rgba(0,0,0,.18);
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color-scheme: light;
}
:root[data-theme='dark'] {
  --bg: #0b0b0d; --panel: #16161a; --panel2: #1d1d22; --fill: rgba(120,120,128,.16);
  --fill2: rgba(120,120,128,.28); --border: rgba(120,120,128,.28); --border-soft: rgba(120,120,128,.16);
  --text: #f2f2f7; --muted: rgba(235,235,245,.6); --tertiary: rgba(235,235,245,.3);
  --green: #32d74b; --red: #ff453a; --orange: #ff9f0a; --yellow: #ffd60a;
  --shadow: 0 8px 30px rgba(0,0,0,.5);
  color-scheme: dark;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font-family: var(--font); font-size: 14px; }
a { color: var(--accent); }
button { font: inherit; cursor: pointer; }
h1 { font-size: 20px; margin: 0; }
h2 { font-size: 15px; margin: 0 0 12px; }
/* Subsection label (e.g. the Profile overlay's Password / Passkeys / Two-factor). */
.card h3, .prof-ov-body h3 { font-size: 12px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .04em; color: var(--muted); margin: 22px 0 8px;
  border-top: 1px solid var(--border-soft); padding-top: 16px; }
.card h3:first-of-type, .prof-ov-body h3:first-of-type { border-top: none; padding-top: 0; }
.wrap { max-width: 980px; margin: 0 auto; padding: 24px 20px 60px; }
.topbar { display: flex; align-items: center; gap: 12px; padding: 14px 20px; background: var(--panel);
  border-bottom: 1px solid var(--border-soft); position: sticky; top: 0; z-index: 10; }
.brand { display: flex; align-items: center; gap: 12px; }
.logo { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center;
  background: none; box-shadow: 0 2px 6px rgba(10,20,60,.35); }
.pm-logo { width: 100%; height: 100%; display: block; }
.brand .sub { font-size: 11px; color: var(--muted); }
.spacer { flex: 1; }
.card { background: var(--panel); border: 1px solid var(--border-soft); border-radius: var(--radius);
  padding: 18px; margin: 16px 0; }
.codeblock { background: var(--panel2); border: 1px solid var(--border-soft); border-radius: 8px;
  padding: 12px 40px 12px 14px; font-family: var(--mono); font-size: 12px; line-height: 1.5; overflow-x: auto; }
.codeblock .tok { color: var(--accent, #0a84ff); font-weight: 600; }
.codeblock-wrap { position: relative; }
.copy-btn { position: absolute; top: 8px; right: 8px; padding: 3px 7px; border: 1px solid var(--border-soft);
  border-radius: 6px; background: var(--panel); cursor: pointer; font-size: 13px; line-height: 1; }
.copy-btn:hover { background: var(--fill2); }
.row { display: flex; align-items: center; gap: 10px; }
.col { display: flex; flex-direction: column; gap: 10px; }
.muted { color: var(--muted); }
.mono { font-family: var(--mono); font-size: 12px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 11px; color: var(--muted); }
input[type=text], input[type=password], input[type=number], select, textarea {
  font: inherit; color: var(--text); background: var(--fill); border: 1px solid transparent;
  border-radius: 7px; padding: 7px 9px; outline: none; width: 100%; }
input:focus, select:focus, textarea:focus { border-color: var(--accent); }
textarea { min-height: 90px; font-family: var(--mono); font-size: 12px; resize: vertical; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 7px 13px; border: none; border-radius: 7px;
  background: var(--fill); color: var(--text); white-space: nowrap; }
.btn:hover { background: var(--fill2); }
.btn.primary { background: var(--accent); color: #fff; }
.btn.danger { color: var(--red); }
.btn.small { padding: 4px 9px; font-size: 12px; }
.btn:disabled { opacity: .45; cursor: default; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-size: 11px; color: var(--muted); font-weight: 600; padding: 8px 10px;
  border-bottom: 1px solid var(--border-soft); }
td { padding: 9px 10px; border-bottom: 1px solid var(--border-soft); vertical-align: middle; }
tr:last-child td { border-bottom: 0; }
.pill { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; padding: 2px 8px; border-radius: 999px; }
.pill.on { background: rgba(50,215,75,.16); color: var(--green); }
.pill.off { background: rgba(255,69,58,.16); color: var(--red); }
.pill.admin { background: rgba(10,132,255,.18); color: var(--accent); }
.pill.active { background: rgba(50,215,75,.18); color: var(--green); }
.pill.ldap { background: rgba(191,90,242,.18); color: #bf5af2; font-weight: 600; letter-spacing: .3px; }
.pill.power { background: rgba(48,209,196,.18); color: #30d1c4; font-weight: 600; letter-spacing: .3px; }
.pill.dev { background: rgba(255,159,10,.18); color: var(--orange); font-weight: 600; letter-spacing: .3px; }
.pill.log-info { background: rgba(10,132,255,.16); color: var(--accent); }
.pill.log-usage { background: rgba(50,215,75,.16); color: var(--green); }
.pill.log-warn { background: rgba(255,159,10,.16); color: var(--orange); }
.pill.log-error { background: rgba(255,69,58,.16); color: var(--red); }
.pill.log-debug { background: var(--fill2); color: var(--muted); }
#logTable table { table-layout: fixed; width: 100%; }
#logTable td { font-size: 12px; vertical-align: top; }
#logTable th:first-child, #logTable td:first-child { white-space: nowrap; width: 104px; }
#logTable th:nth-child(2), #logTable td:nth-child(2) { white-space: nowrap; width: 76px; }
/* Every row stays exactly one line regardless of message length — long SQL is
   clipped with an ellipsis; a click opens the full entry in a popup. */
#logTable td:last-child { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 0; }
#logTable tbody tr { cursor: pointer; }
#logTable tbody tr:hover { background: var(--fill); }
/* Full-entry popup (mirrors the help overlay). */
.log-ov { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; background: rgba(0,0,0,.4); }
.log-ov[hidden] { display: none; }
.log-ov-box { width: min(760px, 92vw); max-height: 84vh; overflow: auto; background: var(--panel);
  border: 1px solid var(--border-soft); border-radius: 12px; padding: 18px; box-shadow: 0 20px 60px rgba(0,0,0,.4); }
/* Theme-aware grey (the old near-white tint was invisible on the light card);
   the inset outline keeps it reading as a badge without changing its size. */
.pill.neutral { background: var(--fill2); color: var(--text); box-shadow: inset 0 0 0 1px var(--border-soft); }
/* Two important roles at once (admin + power / admin + user): one badge whose
   background gently floats between the two role colours (--c1 → --c2). */
.pill.combo { color: #fff; font-weight: 600; letter-spacing: .3px;
  background: linear-gradient(90deg, var(--c1), var(--c2), var(--c1));
  background-size: 220% 100%; animation: pillFloat 4s ease-in-out infinite; }
.pill.combo .sep { opacity: .6; margin: 0 1px; font-weight: 400; }
@keyframes pillFloat { 0%,100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
@media (prefers-reduced-motion: reduce) { .pill.combo { animation: none; } }
.u-ident { display: flex; flex-direction: column; line-height: 1.2; white-space: nowrap; }
.u-real { font-size: 11px; color: var(--muted); margin-top: 1px; }
/* Two-line user cards in a scroll box (~5 rows tall) so every control stays
   inside the card no matter how many per-user toggles there are. */
.user-list { max-height: 340px; overflow-y: auto; border: 1px solid var(--border);
  border-radius: 10px; }
.user-card { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px;
  border-bottom: 1px solid var(--border); }
.user-card:last-child { border-bottom: none; }
.user-card .row1, .user-card .row2 { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.user-card .perm { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--muted); }
.user-card .perm input { width: auto; }
.user-empty { padding: 14px; color: var(--muted); }
.user-search { width: 100%; margin-bottom: 10px; }
/* Master row directly above the list — its checkboxes toggle the Passkey / 2FA
   columns for every user, and sit over the per-user toggles in each card. */
.user-allrow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 6px 12px; }
.seg { display: inline-flex; background: var(--fill); border-radius: 8px; padding: 3px; gap: 3px; }
.seg button { border: none; background: none; color: var(--text); padding: 6px 14px; border-radius: 6px; font-size: 13px; }
.seg button.sel { background: rgba(10,132,255,.22); color: var(--accent); font-weight: 600;
  box-shadow: inset 0 0 0 1px rgba(10,132,255,.35); }
.seg button.sel .subtle { color: var(--accent); }
.theme-seg { padding: 2px; }
.theme-seg button { padding: 5px 10px; font-size: 15px; line-height: 1; }
.banner { border-radius: var(--radius); padding: 12px 16px; margin: 14px 0; font-size: 13px; }
.banner.warn { background: rgba(255,159,10,.12); border: 1px solid rgba(255,159,10,.4); }
.banner.info { background: rgba(10,132,255,.1); border: 1px solid rgba(10,132,255,.3); }
.banner.ok { background: rgba(48,209,88,.12); border: 1px solid rgba(48,209,88,.4); }
.banner.err { background: rgba(255,69,58,.12); border: 1px solid rgba(255,69,58,.45); }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.subtle { font-size: 12px; color: var(--tertiary); }
details summary { cursor: pointer; font-size: 13px; color: var(--accent); padding: 6px 0; }
.toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%); padding: 10px 16px;
  border-radius: 10px; background: var(--panel2); border: 1px solid var(--border); box-shadow: var(--shadow);
  font-size: 13px; opacity: 0; transition: opacity .2s; pointer-events: none; z-index: 50; }
.toast.show { opacity: 1; }
.toast.err { border-color: rgba(255,69,58,.5); }
/* Help overlay — mirrors the main app's Help panel (the master): a clean
   borderless table of contents with a soft-accent active row, a subtle title
   bar, and a titled content pane. */
.help-ov { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center;
  background: rgba(0,0,0,.4); padding: 24px; }
.help-ov[hidden] { display: none; }
.help-ov-panel { width: min(880px, 100%); height: min(640px, 90vh); display: flex; flex-direction: column;
  background: var(--panel); border: 1px solid var(--border-soft); border-radius: var(--radius);
  box-shadow: var(--shadow); overflow: hidden; }
.help-ov-bar { display: flex; align-items: center; gap: 10px; padding: 11px 14px;
  background: rgba(120,120,128,.08); font-weight: 600; }
.help-ov-bar .spacer { flex: 1; }
.help-ov-body { display: flex; flex: 1; min-height: 0; }
.help-ov-nav { width: 210px; flex-shrink: 0; overflow-y: auto; padding: 8px;
  border-right: 1px solid var(--border-soft); display: flex; flex-direction: column; gap: 2px; }
.help-ov-nav button { display: flex; align-items: center; gap: 6px; width: 100%; text-align: left;
  border: none; background: none; color: var(--text); padding: 6px 10px; border-radius: 8px; font-size: 13px; }
.help-ov-nav button:hover { background: var(--fill); }
.help-ov-nav button.sel { background: rgba(10,132,255,.14); color: var(--accent); font-weight: 600; }
.help-ov-content { flex: 1; overflow-y: auto; padding: 20px 24px; font-size: 13px; line-height: 1.55; }
.help-ov-content h2 { font-size: 20px; font-weight: 700; margin: 0 0 12px; padding-bottom: 10px;
  border-bottom: 1px solid var(--border-soft); }
.help-ov-content p { margin: 0 0 10px; color: var(--text); }
.help-ov-content .note { padding: 8px 12px; border-radius: 8px; margin: 10px 0 0;
  background: rgba(10,132,255,.1); border: 1px solid rgba(10,132,255,.28); }
.help-ov-content .warn { background: rgba(255,159,10,.12); border-color: rgba(255,159,10,.32); }
/* Profile overlay — the admin's own account (password / passkeys / two-factor). */
.prof-ov { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center;
  background: rgba(0,0,0,.4); padding: 24px; }
.prof-ov[hidden] { display: none; }
.prof-ov-panel { width: min(620px, 100%); max-height: 90vh; display: flex; flex-direction: column;
  background: var(--panel); border: 1px solid var(--border-soft); border-radius: var(--radius);
  box-shadow: var(--shadow); overflow: hidden; }
.prof-ov-bar { display: flex; align-items: center; gap: 10px; padding: 11px 14px;
  background: rgba(120,120,128,.08); font-weight: 600; }
.prof-ov-bar .spacer { flex: 1; }
.prof-ov-body { flex: 1; overflow-y: auto; padding: 16px 22px 22px; }
/* The admin tab strip is two stacked rows, each a theme; the container carries the
   underline so a selected tab in either row shows its accent mark directly beneath it. */
.tabbar { border-bottom: 1px solid var(--border-soft); margin: 8px 0 4px; }
.tabs { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.tabs + .tabs { margin-top: 2px; }
.tabs .tabgroup { align-self: center; color: var(--muted); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .04em; opacity: .65; padding: 0 10px 0 2px;
  min-width: 116px; }
.tabs button { background: none; border: none; color: var(--muted); padding: 10px 16px; font-size: 14px;
  border-bottom: 2px solid transparent; margin-bottom: -1px; white-space: nowrap; }
.tabs button.sel { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
.tabpanel { display: none; }
.tabpanel.sel { display: block; }
/* Inner tabs inside the connection editor (Database / LLM / Projects). */
.ctabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border-soft); margin: 2px 0 14px; }
.ctabs button { background: none; border: none; color: var(--muted); padding: 8px 14px; font-size: 13px;
  border-bottom: 2px solid transparent; margin-bottom: -1px; cursor: pointer; }
.ctabs button.sel { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
.ctabs button:disabled { opacity: .45; cursor: not-allowed; }
.ctabpanel { display: none; }
/* min-height keeps the editor a stable height across tabs, so switching to a shorter
   panel (LLM/Projects) doesn't collapse the page and bounce the scroll position. */
.ctabpanel.sel { display: block; min-height: 320px; }
.assign-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 6px; }
.assign-grid label { display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 5px 8px;
  border-radius: 6px; background: var(--fill); }
.editor { border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; margin-top: 14px;
  background: var(--panel2); }
@media (max-width: 720px){ .grid2 { grid-template-columns: 1fr; } }
"""


def login_page(error: str = "", inactivity: bool = False, bg_css: str = "",
               mfa_step: bool = False, mfa_setup: bool = False, mfa_qr: str = "",
               recovery_codes: "list[str] | None" = None) -> str:
    """The admin sign-in screen — a faithful port of the main app's login panel
    (`LoginView.tsx`, the master): identical layout, field sizing and behaviour
    (submit stays disabled until a username is entered). The ONLY difference is
    the two-line title (Process Mining Demonstrator / Administration).

    ``bg_css`` overrides the page background (admin Customize tab). It is a value
    already validated by the security store, safe to inject; blank keeps the
    theme colour."""
    # Custom background chosen in the admin Customize tab, or the theme default.
    body_bg = bg_css or "var(--l-grouped)"
    # Over a custom background image, make the panel 50% transparent so the image
    # shows through (a colour/default background keeps the panel solid).
    panel_class = " translucent" if "url(" in body_bg else ""
    err = (
        f'<div class="login-err">{html.escape(error)}</div>' if error else ""
    )
    # Same inactivity notice the app shows (LoginView.tsx); error takes precedence.
    notice = (
        '<div class="login-notice">You were signed out due to inactivity.</div>'
        if inactivity and not error
        else ""
    )
    caption = (
        "Two-factor is on" if recovery_codes is not None
        else "Set up two-factor to continue" if mfa_setup
        else "Enter your authentication code" if mfa_step
        else "Sign in to continue"
    )
    if recovery_codes is not None:
        # Shown once, right after mandatory enrolment — the session cookie is already
        # set on this response, so "Continue" (a GET to /) lands signed in.
        grid = "".join(f"<span>{html.escape(c)}</span>" for c in recovery_codes)
        form_block = (
            '  <div class="login-notice"><strong>Save your recovery codes.</strong> '
            'Each works once if you lose your authenticator; they won&rsquo;t be shown again.</div>\n'
            '  <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; width:100%; '
            'font-family:monospace; font-size:13px; padding:10px 12px; border-radius:6px; '
            'background:var(--l-fill)">' + grid + '</div>\n'
            '  <a class="btn-prominent" href="/" style="text-align:center; text-decoration:none">'
            'Continue to the admin panel</a>'
        )
    elif mfa_setup:
        # Two-factor is required for this admin but not configured — force enrolment
        # before a session is issued. Server-rendered QR + a plain form POST to
        # /login/mfa-setup. mfa_qr is our own generated SVG, safe to inject.
        form_block = (
            '  <div class="t-caption2" style="text-align:center; margin-bottom:6px">'
            'Two-factor is required for your account. Scan this with an authenticator app '
            '(Google Authenticator, 1Password…), then enter the 6-digit code.</div>\n'
            '  <div style="align-self:center; width:168px; height:168px; background:#fff; '
            'padding:8px; border-radius:8px">' + mfa_qr + '</div>\n'
            '  <form class="login-form" method="post" action="/login/mfa-setup">\n'
            '    <div class="field"><label class="field-label" for="code">6-digit code</label>\n'
            '      <input class="text-input" id="code" name="code" inputmode="numeric" '
            'autocomplete="one-time-code" autocapitalize="none" autocorrect="off" autofocus '
            'placeholder="123456"></div>\n'
            '    <div class="btn-row"><button class="btn-prominent" type="submit">'
            'Confirm &amp; sign in</button></div>\n'
            '  </form>'
        )
    elif mfa_step:
        # Second step: the password already verified, ask for the TOTP (or recovery)
        # code. A plain form POST to /login/mfa — no JS, no passkey button.
        form_block = """  <form class="login-form" method="post" action="/login/mfa">
    <div class="field"><label class="field-label" for="code">Authentication code</label>
      <input class="text-input" id="code" name="code" inputmode="numeric" autocomplete="one-time-code"
        autocapitalize="none" autocorrect="off" autofocus placeholder="6-digit code or a recovery code"></div>
    <div class="btn-row"><button class="btn-prominent" type="submit">Verify</button></div>
  </form>
  <div class="t-caption2" style="text-align:center; margin-top:2px">
    Enter the 6-digit code from your authenticator app, or one of your recovery codes.</div>"""
    else:
        form_block = """  <form class="login-form" method="post" action="/login" id="loginForm">
    <div class="field"><label class="field-label" for="u">Username</label>
      <input class="text-input" id="u" type="text" name="username" autocomplete="username"
        autocapitalize="none" autocorrect="off" autofocus></div>
    <div class="field"><label class="field-label" for="p">Password</label>
      <input class="text-input" id="p" type="password" name="password" autocomplete="current-password"></div>
    <div class="btn-row">
      <button class="btn-prominent" type="submit" id="signin" disabled>
        <span class="spinner" id="spin" style="display:none"></span> Sign in</button>
      <button class="btn-secondary" type="button" id="pkbtn" disabled style="display:none"
        title="Sign in with a passkey (Touch ID, Windows Hello, security key…)">🔑 Sign with Passkey</button>
    </div>
  </form>
  <div id="pkerr" class="login-err" style="display:none"></div>
  <div id="dirStatus" class="dir-row" style="display:none">
    <span id="dirDot" style="width:8px; height:8px; border-radius:50%; flex:0 0 auto"></span>
    <span id="dirLabel" class="t-caption2"></span>
  </div>"""
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{_FAVICON_LINK}{_THEME_BOOT}
<title>Process Mining - Administration</title><style>{_STYLE}
/* App-master (LoginView.tsx) tokens, mirrored so both panels render identically
   in light and dark. Rules are scoped under .login-splash so they win over the
   base input/button styles in _STYLE. */
:root {{
  --l-material: rgba(255,255,255,.82);
  /* Layered elevation so the panel floats above any background — colour or photo —
     with a faint hairline ring keeping its edge legible over imagery. The far,
     ultra-diffuse layers give it real virtual distance (higher = larger, softer,
     more offset shadow). Kept in sync with the app's .splash. */
  --l-shadow: 0 0 0 0.5px rgba(0,0,0,.08), 0 6px 18px rgba(0,0,0,.2),
    0 28px 56px rgba(0,0,0,.3), 0 60px 120px rgba(0,0,0,.4),
    0 110px 200px rgba(0,0,0,.46);
  --l-primary: #000; --l-secondary: rgba(60,60,67,.6);
  --l-fill: rgba(120,120,128,.12); --l-grouped: #f2f2f7;
}}
:root[data-theme='dark'] {{
  --l-material: rgba(38,38,40,.86);
  --l-shadow: 0 0 0 0.5px rgba(255,255,255,.1), 0 6px 18px rgba(0,0,0,.62),
    0 28px 60px rgba(0,0,0,.74), 0 64px 130px rgba(0,0,0,.82),
    0 120px 210px rgba(0,0,0,.86);
  --l-primary: #fff; --l-secondary: rgba(235,235,245,.6);
  --l-fill: rgba(120,120,128,.24); --l-grouped: #000;
}}
body {{ display: grid; place-items: center; min-height: 100vh; background: {body_bg}; padding: 24px; }}
.login-splash {{ width: min(460px, 100%); border-radius: 20px; background: var(--l-material);
  -webkit-backdrop-filter: blur(30px); backdrop-filter: blur(30px); box-shadow: var(--l-shadow);
  padding: 32px 28px; display: flex; flex-direction: column; align-items: center; gap: 16px; text-align: center; }}
/* Over a background image the panel is 50% transparent; content stays opaque. */
.login-splash.translucent {{ background: rgba(255,255,255,.5); }}
:root[data-theme='dark'] .login-splash.translucent {{ background: rgba(38,38,40,.5); }}
.login-splash .login-logo {{ width: 64px; height: 64px; border-radius: 11px; display: grid; place-items: center;
  background: none; box-shadow: 0 2px 6px rgba(10,20,60,.28); flex-shrink: 0; }}
.login-splash .login-logo .pm-logo {{ width: 100%; height: 100%; }}
.login-splash .title-col {{ display: flex; flex-direction: column; align-items: center; gap: 2px; }}
.login-splash .t-title3 {{ font-size: 20px; font-weight: 700; color: var(--l-primary); line-height: 1.2; }}
.login-splash .t-caption {{ font-size: 11px; color: var(--l-secondary); }}
.login-splash .login-form {{ display: flex; flex-direction: column; align-items: center; gap: 16px; width: 100%; }}
.login-splash .field {{ display: flex; flex-direction: column; gap: 3px; width: 100%; text-align: left; }}
.login-splash .field-label {{ font-size: 11px; color: var(--l-secondary); }}
.login-splash .text-input {{ width: 100%; padding: 5px 8px; font-size: 12px; border-radius: 6px;
  border: 1px solid transparent; background: var(--l-fill); color: var(--l-primary); outline: none; }}
.login-splash .text-input:focus {{ border-color: transparent; }}
.login-splash .btn-prominent {{ width: 100%; padding: 10px; font-size: 15px; font-weight: 500; border-radius: 6px;
  display: inline-flex; align-items: center; justify-content: center; gap: 5px;
  background: var(--accent); color: #fff; border: none; white-space: nowrap; }}
.login-splash .btn-prominent:hover:not(:disabled) {{ filter: brightness(1.08); }}
.login-splash .btn-prominent:disabled {{ opacity: .4; cursor: default; }}
.login-splash .btn-row {{ display: flex; gap: 8px; width: 100%; }}
.login-splash .btn-row .btn-prominent {{ flex: 1; }}
.login-splash .btn-secondary {{ width: auto; padding: 10px 12px; font-size: 15px; font-weight: 500; border-radius: 6px;
  display: inline-flex; align-items: center; justify-content: center; gap: 5px; white-space: nowrap;
  background: var(--l-fill); color: var(--l-primary); border: 1px solid var(--l-border, rgba(0,0,0,.12)); cursor: pointer; }}
.login-splash .btn-secondary:hover:not(:disabled) {{ filter: brightness(.97); }}
.login-splash .btn-secondary:disabled {{ opacity: .4; cursor: default; }}
.login-splash .login-err, .login-splash .login-notice {{ width: 100%; padding: 10px 12px; border-radius: 6px;
  font-size: 12px; text-align: left; }}
.login-splash .login-err {{ background: rgba(255,59,48,.12); border: 1px solid rgba(255,59,48,.32); color: #ff3b30; }}
.login-splash .login-notice {{ background: rgba(255,159,10,.12); border: 1px solid rgba(255,159,10,.32); color: #ff9500; text-align: center; }}
.login-splash .dir-row {{ display: flex; align-items: center; gap: 6px; }}
.login-splash .t-caption2 {{ font-size: 10px; color: var(--l-secondary); }}
.login-splash .spinner {{ width: 16px; height: 16px; border-radius: 50%; border: 2px solid rgba(255,255,255,.4);
  border-top-color: #fff; animation: spin .8s linear infinite; display: inline-block; }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style></head><body>
<div class="login-splash{panel_class}">
  <div class="login-logo">{_LOGO_SVG}</div>
  <div class="title-col">
    <span class="t-title3">Process Mining Demonstrator</span>
    <span class="t-title3">Administration</span>
    <span class="t-caption">{caption}</span>
    <span class="t-caption2">{html.escape(APP_VERSION)}</span>
  </div>
  {notice}{err}
{form_block}
</div>
<script>
// The inactivity notice is a one-time message: strip ?inactivity from the URL after
// render so a refresh doesn't show it again. This mirrors the app/integration panels,
// whose sign-out reason is an in-memory flag that a page reload clears.
(function () {{
  if (!window.history || !history.replaceState) return;
  var p = new URLSearchParams(location.search);
  if (!p.has('inactivity')) return;
  p.delete('inactivity');
  var q = p.toString();
  history.replaceState(null, '', location.pathname + (q ? '?' + q : '') + location.hash);
}})();
// Submit stays disabled until a username is entered — mirrors the app's LoginView.
(function () {{
  var u = document.getElementById('u'), btn = document.getElementById('signin');
  var form = document.getElementById('loginForm'), spin = document.getElementById('spin');
  if (!u || !btn || !form) return;  // absent on the 2FA code step
  function sync() {{ btn.disabled = !u.value.trim(); }}
  u.addEventListener('input', sync); sync();
  form.addEventListener('submit', function () {{
    if (btn.disabled) return;
    btn.disabled = true; spin.style.display = 'inline-block';  // busy state during the POST
  }});
}})();
// Passkey sign-in — an alternative to the password, shown when the browser supports WebAuthn.
(function () {{
  var u = document.getElementById('u'), pk = document.getElementById('pkbtn');
  var err = document.getElementById('pkerr');
  if (!u || !pk) return;  // absent on the 2FA code step
  if (!window.PublicKeyCredential || !navigator.credentials) return;
  // WebAuthn rejects bare IP addresses / single-label hosts as the RP ID — hide
  // the button when reached by IP so it isn't offered where it can't work.
  var h = location.hostname;
  var domainOk = h === 'localhost'
    || (!/^\\d{{1,3}}(\\.\\d{{1,3}}){{3}}$/.test(h) && h.indexOf(':') < 0 && h.charAt(0) !== '[' && h.indexOf('.') >= 0);
  if (!domainOk) return;
  pk.style.display = 'inline-flex';
  function sync() {{ pk.disabled = !u.value.trim(); }}
  u.addEventListener('input', function () {{ sync(); err.style.display = 'none'; }}); sync();
  function b2b(b) {{ var a = new Uint8Array(b), s = '';
    for (var i = 0; i < a.length; i++) s += String.fromCharCode(a[i]);
    return btoa(s).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, ''); }}
  function b2a(s) {{ var pad = s.length % 4 === 0 ? '' : '='.repeat(4 - (s.length % 4));
    var bin = atob(s.replace(/-/g, '+').replace(/_/g, '/') + pad), a = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a.buffer; }}
  pk.addEventListener('click', async function () {{
    var name = u.value.trim(); if (!name) return;
    pk.disabled = true; err.style.display = 'none';
    try {{
      var beginResp = await fetch('/login/passkey/begin', {{ method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify({{ username: name }}) }});
      if (!beginResp.ok) throw new Error('unavailable');
      var opt = await beginResp.json();
      var publicKey = {{ challenge: b2a(opt.challenge), rpId: opt.rpId, timeout: opt.timeout,
        userVerification: opt.userVerification,
        allowCredentials: (opt.allowCredentials || []).map(function (c) {{
          return {{ id: b2a(c.id), type: c.type, transports: c.transports }}; }}) }};
      var assertion = await navigator.credentials.get({{ publicKey: publicKey }});
      if (!assertion) throw new Error('cancelled');
      var r = assertion.response;
      var cred = {{ id: assertion.id, rawId: b2b(assertion.rawId), type: assertion.type,
        response: {{ clientDataJSON: b2b(r.clientDataJSON), authenticatorData: b2b(r.authenticatorData),
          signature: b2b(r.signature), userHandle: r.userHandle ? b2b(r.userHandle) : undefined }},
        clientExtensionResults: assertion.getClientExtensionResults(),
        authenticatorAttachment: assertion.authenticatorAttachment || undefined }};
      var finishResp = await fetch('/login/passkey/finish', {{ method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify({{ credential: cred }}) }});
      if (!finishResp.ok) throw new Error('failed');
      window.location.href = '/';
    }} catch (e) {{
      pk.disabled = !u.value.trim();
      if (e && (e.name === 'NotAllowedError' || e.name === 'AbortError')) return;  // user cancelled
      err.textContent = 'Passkey sign-in failed. Check the passkey is registered and still enabled.';
      err.style.display = 'block';
    }}
  }});
}})();
// Directory-server availability LED — shown only when a directory is configured.
(async function () {{
  try {{
    const s = await (await fetch('/api/directory-status')).json();
    if (!s.configured) return;
    const ok = !!s.available;
    const color = ok ? 'var(--green)' : 'var(--red)';
    const dot = document.getElementById('dirDot');
    dot.style.background = color;
    dot.style.boxShadow = '0 0 6px ' + color;
    document.getElementById('dirLabel').textContent =
      'Directory server ' + (ok ? 'available' : 'unavailable');
    document.getElementById('dirStatus').style.display = 'flex';
  }} catch (e) {{ /* never block the login screen */ }}
}})();
</script>
</body></html>"""


def dashboard_page(username: str, http_port: int, https_port: int) -> str:
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{_FAVICON_LINK}{_THEME_BOOT}
<title>Process Mining - Administration</title><style>{_STYLE}</style></head><body>
<div class="topbar">
  <div class="brand"><div class="logo">{_LOGO_SVG}</div>
    <div><h1>Administration</h1><div class="sub">Process Mining Demonstrator</div></div></div>
  <div class="spacer"></div>
  <div class="seg theme-seg" id="themeSeg" title="Appearance">
    <button data-theme-choice="system" title="System" aria-label="System theme" onclick="setTheme('system')">◐</button>
    <button data-theme-choice="light" title="Light" aria-label="Light theme" onclick="setTheme('light')">☀</button>
    <button data-theme-choice="dark" title="Dark" aria-label="Dark theme" onclick="setTheme('dark')">☾</button>
  </div>
  <span class="muted">Signed in as <strong id="who">{html.escape(username)}</strong></span>
  <button class="btn small" onclick="openHelp()" title="Administration help">❔ Help</button>
  <button class="btn small" onclick="openProfile()" title="Your account: password, passkeys, two-factor">👤 Profile</button>
  <form method="post" action="/logout" style="display:inline"><button class="btn small">Log out</button></form>
</div>
<div class="help-ov" id="helpOv" hidden onclick="if(event.target===this)closeHelp()">
  <div class="help-ov-panel" role="dialog" aria-label="Administration help">
    <div class="help-ov-bar"><span aria-hidden>⚙︎</span><span class="spacer">Administration</span>
      <button class="btn small" onclick="closeHelp()" aria-label="Close help">✕</button></div>
    <div class="help-ov-body">
      <nav class="help-ov-nav" id="helpNav"></nav>
      <div class="help-ov-content" id="helpContent"></div>
    </div>
  </div>
</div>
<div class="prof-ov" id="profOv" hidden onclick="if(event.target===this)closeProfile()">
  <div class="prof-ov-panel" role="dialog" aria-label="Your profile">
    <div class="prof-ov-bar"><span aria-hidden>👤</span><span class="spacer">Profile</span>
      <button class="btn small" onclick="closeProfile()" aria-label="Close profile">✕</button></div>
    <div class="prof-ov-body">
      <p class="muted" style="margin-top:0">Your own admin account — password, passkeys and two-factor.
        These protect both this admin interface and the main app.</p>

      <h3>Password</h3>
      <div class="row" style="gap:8px; flex-wrap:wrap; align-items:flex-end">
        <div class="field"><label>New password</label>
          <input type="password" id="ownPw1" autocomplete="new-password" style="min-width:180px"></div>
        <div class="field"><label>Confirm</label>
          <input type="password" id="ownPw2" autocomplete="new-password" style="min-width:180px"></div>
        <button class="btn primary" onclick="changeOwnPassword()">Change password</button>
      </div>
      <div id="ownPwResult" class="col" style="margin-top:8px"></div>

      <h3>Passkeys</h3>
      <p class="muted" style="margin-top:0">Sign in with Touch&nbsp;ID, Windows&nbsp;Hello, or a security
        key instead of your password (which always remains a fallback). Passkeys must be enabled for your
        account (Users tab) before you can add one; the same passkey works on both the app and this panel.</p>
      <div id="pkAdminNote" class="banner info" style="margin-top:4px">Checking passkeys…</div>
      <div id="pkAdminList" class="col" style="gap:6px; margin-top:10px"></div>
      <div class="row" id="pkAdminAdd" style="gap:8px; flex-wrap:wrap; align-items:flex-end; margin-top:12px; display:none">
        <div class="field"><label>Passkey name</label>
          <input type="text" id="pkAdminName" placeholder="e.g. MacBook Touch ID" style="min-width:220px"></div>
        <button class="btn primary" onclick="addAdminPasskey()">Add a passkey</button>
      </div>
      <div id="pkAdminResult" class="col" style="margin-top:8px"></div>

      <h3>Two-factor authentication</h3>
      <p class="muted" style="margin-top:0">Add a one-time code from an authenticator app (Google
        Authenticator, 1Password, Authy&hellip;) on top of your password when signing in to this admin
        interface and the main app. Your password still signs you in &mdash; the code is an extra step.
        Two-factor must be enabled for your account (Users tab) before you can set it up.</p>
      <div id="mfaAdminNote" class="banner info" style="margin-top:4px">Checking two-factor&hellip;</div>
      <div id="mfaAdminSetup" style="display:none; margin-top:12px">
        <div class="row" style="gap:16px; flex-wrap:wrap; align-items:flex-start">
          <div id="mfaQr" style="width:180px; height:180px; background:#fff; padding:8px; border-radius:8px"></div>
          <div class="col" style="gap:8px; min-width:200px; flex:1">
            <span class="muted" style="font-size:13px">Scan the QR with your authenticator app, then enter the 6-digit code it shows.</span>
            <span class="subtle" style="word-break:break-all">Can&rsquo;t scan? Key: <strong id="mfaSecret"></strong></span>
            <div class="row" style="gap:8px; align-items:flex-end">
              <div class="field"><label>6-digit code</label>
                <input type="text" id="mfaCode" inputmode="numeric" autocomplete="one-time-code" style="width:140px"></div>
              <button class="btn primary" onclick="confirmAdminMfa()">Confirm</button>
              <button class="btn" onclick="cancelAdminMfa()">Cancel</button>
            </div>
          </div>
        </div>
      </div>
      <div id="mfaRecovery" style="display:none; margin-top:12px"></div>
      <div class="row" id="mfaAdminActions" style="gap:8px; flex-wrap:wrap; margin-top:12px; display:none">
        <button class="btn primary" id="mfaSetupBtn" onclick="beginAdminMfa()">Set up authenticator</button>
        <button class="btn" id="mfaRegenBtn" onclick="regenAdminMfa()" style="display:none">Regenerate recovery codes</button>
        <button class="btn" id="mfaOffBtn" onclick="disableAdminMfa()" style="display:none">Turn off</button>
      </div>
      <div id="mfaAdminResult" class="col" style="margin-top:8px"></div>
    </div>
  </div>
</div>
<div class="wrap">
  <div id="defaultWarn"></div>

  <div class="tabbar">
    <div class="tabs">
      <span class="tabgroup">Platform &amp; Security</span>
      <button data-tab="appcontrol" class="sel" onclick="selectTab('appcontrol')">App Control</button>
      <button data-tab="tls" onclick="selectTab('tls')">TLS / SSL</button>
      <button data-tab="users" onclick="selectTab('users')">Users</button>
      <button data-tab="ldap" onclick="selectTab('ldap')">Directory (LDAP)</button>
      <button data-tab="logging" onclick="selectTab('logging')">Logging</button>
      <button data-tab="backup" onclick="selectTab('backup')">Backup</button>
    </div>
    <div class="tabs">
      <span class="tabgroup">Data &amp; Features</span>
      <button data-tab="connections" onclick="selectTab('connections')">Database Connections</button>
      <button data-tab="integration" onclick="selectTab('integration')">Integration</button>
      <button data-tab="sink" onclick="selectTab('sink')">Event Receiver</button>
      <button data-tab="mcp" onclick="selectTab('mcp')">MCP Server</button>
      <button data-tab="actions" onclick="selectTab('actions')">Actions</button>
      <button data-tab="reporting" onclick="selectTab('reporting')">Reporting</button>
      <button data-tab="customize" onclick="selectTab('customize')">Customize</button>
    </div>
  </div>

  <div class="tabpanel sel" id="tab-appcontrol">
  <div class="card">
    <h2>App Control</h2>
    <p class="muted" style="margin-top:0">Operational controls for the running servers.</p>
    <div class="row" style="flex-wrap:wrap; align-items:center; gap:12px">
      <button class="btn primary" onclick="restartServer()" title="Rebind the app + admin listeners with the current TLS settings">↻ Restart app server</button>
      <span class="subtle">Rebinds the main application and this admin interface in place with the current TLS mode &amp; active certificate — no terminal needed.</span>
    </div>
    <div class="banner info" style="margin-top:14px">
      TLS mode and certificate changes (in the <strong>TLS / SSL</strong> tab) take effect on restart.
      This restarts <strong>the app, the integration console and the admin interface</strong> (they share the certificate),
      so this page may briefly drop — and if you changed the mode, the admin moves between
      HTTP <code>:8090</code> and HTTPS <code>:8453</code>; reconnect there if it stops responding.
    </div>
    <div id="restartResult" class="col" style="margin-top:8px"></div>
  </div>
  <div class="card">
    <h2>License</h2>
    <p class="muted" style="margin-top:0">The compute backend requires a valid license.
      Without one it runs for a short grace period and then stops. Upload the
      <code>license.json</code> you were issued to apply it.</p>
    <div id="licenseStatus" class="banner info" style="margin-top:4px">Checking license…</div>
    <div class="row" style="flex-wrap:wrap; align-items:center; gap:12px; margin-top:12px">
      <input type="file" id="licenseFile" accept=".json,application/json">
      <button class="btn primary" onclick="uploadLicense()">Upload license</button>
      <button class="btn" onclick="deleteLicense()">Delete license</button>
      <span class="subtle">The signature is verified before the license is stored.</span>
    </div>
    <div id="licenseResult" class="col" style="margin-top:8px"></div>
  </div>
  <div class="card">
    <h2>Admin session</h2>
    <p class="muted" style="margin-top:0">Automatically sign out of <strong>this admin interface</strong>
      after a period of inactivity. This is separate from the main app's auto sign-out (set in the Users tab).</p>
    <div class="banner info" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
      <label class="row" style="font-size:13px; gap:8px">
        Auto sign-out after
        <input type="number" id="adminIdleTimeout" min="0" max="1440" step="1" style="width:80px"> minutes of inactivity
      </label>
      <button class="btn small" onclick="saveAdminIdleTimeout()">Save</button>
      <span class="subtle" id="adminIdleTimeoutHint"></span>
    </div>
  </div>
  <div class="card">
    <h2>Timezone</h2>
    <p class="muted" style="margin-top:0">The timezone used for all admin timestamps &mdash; the log
      viewer and exported logs, backup times and the backup schedule (e.g. &ldquo;daily at 02:00&rdquo;
      fires at 02:00 here). Leave as <em>Server local</em> to follow the server's own clock. The main app
      shows each user their own browser's local time.</p>
    <div class="row" style="gap:8px; flex-wrap:wrap; align-items:flex-end">
      <div class="field"><label>Display timezone</label>
        <select id="displayTz" onchange="previewTz()" style="min-width:260px"></select></div>
      <button class="btn primary" onclick="saveDisplayTimezone()">Save</button>
    </div>
    <div class="muted" id="tzPreview" style="font-size:13px; margin-top:8px"></div>
  </div>
  </div><!-- /tab-appcontrol -->

  <div class="tabpanel" id="tab-tls">
  <div class="card">
    <h2>TLS / SSL</h2>
    <p class="muted" style="margin-top:0">Choose how the main application (the GUI server) accepts connections.</p>
    <div class="row" style="flex-wrap:wrap">
      <div class="seg" id="tlsSeg">
        <button data-mode="off">Off (HTTP only)</button>
        <button data-mode="optional">Optional (HTTP + HTTPS)</button>
        <button data-mode="required">Required (HTTPS only)</button>
      </div>
      <button class="btn primary" onclick="saveTlsMode()">Save mode</button>
    </div>
    <div id="tlsPlan" class="col" style="margin-top:12px"></div>
    <p class="subtle" style="margin-top:10px">Mode &amp; certificate changes take effect after a restart — use <strong>↻ Restart app server</strong> in the <strong>App Control</strong> tab.</p>
  </div>

  <div class="card">
    <h2>Certificates</h2>
    <div id="certTable"></div>
    <div class="grid2" style="margin-top:16px">
      <div class="col">
        <h2 style="font-size:13px">Generate self-signed</h2>
        <div class="field"><label>Name</label><input type="text" id="g_name" placeholder="e.g. Internal 2026"></div>
        <div class="field"><label>Common name / host</label><input type="text" id="g_cn" placeholder="processmining.example.com"></div>
        <div class="field"><label>Additional SANs (comma-separated DNS / IPs)</label>
          <input type="text" id="g_sans" placeholder="localhost, 127.0.0.1"></div>
        <div class="row">
          <div class="field" style="flex:1"><label>Valid for (days)</label><input type="number" id="g_days" value="825" min="1" max="3650"></div>
          <div class="field" style="flex:1"><label>Key size</label>
            <select id="g_keysize"><option>2048</option><option>3072</option><option>4096</option></select></div>
        </div>
        <div class="col" style="margin-top:auto">
          <label class="row" style="font-size:13px"><input type="checkbox" id="g_activate" style="width:auto"> Activate after generating</label>
          <button class="btn primary" onclick="generateCert()">Generate</button>
        </div>
      </div>
      <div class="col">
        <h2 style="font-size:13px">Upload certificate</h2>
        <div class="field"><label>Name</label><input type="text" id="u_name" placeholder="e.g. Corporate CA"></div>
        <div class="field"><label>Certificate (PEM)</label><textarea id="u_cert" placeholder="-----BEGIN CERTIFICATE-----"></textarea></div>
        <div class="field"><label>Private key (PEM, unencrypted)</label><textarea id="u_key" placeholder="-----BEGIN PRIVATE KEY-----"></textarea></div>
        <div class="col" style="margin-top:auto">
          <label class="row" style="font-size:13px"><input type="checkbox" id="u_activate" style="width:auto"> Activate after uploading</label>
          <button class="btn primary" onclick="uploadCert()">Upload</button>
        </div>
      </div>
    </div>
  </div>
  </div><!-- /tab-tls -->

  <div class="tabpanel" id="tab-users">
  <div class="card">
    <h2>Users</h2>
    <p class="muted" style="margin-top:0">Only enabled users will be allowed to sign in to the main application.</p>
    <div class="banner info" style="display:flex; align-items:center; gap:12px">
      <label class="row" style="font-size:13px; cursor:pointer">
        <input type="checkbox" id="requireLogin" style="width:auto" onchange="saveRequireLogin()"> Require sign-in for the main application
      </label>
      <span class="subtle" id="requireLoginHint"></span>
    </div>
    <div class="banner info" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
      <label class="row" style="font-size:13px; gap:8px">
        Auto sign-out after
        <input type="number" id="idleTimeout" min="0" max="1440" step="1" style="width:80px"> minutes of inactivity
      </label>
      <button class="btn small" onclick="saveIdleTimeout()">Save</button>
      <span class="subtle" id="idleTimeoutHint"></span>
    </div>
    <div class="banner info" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
      <label class="row" style="font-size:13px; gap:8px">
        Disable an account after
        <input type="number" id="maxFailedLogins" min="0" max="100" step="1" style="width:80px"> failed sign-in attempts
      </label>
      <button class="btn small" onclick="saveMaxFailedLogins()">Save</button>
      <span class="subtle" id="maxFailedLoginsHint"></span>
    </div>
    <div class="row" style="margin:12px 0 6px; gap:10px; flex-wrap:wrap; align-items:center">
      <div class="seg" id="userFilter"></div>
      <input type="text" id="userSearch" class="user-search" style="flex:1; min-width:180px; width:auto"
        placeholder="Search users by name…" oninput="renderUsers()">
    </div>
    <!-- Master toggles: enable/disable the two per-user columns for everyone at once,
         aligned above the Passkey / 2FA checkboxes in the list below. -->
    <div class="user-allrow">
      <span class="subtle" style="font-size:12px">Passkey and two-factor are optional alternatives/additions to the password (which always works).</span>
      <span class="spacer" style="flex:1"></span>
      <span class="subtle" style="font-size:12px">All users:</span>
      <label class="perm" title="Allow every user to enrol and sign in with a passkey">
        <input type="checkbox" id="passkeyAll" onchange="togglePasskeyAll()"> Passkey</label>
      <label class="perm" title="Allow every user to set up two-factor (TOTP)">
        <input type="checkbox" id="mfaAll" onchange="toggleMfaAll()"> 2FA</label>
    </div>
    <div id="userTable"></div>
    <details style="margin-top:12px"><summary>Add a user</summary>
      <div class="row" style="flex-wrap:wrap; margin-top:10px; align-items:flex-end">
        <div class="field" style="flex:1; min-width:160px"><label>Username</label><input type="text" id="nu_name"></div>
        <div class="field" style="flex:1; min-width:160px"><label>Password</label><input type="password" id="nu_pw"></div>
        <label class="row" style="font-size:13px"><input type="checkbox" id="nu_admin" style="width:auto"> Administrator</label>
        <button class="btn primary" onclick="createUser()">Create user</button>
      </div>
    </details>
  </div>
  </div><!-- /tab-users -->

  <div class="tabpanel" id="tab-connections">
  <div class="card">
    <h2>Database Connections</h2>
    <p class="muted" style="margin-top:0">Define a database (and optional LLM) server, then assign it to the users who may
      use it. Each user sees only the connections assigned to them in the main application.</p>
    <div id="connTable"></div>
    <div class="row" style="margin-top:12px">
      <button class="btn primary" onclick="newConnection()">+ New connection</button>
    </div>

    <div class="editor" id="connEditor" style="display:none">
      <input type="hidden" id="c_id">
      <div class="ctabs">
        <button data-ctab="db" class="sel" onclick="selectConnTab('db')">Database</button>
        <button data-ctab="llm" onclick="selectConnTab('llm')">LLM</button>
        <button data-ctab="projects" id="c_projectsTabBtn" onclick="selectConnTab('projects')">Projects</button>
      </div>

      <div class="ctabpanel sel" id="ctab-db">
      <div class="grid2">
        <div class="col">
          <h2 style="font-size:13px">Database</h2>
          <div class="field"><label>Name</label><input type="text" id="c_name" placeholder="e.g. Production Exasol"></div>
          <div class="field"><label>Comment</label><input type="text" id="c_comment" placeholder="optional"></div>
          <div class="row">
            <div class="field" style="flex:2"><label>Host</label><input type="text" id="c_host" placeholder="db.example.com"></div>
            <div class="field" style="flex:1"><label>Port</label><input type="number" id="c_port" value="8563"></div>
          </div>
          <div class="row">
            <div class="field" style="flex:1"><label>Username</label><input type="text" id="c_username"></div>
            <div class="field" style="flex:1"><label>Schema</label><input type="text" id="c_schema" placeholder="optional"></div>
          </div>
          <div class="field"><label>Password <span class="subtle" id="c_pwHint"></span></label>
            <input type="password" id="c_password" placeholder="••••••••" autocomplete="new-password"></div>
          <label class="row" style="font-size:13px"><input type="checkbox" id="c_useTls" style="width:auto" onchange="toggleTlsFields()"> Use TLS</label>
          <div id="c_tlsFields" style="display:none">
            <div class="field"><label>Certificate mode</label>
              <select id="c_certMode">
                <option value="verify">Verify (system trust store)</option>
                <option value="fingerprint">Pin fingerprint</option>
                <option value="insecure">Accept any (insecure)</option>
              </select></div>
            <div class="field"><label>Fingerprint (SHA-256)</label><input type="text" id="c_fingerprint" placeholder="optional"></div>
            <div class="field"><label>Minimum RSA key size</label><input type="number" id="c_minRsa" value="2048"></div>
          </div>
        </div>
        <div class="col">
          <h2 style="font-size:13px">Assign to users</h2>
          <div class="assign-grid" id="c_assign"></div>
        </div>
      </div>
      <div class="banner info" style="margin-top:14px">
        <div class="row" style="align-items:center; gap:10px">
          <button class="btn" onclick="provisionSchema()">Create schema &amp; tables</button>
          <span id="c_provisionResult" class="muted"></span>
        </div>
        <label class="row" style="font-size:13px; margin-top:8px">
          <input type="checkbox" id="c_provisionBuildMat" style="width:auto">
          Also build pre-materialized transitions after provisioning
        </label>
        <p class="subtle" style="margin:8px 0 0">
          Creates the schema named above and the process-mining tables
          (PROJECTS, JOURNEYS, STEPS, METAS, NOTES) if they don't exist, using the credentials
          entered here. This requires a database account permitted to
          <strong>CREATE SCHEMA</strong> and <strong>CREATE TABLE</strong> — only your database
          administrator can grant those rights; this application cannot.
        </p>
      </div>

      <div class="banner info" style="margin-top:14px">
        <label class="row" style="font-size:13px">
          <input type="checkbox" id="c_useMaterialized" style="width:auto">
          <strong>Use pre-materialized transitions</strong>
        </label>
        <p class="subtle" style="margin:6px 0 12px">
          Reads the process map from a prebuilt <code>TRANSITIONS_RAW</code> table instead of running the
          windowed query live — much faster for interactive filtering on large logs. It falls back to the
          live query until the table is built, so rebuild it after each load of <code>JOURNEYS</code>.
        </p>
        <div class="row" style="align-items:center; gap:12px; flex-wrap:wrap">
          <button class="btn" id="c_rebuildBtn" onclick="rebuildTransitions()">Rebuild now</button>
          <span id="c_matStatus" class="subtle"></span>
          <span id="c_matResult" class="muted"></span>
        </div>

        <details id="c_apiBox" style="margin-top:14px">
          <summary style="cursor:pointer; font-size:13px; font-weight:600">Rebuild from a script (API)</summary>
          <div style="margin-top:10px">
            <p class="subtle" style="margin:0 0 10px">
              Let a scheduler (cron / ETL) rebuild <em>this connection</em> right after loading its
              <code>JOURNEYS</code>, without an admin login. The token below is scoped to this connection only,
              and calls are rate-limited.
            </p>
            <div class="row" style="align-items:center; gap:10px; flex-wrap:wrap">
              <span id="rtStatus" class="subtle"></span>
              <span class="spacer"></span>
              <button class="btn small" onclick="generateRebuildToken()">Generate / rotate token</button>
              <button class="btn small danger" id="rtRevokeBtn" onclick="revokeRebuildToken()">Revoke</button>
            </div>
            <div id="rtValue" style="margin-top:8px"></div>
            <div class="codeblock-wrap" style="margin-top:10px">
              <button class="copy-btn" onclick="copyCurl()" title="Copy to clipboard" aria-label="Copy curl command">📋</button>
              <pre id="api_curl" class="codeblock" style="white-space:pre-wrap; word-break:break-all"></pre>
            </div>
            <p class="subtle" style="margin:6px 0 0">
              The token is shown once — copy it now; only its hash is stored. The <code>Bearer</code> value appears
              in the command only while the token is visible above, then shows <code>&lt;token&gt;</code>.
              <code>-k</code> skips the self-signed TLS check.
            </p>
          </div>
        </details>
      </div>

      <div class="banner info" style="margin-top:14px">
        <label class="row" style="font-size:13px">
          <input type="checkbox" id="c_useInDbSampling" style="width:auto">
          <strong>Build sample sets inside the database</strong>
        </label>
        <p class="subtle" style="margin:6px 0 0">
          Creates each sample slot with a single set-based <code>INSERT … SELECT</code> that picks the
          journeys in SQL, instead of extracting every id to the app and re-inserting them in batches.
          Turn this on for very large logs (hundreds of millions of events), where the app-side path
          times out; small projects can leave it off. Applies to the next sample you create.
        </p>
      </div>
      </div><!-- /ctab-db -->

      <div class="ctabpanel" id="ctab-llm">
        <h2 style="font-size:13px">LLM override (optional)</h2>
        <p class="subtle" style="margin-top:0">Overrides the global <strong>Default language model</strong> (Reporting tab) for AI features on <em>this</em> connection. Leave blank to use the default. Edits apply on the next report — no reconnect needed.</p>
        <div class="field"><label>Server URL</label><input type="text" id="c_llmUrl" placeholder="https://api.openai.com/v1"></div>
        <div class="field"><label>Model</label><input type="text" id="c_llmModel" placeholder="gpt-4o"></div>
        <div class="field"><label>API key <span class="subtle" id="c_llmKeyHint"></span></label>
          <input type="password" id="c_llmKey" placeholder="••••••••" autocomplete="new-password"></div>
      </div>

      <div class="ctabpanel" id="ctab-projects">
        <div class="row" style="align-items:center; gap:10px; margin-bottom:8px">
          <h2 style="font-size:13px; margin:0">Projects in this schema</h2>
          <span class="spacer"></span>
          <button class="btn small" onclick="loadProjects()">↻ Refresh</button>
        </div>
        <p class="subtle" style="margin:0 0 12px">Projects stored in <code id="c_projSchema"></code>, with their journey and event counts.
          Deleting a project clears its rows from every table (PROJECTS, JOURNEYS, STEPS, METAS, NOTES, TRANSITIONS_RAW). This cannot be undone.</p>
        <div id="c_projectsList"><span class="muted">Save the connection first to list its projects.</span></div>
      </div>

      <div class="row" style="margin-top:16px; align-items:center">
        <button class="btn primary" onclick="saveConnection()">Save</button>
        <button class="btn" onclick="testConnection()">Test connection</button>
        <button class="btn" onclick="cancelConnection()">Cancel</button>
        <span class="spacer"></span>
        <button class="btn danger" id="c_deleteBtn" onclick="deleteConnection()" style="display:none">Delete</button>
      </div>
      <div id="c_testResult" class="col" style="margin-top:10px"></div>
    </div>
  </div>
  </div><!-- /tab-connections -->

  <div class="tabpanel" id="tab-ldap">
  <div class="card">
    <h2>Directory (LDAP / Active Directory)</h2>
    <p class="muted" style="margin-top:0">When enabled, the <strong>main application</strong> also accepts sign-ins from an
      LDAP directory (search&nbsp;+&nbsp;bind). Directory users are created here automatically on first login as
      plain, enabled users — grant them a role or database connections like any other user. Local accounts always keep
      working.</p>
    <div class="banner info" style="display:flex; flex-direction:column; align-items:flex-start; gap:10px">
      <label class="row" style="font-size:13px; cursor:pointer">
        <input type="checkbox" id="l_enabled" style="width:auto"> Enable directory sign-in for the main app
      </label>
      <label class="row" style="font-size:13px; cursor:pointer">
        <input type="checkbox" id="l_adminLogin" style="width:auto"> Also allow directory sign-in to <strong>this admin interface</strong>
      </label>
      <p class="subtle" style="margin:0">A directory account can only reach the admin interface once it has been promoted to
        <strong>admin</strong> in the Users tab. Local administrators always work regardless of this setting.</p>
      <label class="row" style="font-size:13px; cursor:pointer">
        <input type="checkbox" id="l_showStatus" style="width:auto"> Show the <strong>Authentication Server</strong> availability indicator on the login panels
      </label>
      <p class="subtle" style="margin:0">When on, both the app and admin sign-in panels display a live LED that reports whether the
        directory server is reachable. Turn it off to hide that indicator from users.</p>
    </div>
    <div class="grid2" style="margin-top:14px; border-bottom:1px solid var(--border); padding-bottom:18px; align-items:stretch">
      <div class="col">
        <h2 style="font-size:13px">Server</h2>
        <div class="field"><label>Server URI</label><input type="text" id="l_uri" placeholder="ldap://dir.example.com:389 or ldaps://dir.example.com:636"></div>
        <label class="row" style="font-size:13px"><input type="checkbox" id="l_startTls" style="width:auto"> Use StartTLS (upgrade a plain ldap:// connection)</label>
        <label class="row" style="font-size:13px"><input type="checkbox" id="l_verify" style="width:auto" checked> Verify server certificate</label>
        <div class="field"><label>CA certificate (PEM, optional)</label><textarea id="l_caCert" placeholder="-----BEGIN CERTIFICATE-----"></textarea></div>
        <p class="subtle">For a lab you can use a plain <code>ldap://</code> URI with StartTLS off — the password is then sent in the clear.</p>
        <div class="row" style="margin-top:auto"><button class="btn" onclick="testLdapServer()">Test server connection</button></div>
        <div id="l_serverTestResult" class="col"></div>
      </div>
      <div class="col">
        <h2 style="font-size:13px">Service account &amp; search</h2>
        <div class="field"><label>Bind DN <span class="subtle">(read-only service account; blank = anonymous)</span></label>
          <input type="text" id="l_bindDN" placeholder="cn=readonly,dc=example,dc=com"></div>
        <div class="field"><label>Bind password <span class="subtle" id="l_bindPwHint"></span></label>
          <input type="password" id="l_bindPw" placeholder="••••••••" autocomplete="new-password"></div>
        <div class="field"><label>Base DN</label><input type="text" id="l_baseDN" placeholder="ou=people,dc=example,dc=com"></div>
        <div class="field"><label>User filter <span class="subtle">(<code>{{username}}</code> is substituted)</span></label>
          <input type="text" id="l_filter" placeholder="(uid={{username}})"></div>
        <div class="row" style="margin-top:auto">
          <div class="field" style="flex:1"><label>Login attribute</label><input type="text" id="l_loginAttr" placeholder="uid"></div>
          <div class="field" style="flex:1"><label>Email attribute</label><input type="text" id="l_emailAttr" placeholder="mail"></div>
          <div class="field" style="flex:1"><label>Name attribute</label><input type="text" id="l_displayAttr" placeholder="cn"></div>
        </div>
      </div>
    </div>
    <div class="banner info" style="margin-top:16px">
      <strong>Test a user login</strong> — resolve a directory account and verify its password
      (search&nbsp;+&nbsp;bind). Use <em>Test server connection</em> above to check the server alone.
      <div class="row" style="flex-wrap:wrap; margin-top:8px; align-items:flex-end">
        <div class="field" style="flex:1; min-width:150px"><label>Test username</label><input type="text" id="l_testUser"></div>
        <div class="field" style="flex:1; min-width:150px"><label>Test password</label><input type="password" id="l_testPw" autocomplete="new-password"></div>
        <button class="btn" onclick="testLdap()">Test</button>
      </div>
      <div id="l_testResult" class="col" style="margin-top:8px"></div>
    </div>
    <div class="row" style="margin-top:16px">
      <button class="btn primary" onclick="saveLdap()">Save</button>
    </div>
  </div>
  </div><!-- /tab-ldap -->

  <div class="tabpanel" id="tab-logging">
  <div class="card">
    <div class="banner info" style="display:flex; flex-wrap:wrap; align-items:center; gap:12px">
      <label class="row" style="font-size:13px; gap:6px">Max level logged
        <select id="logLevel"></select>
      </label>
      <label class="row" style="font-size:13px; gap:6px">New file after
        <input type="number" id="logMaxMb" min="1" max="1000" step="1" style="width:80px"> MB
      </label>
      <button class="btn small" onclick="saveLogConfig()">Save</button>
      <span class="subtle">Records this severity and everything above it in the ladder
        (INFO → USAGE → WARN → ERROR → DEBUG; DEBUG logs everything).</span>
    </div>

    <div class="row" style="flex-wrap:wrap; gap:8px; margin:12px 0 8px; align-items:center">
      <div class="seg" id="logSeverityFilter"></div>
      <input type="text" id="logIp" placeholder="Client IP" style="width:130px" oninput="scheduleLogReload()">
      <select id="logOp" onchange="logResetReload()"><option value="">All operations</option></select>
      <select id="logTag" onchange="logResetReload()"><option value="">All tags</option></select>
      <input type="text" id="logSearch" placeholder="Search message (regex / wildcards)…"
        style="flex:1; min-width:180px" oninput="scheduleLogReload()">
      <button class="btn small" onclick="loadLogs()">↻ Refresh</button>
      <button class="btn small" onclick="downloadLog()">⬇ Download</button>
      <button class="btn small danger" onclick="clearLogs()">Clear</button>
    </div>
    <div id="logTable"></div>
    <div id="logModal" class="log-ov" hidden onclick="if(event.target===this)closeLogModal()">
      <div class="log-ov-box">
        <div class="row" style="justify-content:space-between; align-items:center; margin-bottom:12px">
          <strong style="font-size:14px">Log entry</strong>
          <button class="btn small" onclick="closeLogModal()">Close</button>
        </div>
        <div id="logModalBody"></div>
      </div>
    </div>
    <div class="row" id="logPager"
      style="justify-content:space-between; align-items:center; gap:12px; margin-top:12px; font-size:13px">
      <label class="row subtle" style="gap:6px">Per page
        <select id="logPerPage" onchange="setLogPerPage()">
          <option value="10">10</option>
          <option value="25" selected>25</option>
          <option value="50">50</option>
          <option value="100">100</option>
        </select>
      </label>
      <span class="row" id="logPagerNav" style="gap:8px; align-items:center"></span>
    </div>
  </div>
  </div><!-- /tab-logging -->

  <div class="tabpanel" id="tab-backup">
  <div class="card">
    <h2>Backup</h2>
    <p class="muted" style="font-size:13px; margin:0 0 12px">A backup captures everything except the
      event data itself &mdash; connections, filter presets, happy paths, target norms, node layouts,
      LLM prompt templates and app preferences &mdash; as a single JSON file (byte-compatible with the
      app's backup format). Download one now, or have the server write encrypted backups automatically
      on a schedule. The options and password below apply to both.</p>
    <div class="col" style="gap:12px; max-width:560px">
      <div class="col" style="gap:6px">
        <label class="row" style="gap:8px; font-size:14px"><input type="checkbox" id="schedInclUser" checked style="width:auto"> Include database usernames</label>
        <label class="row" style="gap:8px; font-size:14px"><input type="checkbox" id="schedInclPw" checked style="width:auto" onchange="updateBackupWarn()"> Include database passwords</label>
        <label class="row" style="gap:8px; font-size:14px"><input type="checkbox" id="schedInclLlm" checked style="width:auto" onchange="updateBackupWarn()"> Include LLM API keys</label>
      </div>
      <div id="bkSecretWarn" class="banner warn" style="display:none">⚠ Secrets will be written in plain text unless you set an encryption password.</div>
      <div class="field"><label>Encryption password (AES-256-GCM)</label>
        <input type="password" id="schedPw" autocomplete="new-password" oninput="updateBackupWarn()" style="max-width:320px">
        <span class="subtle" id="schedPwHint" style="font-size:12px"></span></div>
      <div class="banner warn" style="font-size:13px">For automatic backups the password is stored <strong>encrypted</strong> on the server so they can run unattended. Keep it safe &mdash; a backup can only be restored with it.</div>

      <div class="row" style="gap:8px">
        <button class="btn primary" onclick="downloadBackup()">⬇ Download backup</button>
        <button class="btn" onclick="runBackupNow()">Run backup on server now</button>
      </div>

      <hr style="border:none; border-top:1px solid var(--border-soft); margin:6px 0">
      <div style="font-weight:600">Automatic backups</div>
      <p class="muted" style="font-size:13px; margin:0">Written on a schedule while the admin server is
        running, saved under <code>data/backups/</code>; older files are pruned beyond the retention count.</p>
      <label class="row" style="gap:8px; font-size:14px"><input type="checkbox" id="schedEnabled" style="width:auto"> Enable automatic backups</label>

      <div class="field"><label>Frequency</label>
        <select id="schedFreq" onchange="onSchedFreqChange()" style="max-width:220px">
          <option value="hourly">Every hour</option>
          <option value="daily">Every day</option>
          <option value="weekly">Every week</option>
          <option value="monthly">Every month</option>
          <option value="custom">Custom (cron)</option>
        </select></div>

      <div class="row" style="gap:12px; flex-wrap:wrap">
        <div class="field" id="schedHourWrap"><label>Hour</label>
          <select id="schedHour" onchange="updateCron()"></select></div>
        <div class="field" id="schedMinuteWrap"><label>Minute</label>
          <select id="schedMinute" onchange="updateCron()"></select></div>
        <div class="field" id="schedDowWrap" style="display:none"><label>Weekday</label>
          <select id="schedDow" onchange="updateCron()"></select></div>
        <div class="field" id="schedDomWrap" style="display:none"><label>Day of month</label>
          <select id="schedDom" onchange="updateCron()"></select></div>
      </div>

      <div class="field" id="schedCustomWrap" style="display:none"><label>Cron expression (minute hour day-of-month month weekday)</label>
        <input type="text" id="schedCron" oninput="onCustomCron()" placeholder="0 2 * * *" spellcheck="false" style="max-width:280px; font-family:monospace"></div>

      <div class="muted" style="font-size:13px">Runs: <code id="schedCronOut">0 2 * * *</code> &mdash; <span id="schedSummary"></span></div>

      <div class="field"><label>Keep newest backups</label>
        <input type="number" id="schedRetention" min="1" value="30" style="max-width:110px"></div>

      <div class="row" style="gap:8px">
        <button class="btn primary" onclick="saveSchedule()">Save schedule</button>
      </div>
      <div class="muted" id="schedStatus" style="font-size:13px"></div>
    </div>
  </div>
  <div class="card">
    <h2>Restore</h2>
    <p class="muted" style="font-size:13px; margin:0 0 12px">Load a backup file, review its contents,
      then choose what to restore. This overwrites the corresponding settings.</p>
    <div class="col" style="gap:10px; max-width:520px">
      <div class="field"><label>Backup file</label>
        <input type="file" id="bkFile" accept=".json,application/json" onchange="pickBackupFile()"></div>
      <div class="field"><label>Password (if the backup is encrypted)</label>
        <div class="row" style="gap:8px">
          <input type="password" id="bkRestorePw" autocomplete="off" style="max-width:280px">
          <button class="btn small" onclick="inspectBackup()">Inspect</button>
        </div></div>
      <div id="bkError" class="banner warn" style="display:none"></div>
      <div id="bkSummary" style="display:none">
        <hr style="border:none; border-top:1px solid var(--border-soft); margin:8px 0">
        <div style="font-weight:600; margin-bottom:6px">Backup contents</div>
        <div id="bkSummaryBody" class="col" style="gap:3px; font-size:13px; color:var(--muted)"></div>
        <div style="font-weight:600; margin:14px 0 6px">Restore</div>
        <div id="bkRestoreOpts" class="col" style="gap:6px"></div>
        <button class="btn primary danger" style="align-self:flex-start; margin-top:12px" onclick="restoreBackup()">Restore</button>
      </div>
    </div>
  </div>
  </div><!-- /tab-backup -->

  <div class="tabpanel" id="tab-customize">
  <div class="card">
    <h2>Customize</h2>
    <p class="muted" style="margin-top:0">Branding and appearance for the application and this admin interface. More options to come.</p>

    <h2 style="font-size:14px; margin-top:18px">Login Page</h2>
    <p class="subtle" style="margin-top:0">Background for both sign-in pages (the main app and this admin interface). The default keeps the built-in theme colour, which follows light / dark mode.</p>

    <div class="col" style="gap:10px; max-width:520px; margin-top:12px">
      <label class="row" style="font-size:14px; cursor:pointer"><input type="radio" name="loginBg" value="default" id="lbg_default" style="width:auto" onchange="onLoginBgType()"> Default theme colour</label>
      <label class="row" style="font-size:14px; cursor:pointer"><input type="radio" name="loginBg" value="color" id="lbg_color" style="width:auto" onchange="onLoginBgType()"> Solid colour</label>
      <div class="row" id="lbg_colorRow" style="gap:10px; align-items:center; padding-left:26px; display:none">
        <input type="color" id="lbg_colorPicker" value="#f2f2f7" style="width:48px; height:32px; padding:2px" onchange="syncLoginColor('picker')">
        <div class="field" style="margin:0"><input type="text" id="lbg_colorHex" placeholder="#f2f2f7" style="width:120px" oninput="syncLoginColor('hex')"></div>
      </div>
      <label class="row" style="font-size:14px; cursor:pointer"><input type="radio" name="loginBg" value="image" id="lbg_image" style="width:auto" onchange="onLoginBgType()"> Background image</label>
      <div class="col" id="lbg_imageRow" style="gap:8px; padding-left:26px; display:none">
        <!-- No accept filter: a stray MIME token (svg+xml/webp) makes Safari's
             picker disable the confirm button for every file. We validate + re-encode
             the chosen file ourselves, and the server whitelists the final format. -->
        <input type="file" id="lbg_imageFile" onchange="pickLoginImage()">
        <p class="subtle" style="margin:0">PNG, JPEG, GIF, WebP or SVG — or just <strong>drag an image onto the preview below</strong>. Large photos are automatically scaled down; the image is then stretched to cover the page.</p>
      </div>
    </div>

    <div style="margin-top:16px">
      <div class="subtle" style="margin-bottom:6px">Preview</div>
      <div id="lbg_preview" title="Drag an image here to use it as the background" ondragover="dragOverLoginImage(event)" ondragleave="dragLeaveLoginImage(event)" ondrop="dropLoginImage(event)" style="width:100%; max-width:520px; height:150px; border-radius:10px; border:1px solid var(--border-soft); background:var(--bg); display:grid; place-items:center">
        <div style="padding:10px 16px; border-radius:10px; background:rgba(255,255,255,.82); color:#000; font-size:13px; box-shadow:0 6px 20px rgba(0,0,0,.18)">Sign in</div>
      </div>
    </div>

    <div class="row" style="margin-top:16px; align-items:center; gap:12px">
      <button class="btn primary" onclick="saveLoginBg()">Save</button>
      <span id="lbg_result" class="subtle"></span>
    </div>
  </div>
  </div><!-- /tab-customize -->

  <div class="tabpanel" id="tab-reporting">
  <div class="card">
    <h2>AI Reporting</h2>
    <p class="muted" style="margin-top:0">The high-gloss AI report analyses the transition table with a language model, then assembles the findings — plus the Sankey, Happy Path and Conformance sections — into a styled, printable document.</p>

    <h2 style="font-size:14px; margin-top:18px">Default language model</h2>
    <p class="subtle" style="margin-top:0">The LLM used for AI features on every connection — <strong>unless a connection defines its own LLM, which overrides this default</strong> (set that under Connections). OpenAI-compatible endpoint (a <code>/v1</code>-style base URL). Leave the server URL blank to require each connection to bring its own.</p>
    <div class="col" style="gap:10px; max-width:560px; margin-top:10px">
      <div class="field"><label>Server URL</label><input type="text" id="rep_llmUrl" placeholder="https://api.openai.com/v1"></div>
      <div class="field"><label>Model</label><input type="text" id="rep_llmModel" placeholder="gpt-4o"></div>
      <div class="field"><label>API key</label><input type="password" id="rep_llmKey" placeholder="leave blank to keep the stored key" autocomplete="new-password"></div>
      <div class="row" style="gap:12px; align-items:center">
        <button class="btn" onclick="testReportLLM()">Test</button>
        <span id="rep_llmTest" class="subtle"></span>
      </div>
    </div>

    <div class="row" style="margin-top:16px; align-items:center; gap:12px">
      <button class="btn primary" onclick="saveReportLLM()">Save language model</button>
      <span id="rep_result" class="subtle"></span>
    </div>
  </div>

  <div class="card">
    <h2 style="font-size:14px">Style &amp; sections <span class="subtle" style="font-weight:400">— per project</span></h2>
    <p class="subtle" style="margin-top:0">The report look is configured <strong>per (connection, project)</strong>, so one environment can brand reports differently for each customer. Pick the connection, then the project; a project with no style of its own uses a plain default theme.</p>
    <div class="row" style="gap:10px; flex-wrap:wrap; align-items:flex-end; margin-top:10px">
      <div class="field" style="margin:0"><label>Connection</label><select id="rep_styleConn" style="min-width:220px" onchange="loadStyleProjects()"></select></div>
      <div class="field" style="margin:0"><label>Project</label><select id="rep_styleProject" style="min-width:240px" onchange="loadReportStyle()"></select></div>
      <span id="rep_styleProjStatus" class="subtle"></span>
    </div>
    <div class="col" style="gap:10px; max-width:560px; margin-top:12px">
      <div class="row" style="gap:10px; align-items:center">
        <label style="min-width:130px">Accent colour</label>
        <input type="color" id="rep_accentPicker" value="#4a3aa7" style="width:48px; height:32px; padding:2px" onchange="$('rep_accentHex').value=$('rep_accentPicker').value">
        <div class="field" style="margin:0"><input type="text" id="rep_accentHex" placeholder="#4a3aa7" style="width:120px" oninput="if(/^#[0-9a-fA-F]{6}$/.test(this.value))$('rep_accentPicker').value=this.value"></div>
      </div>
      <div class="field"><label>Organisation / letterhead (optional)</label><input type="text" id="rep_orgName" placeholder="e.g. ACME Airports" maxlength="120"></div>
      <div class="field">
        <label>Logo (PNG/JPG, optional) — shown on the first page</label>
        <div class="row" style="gap:10px; align-items:center">
          <input type="file" id="rep_logoFile" accept="image/png,image/jpeg,image/webp,image/svg+xml" onchange="pickReportLogo()">
          <button class="btn" type="button" id="rep_logoClear" onclick="clearReportLogo()" style="display:none">Remove</button>
        </div>
        <img id="rep_logoPreview" alt="" style="display:none; max-height:48px; max-width:190px; margin-top:8px; border:1px solid var(--border); border-radius:6px; padding:4px; background:#fff">
      </div>
      <div class="row" style="gap:10px; align-items:center">
        <label style="min-width:130px">Logo position</label>
        <select id="rep_logoPos" style="width:150px"><option value="left">Left</option><option value="right">Right</option></select>
      </div>
      <div class="row" style="gap:10px; align-items:center">
        <label style="min-width:130px">Logo size</label>
        <input type="range" id="rep_logoScale" min="0.5" max="2" step="0.1" value="1" style="width:200px" oninput="$('rep_logoScaleVal').textContent = (+this.value).toFixed(1) + '×'; updateLogoPreviewScale()">
        <span id="rep_logoScaleVal" class="subtle" style="min-width:36px">1.0×</span>
      </div>
      <div class="col" style="gap:6px; margin-top:4px">
        <label class="row" style="font-size:14px; cursor:pointer"><input type="checkbox" id="rep_incSankey" style="width:auto" checked> Include the process flow (Sankey) diagram</label>
        <label class="row" style="font-size:14px; cursor:pointer"><input type="checkbox" id="rep_incHappy" style="width:auto" checked> Include the Happy Path conformance section</label>
        <label class="row" style="font-size:14px; cursor:pointer"><input type="checkbox" id="rep_incConf" style="width:auto" checked> Include the Conformance gap analysis</label>
      </div>
    </div>
    <div class="row" style="margin-top:16px; align-items:center; gap:12px">
      <button class="btn primary" onclick="saveReportStyle()">Save style</button>
      <button class="btn danger" onclick="removeReportStyle()">Remove</button>
      <span id="rep_styleResult" class="subtle"></span>
    </div>
    <div id="rep_styleList" style="margin-top:16px"></div>
  </div>

  <div class="card">
    <h2 style="font-size:14px">Analysis prompts</h2>
    <p class="subtle" style="margin-top:0">The instruction the report LLM follows, <strong>linked to a connection and a project</strong> — so each process gets tailored analysis. When no prompt is defined for a project, the app's own prompt template is used. Pick the connection, then the project (its projects are loaded from its database).</p>
    <div class="row" style="gap:10px; flex-wrap:wrap; align-items:flex-end; margin-top:10px">
      <div class="field" style="margin:0"><label>Connection</label><select id="rep_promptConn" style="min-width:220px" onchange="loadReportProjects()"></select></div>
      <div class="field" style="margin:0"><label>Project</label><select id="rep_promptProject" style="min-width:240px"></select></div>
      <span id="rep_projStatus" class="subtle"></span>
    </div>
    <div class="field" style="max-width:760px; margin-top:8px"><label>Prompt</label><textarea id="rep_promptText" rows="4" placeholder="e.g. Identify outliers, bottlenecks and any anomalies in the routing percentages; call out timing data that looks synthetic."></textarea></div>
    <div class="row" style="gap:12px; align-items:center">
      <button class="btn primary" onclick="saveReportPrompt()">Save prompt</button>
      <span id="rep_promptResult" class="subtle"></span>
    </div>
    <div id="rep_promptList" style="margin-top:16px"></div>
  </div>
  </div><!-- /tab-reporting -->

  <div class="tabpanel" id="tab-integration">
  <div class="card">
    <h2>Integration console</h2>
    <p class="muted" style="margin-top:0">
      A separate surface for configuring data sources, reachable only by
      <strong>power users</strong>, <strong>developers</strong> and <strong>admins</strong>.
      Grant the Developer role per user in the <strong>Users</strong> tab.
    </p>
    <label class="row" style="font-size:14px; cursor:pointer; gap:8px; align-items:center">
      <input type="checkbox" id="int_enabled" style="width:auto" onchange="toggleIntegrationEnabled()">
      Enable the integration console
    </label>
    <div id="int_status" class="col" style="margin-top:12px; gap:6px"></div>
    <p class="subtle" style="margin-top:10px">
      The console follows the same TLS mode &amp; certificate as the app and this admin
      interface (change them in the <strong>TLS / SSL</strong> tab). Enabling/disabling and
      TLS changes take effect after <strong>↻ Restart app server</strong> in the
      <strong>App Control</strong> tab.
    </p>
  </div>
  </div><!-- /tab-integration -->

  <div class="tabpanel" id="tab-actions">
  <!-- TEMPORARY: "Experimental" hazard banner for the Actions feature. Remove this whole
       block (down to the matching end-comment) when Actions leaves experimental status. -->
  <div style="position:relative; margin:0 0 14px; border-radius:8px; overflow:hidden;
       background:repeating-linear-gradient(45deg, #111 0 22px, #f2c200 22px 44px);
       padding:16px 0; text-align:center;">
    <span style="display:inline-block; background:rgba(0,0,0,.82); color:#f2c200;
         font-weight:800; letter-spacing:3px; text-transform:uppercase; font-size:15px;
         padding:7px 24px; border-radius:6px; border:1px solid rgba(242,194,0,.65);">
      &#9888; Experimental
    </span>
  </div>
  <!-- END TEMPORARY experimental banner -->
  <div class="card">
    <h2>Actions</h2>
    <p class="muted" style="margin-top:0">
      Lets authors attach small, business-readable <strong>actions</strong> to process-map
      nodes (e.g. &ldquo;show the last log entries from this node&rdquo;). Actions are written on a
      separate <strong>Actions</strong> surface (reachable by <strong>developers</strong> and
      <strong>admins</strong>) and run from a node&rsquo;s menu in the app by every signed-in user
      except plain standard users.
    </p>
    <label class="row" style="font-size:14px; cursor:pointer; gap:8px; align-items:center">
      <input type="checkbox" id="act_enabled" style="width:auto" onchange="toggleActionsEnabled()">
      Enable Actions
    </label>
    <div id="act_status" class="col" style="margin-top:12px; gap:6px"></div>
    <p class="subtle" style="margin-top:10px">
      The Actions surface follows the same TLS mode &amp; certificate as the app and this admin
      interface (change them in the <strong>TLS / SSL</strong> tab). Enabling/disabling and
      TLS changes take effect after <strong>↻ Restart app server</strong> in the
      <strong>App Control</strong> tab.
    </p>
  </div>
  </div><!-- /tab-actions -->

  <div class="tabpanel" id="tab-sink">
  <div class="card">
    <h2>API Server - Event Receiver</h2>
    <p class="muted" style="margin-top:0">
      An HTTP/HTTPS API that AI agents <strong>POST journey entries</strong> to as JSON; each
      entry is written to the <strong>JOURNEYS</strong> table of the connection chosen when the
      sink is defined, and unknown steps are created automatically. Sinks are defined in the
      <strong>Integration console</strong> (kind <em>API Server - Event Receiver</em>) by developers
      and admins; each runs on its own port from a fixed pool.
    </p>
    <label class="row" style="font-size:14px; cursor:pointer; gap:8px; align-items:center">
      <input type="checkbox" id="sink_enabled" style="width:auto" onchange="toggleSinkEnabled()">
      Enable the API Server - Event Receiver module
    </label>
    <div id="sink_status" class="col" style="margin-top:12px; gap:6px"></div>
    <p class="subtle" style="margin-top:10px">
      Enabling/disabling takes effect <strong>immediately</strong> (no restart) — while off, the
      ports stay open but return 503. The sinks follow the same TLS mode &amp; certificate as the
      app and this admin interface; a TLS change takes effect after
      <strong>↻ Restart app server</strong> in the <strong>App Control</strong> tab.
    </p>
  </div>
  </div><!-- /tab-sink -->

  <div class="tabpanel" id="tab-mcp">
  <div class="card">
    <h2>MCP Server</h2>
    <p class="muted" style="margin-top:0">
      A read-only <strong>Model Context Protocol</strong> endpoint that lets AI clients
      (Claude, ChatGPT, …) query your process data — <em>metrics, paths and metadata</em> — over
      HTTP(S). Callers authenticate with an <strong>OAuth access token from your Authentik
      server</strong>; the token is verified against Authentik&rsquo;s signing keys and mapped to a
      Process Mining user, whose assigned database connections gate what they can see. See
      <code>MCP-SERVER.md</code> for the full Authentik + client setup.
    </p>
    <label class="row" style="font-size:14px; cursor:pointer; gap:8px; align-items:center">
      <input type="checkbox" id="mcp_enabled" style="width:auto" onchange="toggleMcpEnabled()">
      Enable the MCP server
    </label>
    <div id="mcp_status" class="col" style="margin-top:12px; gap:6px"></div>

    <h3 style="font-size:13px; margin:18px 0 6px">Authentik (OAuth) settings</h3>
    <div class="field">
      <label>Issuer URL</label>
      <input type="text" id="mcp_issuer" placeholder="https://authentik.example.com:19443/application/o/process-mining/">
    </div>
    <div class="field">
      <label>JWKS URL <span class="subtle">(leave blank to auto-discover from the issuer)</span></label>
      <input type="text" id="mcp_jwksUri" placeholder="https://…/application/o/process-mining/jwks/">
    </div>
    <div class="field">
      <label>Audience / Client ID <span class="subtle">(the token&rsquo;s <code>aud</code>; blank = skip the check)</span></label>
      <input type="text" id="mcp_audience" placeholder="the OAuth application's Client ID">
    </div>
    <div class="field">
      <label>Required group <span class="subtle">(optional — only members may connect)</span></label>
      <input type="text" id="mcp_requiredGroup" placeholder="e.g. process-mining-users">
    </div>
    <div class="field">
      <label>Username claim <span class="subtle">(the JWT claim matched to a Process Mining user)</span></label>
      <input type="text" id="mcp_usernameClaim" placeholder="preferred_username">
    </div>
    <div class="row" style="align-items:center; gap:10px; margin-top:8px">
      <button class="btn primary" onclick="saveMcpSettings()">Save settings</button>
      <button class="btn" onclick="testMcp()">Test Authentik</button>
      <span id="mcp_testResult" class="muted"></span>
    </div>
    <p class="subtle" style="margin-top:12px">
      Enabling/disabling takes effect <strong>immediately</strong> (no restart) — while off, the
      endpoint returns 503. The server follows the same TLS mode &amp; certificate as the app and
      this admin interface; a TLS change takes effect after <strong>↻ Restart app server</strong>
      in the <strong>App Control</strong> tab. The endpoint is <code>/mcp</code> on the MCP port
      (see the status line above).
    </p>
  </div>
  </div><!-- /tab-mcp -->
</div>
<div class="toast" id="toast"></div>
<script>
const HTTP_PORT = {http_port}, HTTPS_PORT = {https_port};
{_DASHBOARD_JS}
</script>
</body></html>"""


# JS is kept as a separate constant purely for readability of the template above.
_DASHBOARD_JS = r"""
const $ = (id) => document.getElementById(id);
let TLS = null;

// ── Appearance (System / Light / Dark), analog to the main app ────────────────
const THEME_KEY = 'pmw_admin_theme';
function readThemePref() { try { return localStorage.getItem(THEME_KEY) || 'system'; } catch (e) { return 'system'; } }
function applyTheme(pref) {
  const dark = pref === 'system'
    ? matchMedia('(prefers-color-scheme: dark)').matches
    : pref === 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}
function markThemeSel(pref) {
  const seg = $('themeSeg'); if (!seg) return;
  seg.querySelectorAll('button').forEach((b) =>
    b.classList.toggle('sel', b.getAttribute('data-theme-choice') === pref));
}
function setTheme(pref) {
  try { localStorage.setItem(THEME_KEY, pref); } catch (e) { /* private mode */ }
  applyTheme(pref); markThemeSel(pref);
}
function initTheme() {
  const pref = readThemePref();
  applyTheme(pref); markThemeSel(pref);
  try {
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (readThemePref() === 'system') applyTheme('system');
    });
  } catch (e) { /* Safari < 14 */ }
}
initTheme();

function toast(msg, isErr) {
  const t = $('toast'); t.textContent = msg; t.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(t._h); t._h = setTimeout(() => (t.className = 'toast'), 2600);
}
async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
  if (r.status === 401) { location.href = '/login'; throw new Error('unauthorized'); }
  const body = r.headers.get('content-type')?.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((body && body.detail) || ('HTTP ' + r.status));
  return body;
}
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let DISPLAY_TZ = ''; // '' = browser local; else an IANA zone from the admin setting
const fmtDate = (s) => {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d)) return '—';
  try { return d.toLocaleString(undefined, DISPLAY_TZ ? { timeZone: DISPLAY_TZ } : {}); }
  catch (e) { return d.toLocaleString(); }
};

function _populateTzSelect() {
  const sel = $('displayTz');
  if (!sel || sel.options.length) return;
  let zones = [];
  try { zones = Intl.supportedValuesOf('timeZone'); } catch (e) { zones = []; }
  const add = (v, label) => { const o = document.createElement('option'); o.value = v; o.textContent = label || v; sel.appendChild(o); };
  add('', 'Server local (default)');
  add('UTC', 'UTC');
  for (const z of zones) if (z !== 'UTC') add(z);
}

function previewTz() {
  const tz = $('displayTz').value;
  try {
    const now = new Date().toLocaleString(undefined, tz ? { timeZone: tz } : {});
    $('tzPreview').textContent = 'Current time: ' + now + (tz ? '' : ' (server / browser local)');
  } catch (e) { $('tzPreview').textContent = ''; }
}

async function saveDisplayTimezone() {
  try {
    await api('/api/access/timezone', { method: 'POST', body: JSON.stringify({ timezone: $('displayTz').value }) });
    toast('Timezone updated'); await loadSession();
  } catch (e) { toast(e.message, true); }
}

let BUILTIN_ADMIN = '';
async function loadSession() {
  const s = await api('/api/session');
  BUILTIN_ADMIN = s.builtinAdmin || '';
  $('who').textContent = s.username;
  $('defaultWarn').innerHTML = s.defaultPasswordActive
    ? '<div class="banner warn">⚠️ The <strong>Administrator</strong> account is still using its default password. Change it now in <strong>👤 Profile</strong> (top right).</div>'
    : '';
  $('requireLogin').checked = !!s.requireLogin;
  $('requireLoginHint').textContent = s.requireLogin
    ? 'Users must sign in.' : 'The app is open — no sign-in required.';
  const idle = s.idleTimeoutMins || 0;
  $('idleTimeout').value = idle;
  $('idleTimeoutHint').textContent = idle > 0
    ? 'Idle sessions are signed out after ' + idle + ' min.' : 'Disabled — sessions never time out on inactivity.';
  const adminIdle = s.adminIdleTimeoutMins || 0;
  $('adminIdleTimeout').value = adminIdle;
  $('adminIdleTimeoutHint').textContent = adminIdle > 0
    ? 'You are signed out of this admin after ' + adminIdle + ' min idle.'
    : 'Disabled — the admin session never times out on inactivity.';
  setAdminIdle(adminIdle);
  const maxFail = s.maxFailedLogins || 0;
  $('maxFailedLogins').value = maxFail;
  $('maxFailedLoginsHint').textContent = maxFail > 0
    ? 'Accounts (incl. the Administrator) are disabled after ' + maxFail + ' failed sign-ins.'
    : 'Disabled — accounts are never locked on failed sign-ins.';
  DISPLAY_TZ = s.displayTimezone || '';
  _populateTzSelect();
  $('displayTz').value = DISPLAY_TZ;
  previewTz();
  renderLicense(s.license);
}
function renderLicense(lic) {
  const el = $('licenseStatus');
  if (!el) return;
  lic = lic || { state: 'missing', message: 'No license installed.' };
  const cls = lic.state === 'valid' ? 'banner ok'
    : lic.state === 'expired' ? 'banner warn' : 'banner err';
  let html = '<strong>' + esc(lic.message || lic.state) + '</strong>';
  if (lic.licensee) {
    html += '<div class="subtle" style="margin-top:4px">Licensed to ' + esc(lic.licensee)
      + (lic.expires ? ' · expires ' + esc(lic.expires) : '')
      + (lic.issued ? ' · issued ' + esc(lic.issued) : '') + '</div>';
  }
  el.className = cls;
  el.innerHTML = html;
}
async function uploadLicense() {
  const f = $('licenseFile').files[0];
  if (!f) { toast('Choose a license file first', true); return; }
  const out = $('licenseResult');
  try {
    const content = await _fileToBase64(f);
    const r = await api('/api/license', { method: 'POST', body: JSON.stringify({ content }) });
    renderLicense(r.license);
    if (out) out.innerHTML = '<div class="banner ok">License installed. The backend applies it within a few seconds.</div>';
    $('licenseFile').value = '';
    toast('License installed');
  } catch (e) {
    if (out) out.innerHTML = '<div class="banner err">' + esc(e.message) + '</div>';
    toast(e.message, true);
  }
}
async function deleteLicense() {
  if (!confirm('Delete the installed license?\n\nThe compute backend drops to Demo Mode and stops after the grace period unless a new license is applied.')) return;
  const out = $('licenseResult');
  try {
    const r = await api('/api/license', { method: 'DELETE' });
    renderLicense(r.license);
    if (out) out.innerHTML = r.removed
      ? '<div class="banner warn">License removed — the backend is now in Demo Mode.</div>'
      : '<div class="banner info">No license was installed.</div>';
    toast(r.removed ? 'License deleted' : 'No license installed');
  } catch (e) {
    if (out) out.innerHTML = '<div class="banner err">' + esc(e.message) + '</div>';
    toast(e.message, true);
  }
}
async function saveMaxFailedLogins() {
  const count = Math.max(0, parseInt($('maxFailedLogins').value, 10) || 0);
  try { await api('/api/access/max-failed-logins', { method: 'POST', body: JSON.stringify({ count }) });
    toast('Failed-sign-in lockout updated'); await loadSession(); }
  catch (e) { toast(e.message, true); }
}
async function saveRequireLogin() {
  const requireLogin = $('requireLogin').checked;
  try { await api('/api/access/require-login', { method: 'POST', body: JSON.stringify({ requireLogin }) });
    toast('Access updated'); await loadSession(); }
  catch (e) { toast(e.message, true); $('requireLogin').checked = !requireLogin; }
}
async function saveIdleTimeout() {
  const minutes = Math.max(0, parseInt($('idleTimeout').value, 10) || 0);
  try { await api('/api/access/idle-timeout', { method: 'POST', body: JSON.stringify({ minutes }) });
    toast('Auto sign-out updated'); await loadSession(); }
  catch (e) { toast(e.message, true); }
}
async function saveAdminIdleTimeout() {
  const minutes = Math.max(0, parseInt($('adminIdleTimeout').value, 10) || 0);
  try { await api('/api/access/admin-idle-timeout', { method: 'POST', body: JSON.stringify({ minutes }) });
    toast('Admin auto sign-out updated'); await loadSession(); }
  catch (e) { toast(e.message, true); }
}

// ── Admin idle auto-logout ────────────────────────────────────────────────
// Mirrors the app's IdleLogout: after N minutes without activity, sign out of
// the admin. Activity slides the server window (a throttled /api/session poll).
let ADMIN_IDLE_MINS = 0, _idleTimer = null, _lastPing = 0, _idleWired = false;
function _resetIdle() {
  clearTimeout(_idleTimer);
  if (!ADMIN_IDLE_MINS) return;
  _idleTimer = setTimeout(_onIdleTimeout, ADMIN_IDLE_MINS * 60000);
  const now = Date.now();
  if (now - _lastPing > 30000) { _lastPing = now; fetch('/api/session').catch(() => {}); }
}
async function _onIdleTimeout() {
  try { await fetch('/logout', { method: 'POST' }); } catch (e) { /* cookie expires anyway */ }
  location.href = '/login?inactivity=1';
}
function setAdminIdle(mins) {
  ADMIN_IDLE_MINS = mins || 0;
  if (!_idleWired) {
    _idleWired = true;
    ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click'].forEach(ev =>
      document.addEventListener(ev, _resetIdle, { passive: true }));
  }
  _resetIdle();
}

// ── TLS ─────────────────────────────────────────────────────────────────────
async function loadTls() {
  TLS = await api('/api/tls');
  document.querySelectorAll('#tlsSeg button').forEach(b =>
    b.classList.toggle('sel', b.dataset.mode === TLS.mode));
  const host = location.hostname;
  const plan = TLS.plan;
  let rows = '';
  rows += `<div class="row"><span class="muted" style="width:150px">HTTP endpoint</span>` +
    (plan.http ? `<a class="mono" href="http://${host}:${HTTP_PORT}/">http://${host}:${HTTP_PORT}/</a>` : `<span class="subtle">disabled</span>`) + `</div>`;
  rows += `<div class="row"><span class="muted" style="width:150px">HTTPS endpoint</span>` +
    (plan.https ? `<a class="mono" href="https://${host}:${HTTPS_PORT}/">https://${host}:${HTTPS_PORT}/</a>` : `<span class="subtle">disabled</span>`) + `</div>`;
  if ((TLS.mode !== 'off') && !plan.hasActiveCert)
    rows += `<div class="banner warn" style="margin:8px 0 0">No active certificate — HTTPS cannot start. Generate or upload one and activate it below.</div>`;
  $('tlsPlan').innerHTML = rows;
  renderCerts();
}
async function saveTlsMode() {
  const sel = document.querySelector('#tlsSeg button.sel');
  if (!sel) return;
  try { await api('/api/tls/mode', { method: 'POST', body: JSON.stringify({ mode: sel.dataset.mode }) });
    toast('TLS mode saved — restart in App Control to apply'); await loadTls(); }
  catch (e) { toast(e.message, true); }
}
document.querySelectorAll('#tlsSeg button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#tlsSeg button').forEach(x => x.classList.remove('sel'));
  b.classList.add('sel');
});
async function restartServer() {
  if (!confirm('Restart now?\n\nThe app AND this admin interface rebind their HTTP/HTTPS listeners with the current TLS settings. Anyone using the app will briefly disconnect, and if you changed the TLS mode this admin page may move between :8090 (HTTP) and :8453 (HTTPS).')) return;
  const out = $('restartResult');
  if (out) out.innerHTML = '<span class="muted">Restarting…</span>';
  try { const r = await api('/api/restart', { method: 'POST' });
    toast('Restarting (app pid ' + r.pid + (r.adminPid ? ', admin pid ' + r.adminPid : '') + ')…');
    if (out) out.innerHTML = '<div class="banner info">Restart signalled. Listeners rebind with the current TLS plan; reconnect on the new address if this page stops responding.</div>';
    // Give it a moment to rebind, then refresh the endpoint view.
    setTimeout(() => loadTls().catch(() => {}), 1500);
  } catch (e) { if (out) out.innerHTML = ''; toast(e.message, true); }
}

// ── Certificates ────────────────────────────────────────────────────────────
function renderCerts() {
  const certs = TLS.certs || [];
  if (!certs.length) { $('certTable').innerHTML = '<p class="subtle">No certificates yet. Generate or upload one below.</p>'; return; }
  let h = '<table><thead><tr><th>Name</th><th>Subject</th><th>Type</th><th>Expires</th><th></th></tr></thead><tbody>';
  for (const c of certs) {
    const active = c.id === TLS.activeCertId;
    h += `<tr><td><strong>${esc(c.name)}</strong> ${active ? '<span class="pill active">active</span>' : ''}</td>` +
      `<td class="mono">${esc(c.subject)}</td>` +
      `<td>${c.isSelfSigned ? 'Self-signed' : 'CA-signed'}</td>` +
      `<td>${fmtDate(c.notAfter)}</td>` +
      `<td style="text-align:right; white-space:nowrap">` +
        (active ? '' : `<button class="btn small" data-id="${esc(c.id)}" onclick="activateCert(this.dataset.id)">Activate</button> `) +
        `<a class="btn small" href="/api/certs/${encodeURIComponent(c.id)}/download">Download</a> ` +
        `<button class="btn small danger" data-id="${esc(c.id)}" data-name="${esc(c.name)}" onclick="deleteCert(this.dataset.id, this.dataset.name)">Delete</button>` +
      `</td></tr>`;
  }
  $('certTable').innerHTML = h + '</tbody></table>';
}
async function generateCert() {
  const body = { name: $('g_name').value, commonName: $('g_cn').value,
    sans: $('g_sans').value.split(',').map(s => s.trim()).filter(Boolean),
    days: Number($('g_days').value), keySize: Number($('g_keysize').value), activate: $('g_activate').checked };
  try { await api('/api/certs/generate', { method: 'POST', body: JSON.stringify(body) });
    toast('Certificate generated'); $('g_name').value = $('g_cn').value = $('g_sans').value = '';
    await loadTls(); }
  catch (e) { toast(e.message, true); }
}
async function uploadCert() {
  const body = { name: $('u_name').value, certPem: $('u_cert').value, keyPem: $('u_key').value, activate: $('u_activate').checked };
  try { await api('/api/certs/upload', { method: 'POST', body: JSON.stringify(body) });
    toast('Certificate uploaded'); $('u_name').value = $('u_cert').value = $('u_key').value = '';
    await loadTls(); }
  catch (e) { toast(e.message, true); }
}
async function activateCert(id) {
  try { await api('/api/certs/' + id + '/activate', { method: 'POST' });
    toast('Certificate activated'); await loadTls(); }
  catch (e) { toast(e.message, true); }
}
async function deleteCert(id, name) {
  if (!confirm('Delete certificate "' + name + '"?')) return;
  try { await api('/api/certs/' + id, { method: 'DELETE' }); toast('Certificate deleted'); await loadTls(); }
  catch (e) { toast(e.message, true); }
}

// ── Users ───────────────────────────────────────────────────────────────────
let USERS = [];
let USER_FILTER = 'all';  // 'all' | 'local' | 'ldap'

async function loadUsers() {
  USERS = await api('/api/users');
  renderUsers();
}
// The role cell. Every role the account holds is shown as one segment of a single
// badge: the base level (admin, else power, else user) followed by any add-on roles
// (a power admin shows admin·power; a developer adds ·dev). Two or more segments
// share one combo pill whose colour floats across all of them; a lone base role is a
// plain single pill.
function roleTitle(u) {
  const r = [];
  if (u.isAdmin) r.push('administrator');
  if (u.isPower) r.push('power user (manages own connections)');
  if (u.isDeveloper) r.push('developer (integration console)');
  return r.length ? 'Roles: ' + r.join(', ') : 'Regular user';
}
function roleBadge(u) {
  const BLUE = 'var(--accent)', TEAL = '#30d1c4', ORANGE = 'var(--orange)', GREY = '#8e8e93';
  const parts = [];
  // Base level: admins always carry a second base role (power or plain user).
  if (u.isAdmin) { parts.push({ t: 'admin', c: BLUE }); parts.push(u.isPower ? { t: 'power', c: TEAL } : { t: 'user', c: GREY }); }
  else if (u.isPower) parts.push({ t: 'power', c: TEAL });
  else parts.push({ t: 'user', c: GREY });
  if (u.isDeveloper) parts.push({ t: 'dev', c: ORANGE });  // add-on role
  const title = roleTitle(u);
  if (parts.length === 1)
    return `<span class="pill ${parts[0].t === 'power' ? 'power' : 'neutral'}" title="${title}">${parts[0].t}</span>`;
  // Floating gradient across each role colour (and back to the first).
  const grad = 'linear-gradient(90deg, ' + parts.map(p => p.c).join(', ') + ', ' + parts[0].c + ')';
  const inner = parts.map(p => p.t).join('<span class="sep">·</span>');
  return `<span class="pill combo" style="background-image:${grad}" title="${title}">${inner}</span>`;
}
function setUserFilter(f) { USER_FILTER = f; renderUsers(); }
function renderUsers() {
  const counts = { all: USERS.length, local: 0, ldap: 0 };
  for (const u of USERS) counts[u.authSource === 'ldap' ? 'ldap' : 'local']++;
  const chips = [
    { key: 'all', label: 'All' },
    { key: 'local', label: 'Local' },
    { key: 'ldap', label: 'LDAP' },
  ];
  $('userFilter').innerHTML = chips.map(c =>
    `<button class="${USER_FILTER === c.key ? 'sel' : ''}" onclick="setUserFilter('${c.key}')">` +
    `${c.label} <span class="subtle" style="font-size:11px">${counts[c.key]}</span></button>`
  ).join('');

  const q = ($('userSearch') ? $('userSearch').value : '').trim().toLowerCase();
  const rows = USERS.filter(u =>
    (USER_FILTER === 'all' || (u.authSource === 'ldap' ? 'ldap' : 'local') === USER_FILTER) &&
    (!q || u.username.toLowerCase().includes(q) ||
      (u.displayName || '').toLowerCase().includes(q)));
  // The master "all users" checkboxes reflect whether every user is allowed.
  $('passkeyAll').checked = USERS.length > 0 && USERS.every(u => u.passkeyAllowed);
  $('mfaAll').checked = USERS.length > 0 && USERS.every(u => u.mfaAllowed);
  if (rows.length === 0) {
    $('userTable').innerHTML = '<div class="user-empty">No matching users.</div>';
    return;
  }
  let h = '<div class="user-list">';
  for (const u of rows) {
    const isLdap = u.authSource === 'ldap';
    // The built-in Administrator cannot be disabled or demoted (enforced server-side too).
    const isBuiltin = !!BUILTIN_ADMIN && u.username.toLowerCase() === BUILTIN_ADMIN.toLowerCase();
    const du = esc(u.username);
    const access = u.isEnabled
      ? '<span class="pill on">enabled</span>'
      : (u.loginLocked
          ? '<span class="pill off" title="Disabled after too many failed sign-ins — Unlock to restore.">locked</span>'
          : '<span class="pill off">disabled</span>');
    // Line 1 — identity, source, role, access, and the per-user permission toggles.
    h += '<div class="user-card"><div class="row1">' +
      `<div class="u-ident"><strong>${du}</strong>` +
        (u.displayName ? `<span class="u-real">${esc(u.displayName)}</span>` : '') + '</div>' +
      (isLdap ? '<span class="pill ldap">LDAP</span>' : '<span class="pill neutral">local</span>') +
      roleBadge(u) + access +
      '<span class="spacer" style="flex:1"></span>' +
      `<label class="perm" title="Allow this user to enrol and sign in with a passkey">` +
        `<input type="checkbox" data-user="${du}" ${u.passkeyAllowed ? 'checked' : ''} onchange="togglePasskey(this.dataset.user, this.checked)"> Passkey</label>` +
      `<label class="perm" title="Allow this user to set up two-factor (TOTP)">` +
        `<input type="checkbox" data-user="${du}" ${u.mfaAllowed ? 'checked' : ''} onchange="toggleMfa(this.dataset.user, this.checked)"> 2FA</label>` +
      '</div>';
    // Line 2 — last sign-in and the action buttons.
    h += '<div class="row2"><span class="muted" style="font-size:12px">Last sign-in: ' +
      fmtDate(u.lastLogin) + '</span><span class="spacer" style="flex:1"></span>' +
      (isBuiltin
        ? (u.loginLocked
            ? `<button class="btn small" data-user="${du}" onclick="toggleEnabled(this.dataset.user,true)">Unlock</button> `
            : '')
        : `<button class="btn small" data-user="${du}" onclick="toggleEnabled(this.dataset.user,${!u.isEnabled})">${u.isEnabled ? 'Disable' : (u.loginLocked ? 'Unlock' : 'Enable')}</button> `) +
      (isBuiltin ? '' : `<button class="btn small" data-user="${du}" onclick="toggleAdmin(this.dataset.user,${!u.isAdmin})">${u.isAdmin ? 'Remove admin' : 'Make admin'}</button> `) +
      (isBuiltin ? '' : `<button class="btn small" data-user="${du}" onclick="togglePower(this.dataset.user,${!u.isPower})">${u.isPower ? 'Remove power' : 'Make power'}</button> `) +
      (isBuiltin ? '' : `<button class="btn small" data-user="${du}" onclick="toggleDeveloper(this.dataset.user,${!u.isDeveloper})">${u.isDeveloper ? 'Remove developer' : 'Make developer'}</button> `) +
      (isLdap ? '' : `<button class="btn small" data-user="${du}" onclick="resetPw(this.dataset.user)">Reset password</button> `) +
      (isBuiltin ? '<span class="subtle" title="The built-in administrator cannot be disabled, demoted or deleted.">built-in admin</span>' : `<button class="btn small danger" data-user="${du}" onclick="delUser(this.dataset.user)">Delete</button>`) +
      '</div></div>';
  }
  $('userTable').innerHTML = h + '</div>';
}
async function createUser() {
  const body = { username: $('nu_name').value.trim(), password: $('nu_pw').value, isAdmin: $('nu_admin').checked };
  try { await api('/api/users', { method: 'POST', body: JSON.stringify(body) });
    toast('User created'); $('nu_name').value = $('nu_pw').value = ''; $('nu_admin').checked = false; await loadUsers(); }
  catch (e) { toast(e.message, true); }
}
async function toggleEnabled(u, enabled) {
  try { await api('/api/users/' + encodeURIComponent(u) + '/enabled', { method: 'POST', body: JSON.stringify({ enabled }) });
    toast('Updated'); await loadUsers(); } catch (e) { toast(e.message, true); }
}
async function toggleAdmin(u, isAdmin) {
  try { await api('/api/users/' + encodeURIComponent(u) + '/admin', { method: 'POST', body: JSON.stringify({ isAdmin }) });
    toast('Updated'); await loadUsers(); } catch (e) { toast(e.message, true); }
}
async function togglePower(u, isPower) {
  try { await api('/api/users/' + encodeURIComponent(u) + '/power', { method: 'POST', body: JSON.stringify({ isPower }) });
    toast('Updated'); await loadUsers(); } catch (e) { toast(e.message, true); }
}
async function togglePasskey(u, allowed) {
  try { await api('/api/users/' + encodeURIComponent(u) + '/passkey-allowed', { method: 'POST', body: JSON.stringify({ allowed }) });
    toast('Updated'); await loadUsers(); } catch (e) { toast(e.message, true); await loadUsers(); }
}
async function toggleDeveloper(u, isDeveloper) {
  try { await api('/api/users/' + encodeURIComponent(u) + '/developer', { method: 'POST', body: JSON.stringify({ isDeveloper }) });
    toast('Updated'); await loadUsers(); } catch (e) { toast(e.message, true); await loadUsers(); }
}
async function togglePasskeyAll() {
  const allowed = $('passkeyAll').checked;
  try { await api('/api/access/passkey-all', { method: 'POST', body: JSON.stringify({ allowed }) });
    toast(allowed ? 'Passkeys allowed for all users' : 'Passkeys disabled for all users'); await loadUsers(); }
  catch (e) { toast(e.message, true); $('passkeyAll').checked = !allowed; }
}
async function toggleMfa(u, allowed) {
  try { await api('/api/users/' + encodeURIComponent(u) + '/mfa-allowed', { method: 'POST', body: JSON.stringify({ allowed }) });
    toast('Updated'); await loadUsers(); } catch (e) { toast(e.message, true); await loadUsers(); }
}
async function toggleMfaAll() {
  const allowed = $('mfaAll').checked;
  try { await api('/api/access/mfa-all', { method: 'POST', body: JSON.stringify({ allowed }) });
    toast(allowed ? 'Two-factor allowed for all users' : 'Two-factor disabled for all users'); await loadUsers(); }
  catch (e) { toast(e.message, true); $('mfaAll').checked = !allowed; }
}
async function resetPw(u) {
  const pw = prompt('New password for ' + u + ':'); if (!pw) return;
  try { await api('/api/users/' + encodeURIComponent(u) + '/password', { method: 'POST', body: JSON.stringify({ password: pw }) });
    toast('Password reset'); await loadSession(); } catch (e) { toast(e.message, true); }
}
async function delUser(u) {
  if (!confirm('Delete user "' + u + '"?')) return;
  try { await api('/api/users/' + encodeURIComponent(u), { method: 'DELETE' }); toast('User deleted'); await loadUsers(); }
  catch (e) { toast(e.message, true); }
}
async function changeOwnPassword() {
  const p1 = $('ownPw1').value, p2 = $('ownPw2').value, out = $('ownPwResult');
  out.textContent = '';
  if (!p1) { out.style.color = 'var(--red)'; out.textContent = 'Enter a new password.'; return; }
  if (p1 !== p2) { out.style.color = 'var(--red)'; out.textContent = 'The passwords don’t match.'; return; }
  try {
    await api('/api/self/password', { method: 'POST', body: JSON.stringify({ password: p1 }) });
    $('ownPw1').value = $('ownPw2').value = '';
    toast('Password changed'); await loadSession();
  } catch (e) { out.style.color = 'var(--red)'; out.textContent = e.message; }
}
// Profile overlay — the admin's own account (password / passkeys / two-factor).
function openProfile() {
  $('profOv').hidden = false;
  loadAdminPasskeys().catch(() => {});
  loadAdminMfa().catch(() => {});
  const el = $('ownPw1'); if (el) el.focus();
}
function closeProfile() { $('profOv').hidden = true; }

// ── Tabs ──────────────────────────────────────────────────────────────────
function selectTab(name) {
  for (const b of document.querySelectorAll('.tabs button'))
    b.classList.toggle('sel', b.dataset.tab === name);
  for (const p of document.querySelectorAll('.tabpanel'))
    p.classList.toggle('sel', p.id === 'tab-' + name);
  if (name === 'connections') loadConnections().catch(e => toast(e.message, true));
  if (name === 'ldap') loadLdap().catch(e => toast(e.message, true));
  if (name === 'logging') loadLogs().catch(e => toast(e.message, true));
  if (name === 'customize') loadCustomize().catch(e => toast(e.message, true));
  if (name === 'reporting') loadReporting().catch(e => toast(e.message, true));
  if (name === 'backup') loadSchedule().catch(e => toast(e.message, true));
  if (name === 'integration') loadIntegration().catch(e => toast(e.message, true));
  if (name === 'actions') loadActions().catch(e => toast(e.message, true));
  if (name === 'sink') loadSink().catch(e => toast(e.message, true));
  if (name === 'mcp') loadMcp().catch(e => toast(e.message, true));
}

// ── AI Reporting ─────────────────────────────────────────────────────────────
let _reportPrompts = [];  // last-loaded prompt rows; Edit/Remove dispatch by index
let _reportLogo = null;  // report logo staged for save: null = keep stored, '' = clear, data URI = new

function showReportLogo(uri) {
  const p = $('rep_logoPreview');
  if (uri) { p.src = uri; p.style.display = 'block'; $('rep_logoClear').style.display = ''; updateLogoPreviewScale(); }
  else { p.removeAttribute('src'); p.style.display = 'none'; $('rep_logoClear').style.display = 'none'; }
}
function clearReportLogo() { _reportLogo = ''; $('rep_logoFile').value = ''; showReportLogo(''); }
function pickReportLogo() {
  const f = $('rep_logoFile').files[0];
  if (!f) return;
  if (f.size > 30 * 1024 * 1024) { toast('Logo file is too large (max 30 MB)', true); $('rep_logoFile').value = ''; return; }
  const setLogo = (uri) => { _reportLogo = uri; showReportLogo(uri); toast('Logo ready — click Save settings to store it'); };
  // SVG stays vector; raster formats are drawn to a canvas and re-encoded small.
  if (f.type === 'image/svg+xml' || /\.svg$/i.test(f.name || '')) {
    const r = new FileReader();
    r.onload = () => setLogo(r.result);
    r.onerror = () => toast('Could not read the logo', true);
    r.readAsDataURL(f);
    return;
  }
  const url = URL.createObjectURL(f);
  const img = new Image();
  img.onload = () => {
    URL.revokeObjectURL(url);
    const MAX = 600;  // a logo prints crisply at a 600px long edge and stays tiny
    const scale = Math.min(1, MAX / Math.max(img.width, img.height));
    const w = Math.max(1, Math.round(img.width * scale));
    const h = Math.max(1, Math.round(img.height * scale));
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    c.getContext('2d').drawImage(img, 0, 0, w, h);
    let uri = c.toDataURL('image/png');  // PNG keeps transparency + crisp edges
    if (uri.length > 3000000) uri = c.toDataURL('image/jpeg', 0.85);  // last resort
    setLogo(uri);
  };
  img.onerror = () => { URL.revokeObjectURL(url); toast('Could not read the logo', true); };
  img.src = url;
}
async function loadReporting() {
  const [cfg, prompts, styles, conns] = await Promise.all([
    api('/api/reporting/config'),
    api('/api/reporting/prompts'),
    api('/api/reporting/styles'),
    api('/api/connections'),
  ]);
  $('rep_llmUrl').value = cfg.llmUrl || '';
  $('rep_llmModel').value = cfg.llmModel || '';
  $('rep_llmKey').value = '';
  $('rep_llmKey').placeholder = cfg.hasLlmKey ? '•••••• (stored — leave blank to keep)' : 'API key';

  const connOpts = conns.map(c => '<option value="' + esc(c.id) + '">' + esc(c.name || c.id) + '</option>').join('');
  $('rep_promptConn').innerHTML = connOpts;
  $('rep_styleConn').innerHTML = connOpts;
  await Promise.all([loadReportProjects(), loadStyleProjects()]);
  renderReportPrompts(prompts, conns);
  renderReportStyles(styles, conns);
}

// Load the selected connection's projects into the project dropdown: the option text is
// the project title (for the human), the option value is the project id (for linkage).
async function loadReportProjects() {
  const conn = $('rep_promptConn').value;
  const sel = $('rep_promptProject');
  if (!conn) { sel.innerHTML = ''; $('rep_projStatus').textContent = ''; return; }
  sel.innerHTML = '<option value="">Loading…</option>';
  $('rep_projStatus').textContent = '';
  try {
    const r = await api('/api/reporting/projects/' + encodeURIComponent(conn));
    if (r.error) { sel.innerHTML = '<option value="">—</option>'; $('rep_projStatus').textContent = '⚠ ' + r.error; return; }
    if (!r.projects.length) { sel.innerHTML = '<option value="">— no projects —</option>'; return; }
    sel.innerHTML = r.projects
      .map(p => '<option value="' + esc(p.projectId) + '">' + esc(p.title) + ' (' + esc(p.projectId) + ')</option>')
      .join('');
  } catch (e) {
    sel.innerHTML = '<option value="">—</option>';
    $('rep_projStatus').textContent = '⚠ ' + e.message;
  }
}

function renderReportPrompts(prompts, conns) {
  _reportPrompts = prompts;  // dispatch Edit/Remove by index — never inject values into HTML
  const nameOf = {};
  for (const c of conns) nameOf[c.id] = c.name || c.id;
  if (!prompts.length) {
    $('rep_promptList').innerHTML = '<p class="subtle">No analysis prompts yet — the app prompt template is used for every project.</p>';
    return;
  }
  let html = '<table class="tbl"><thead><tr><th>Connection</th><th>Project</th><th>Prompt</th><th></th></tr></thead><tbody>';
  prompts.forEach((p, i) => {
    html += '<tr><td>' + esc(nameOf[p.connectionId] || p.connectionId) + '</td><td><code>' + esc(p.projectId) + '</code></td>'
      + '<td class="subtle" style="max-width:420px">' + esc((p.prompt || '').slice(0, 160)) + ((p.prompt || '').length > 160 ? '…' : '') + '</td>'
      + '<td style="text-align:right; white-space:nowrap">'
      + '<button class="btn small" onclick="editReportPrompt(' + i + ')">Edit</button> '
      + '<button class="btn small danger" onclick="deleteReportPrompt(' + i + ')">Remove</button>'
      + '</td></tr>';
  });
  $('rep_promptList').innerHTML = html + '</tbody></table>';
}

async function editReportPrompt(i) {
  const p = _reportPrompts[i];
  if (!p) return;
  $('rep_promptConn').value = p.connectionId;
  await loadReportProjects();
  const sel = $('rep_promptProject');
  // Preserve the linked project even if it isn't in the fetched list (DB down / renamed).
  if (![...sel.options].some(o => o.value === p.projectId)) {
    sel.insertAdjacentHTML('afterbegin', '<option value="' + esc(p.projectId) + '">' + esc(p.projectId) + '</option>');
  }
  sel.value = p.projectId;
  $('rep_promptText').value = p.prompt || '';
  $('rep_promptText').focus();
}

async function saveReportLLM() {
  const body = { llmUrl: $('rep_llmUrl').value.trim(), llmModel: $('rep_llmModel').value.trim() };
  const key = $('rep_llmKey').value;
  if (key.trim() !== '') body.llmKey = key;  // omit → keep the stored key
  $('rep_result').textContent = '';
  try {
    await api('/api/reporting/config', { method: 'POST', body: JSON.stringify(body) });
    $('rep_llmKey').value = '';
    $('rep_result').textContent = 'Saved.';
    toast('Report language model saved');
    loadReporting().catch(() => {});
  } catch (e) { toast(e.message, true); }
}

// ── per-project Style & Sections ────────────────────────────────────────────
let _reportStyles = [];  // last-loaded style rows (logo omitted); Edit/Remove dispatch by index

function fillStyleFields(s) {
  s = s || {};
  const accent = /^#[0-9a-fA-F]{6}$/.test(s.accent || '') ? s.accent : '#4a3aa7';
  $('rep_accentHex').value = accent;
  $('rep_accentPicker').value = accent;
  $('rep_orgName').value = s.orgName || '';
  _reportLogo = null;  // null → keep the project's stored logo unless picked/removed
  $('rep_logoFile').value = '';
  const scale = Math.min(2, Math.max(0.5, parseFloat(s.logoScale) || 1));
  $('rep_logoScale').value = scale;
  $('rep_logoScaleVal').textContent = scale.toFixed(1) + '×';
  showReportLogo(s.logo || '');  // applies the scale via updateLogoPreviewScale
  $('rep_logoPos').value = s.logoPos === 'right' ? 'right' : 'left';
  $('rep_incSankey').checked = s.includeSankey !== false;
  $('rep_incHappy').checked = s.includeHappyPath !== false;
  $('rep_incConf').checked = s.includeConformance !== false;
}

// Scale the logo preview to match the slider, about the 48×190px base box (aspect kept).
function updateLogoPreviewScale() {
  const scale = Math.min(2, Math.max(0.5, parseFloat($('rep_logoScale').value) || 1));
  const p = $('rep_logoPreview');
  p.style.maxHeight = (48 * scale) + 'px';
  p.style.maxWidth = (190 * scale) + 'px';
}

// Load the selected connection's projects into the style project dropdown, then load the
// style for the first project (option text = title, value = project id).
async function loadStyleProjects() {
  const conn = $('rep_styleConn').value;
  const sel = $('rep_styleProject');
  if (!conn) { sel.innerHTML = ''; $('rep_styleProjStatus').textContent = ''; fillStyleFields(null); return; }
  sel.innerHTML = '<option value="">Loading…</option>';
  $('rep_styleProjStatus').textContent = '';
  try {
    const r = await api('/api/reporting/projects/' + encodeURIComponent(conn));
    if (r.error) { sel.innerHTML = '<option value="">—</option>'; $('rep_styleProjStatus').textContent = '⚠ ' + r.error; fillStyleFields(null); return; }
    if (!r.projects.length) { sel.innerHTML = '<option value="">— no projects —</option>'; fillStyleFields(null); return; }
    sel.innerHTML = r.projects
      .map(p => '<option value="' + esc(p.projectId) + '">' + esc(p.title) + ' (' + esc(p.projectId) + ')</option>')
      .join('');
  } catch (e) {
    sel.innerHTML = '<option value="">—</option>';
    $('rep_styleProjStatus').textContent = '⚠ ' + e.message;
    fillStyleFields(null);
    return;
  }
  await loadReportStyle();
}

async function loadReportStyle() {
  const conn = $('rep_styleConn').value, proj = $('rep_styleProject').value;
  if (!conn || !proj) { fillStyleFields(null); return; }
  try {
    const s = await api('/api/reporting/style?connectionId=' + encodeURIComponent(conn) + '&projectId=' + encodeURIComponent(proj));
    fillStyleFields(s);  // null when the project has no style yet → default fields
    $('rep_styleProjStatus').textContent = s ? '' : 'No style yet — showing defaults.';
  } catch (e) { fillStyleFields(null); toast(e.message, true); }
}

async function saveReportStyle() {
  const conn = $('rep_styleConn').value, proj = $('rep_styleProject').value;
  if (!conn || !proj) { toast('Pick a connection and a project first', true); return; }
  const body = {
    connectionId: conn, projectId: proj,
    accent: $('rep_accentHex').value.trim(),
    orgName: $('rep_orgName').value.trim(),
    logoPos: $('rep_logoPos').value === 'right' ? 'right' : 'left',
    logoScale: Math.min(2, Math.max(0.5, parseFloat($('rep_logoScale').value) || 1)),
    includeSankey: $('rep_incSankey').checked,
    includeHappyPath: $('rep_incHappy').checked,
    includeConformance: $('rep_incConf').checked,
  };
  if (_reportLogo !== null) body.logo = _reportLogo;  // null → keep stored; '' → clear; URI → new
  $('rep_styleResult').textContent = '';
  try {
    await api('/api/reporting/style', { method: 'POST', body: JSON.stringify(body) });
    $('rep_styleResult').textContent = 'Saved.';
    toast('Report style saved for this project');
    loadReporting().catch(() => {});
  } catch (e) { toast(e.message, true); }
}

async function removeReportStyle() {
  const conn = $('rep_styleConn').value, proj = $('rep_styleProject').value;
  if (!conn || !proj) { toast('Pick a connection and a project first', true); return; }
  await deleteStyle(conn, proj);
}

async function deleteReportStyleAt(i) {
  const s = _reportStyles[i];
  if (!s) return;
  await deleteStyle(s.connectionId, s.projectId);
}

async function deleteStyle(conn, proj) {
  try {
    await api('/api/reporting/style?connectionId=' + encodeURIComponent(conn) + '&projectId=' + encodeURIComponent(proj), { method: 'DELETE' });
    toast('Report style removed — this project uses the default theme');
    loadReporting().catch(() => {});
  } catch (e) { toast(e.message, true); }
}

function renderReportStyles(styles, conns) {
  _reportStyles = styles;
  const nameOf = {};
  for (const c of conns) nameOf[c.id] = c.name || c.id;
  if (!styles.length) {
    $('rep_styleList').innerHTML = '<p class="subtle">No project styles yet — every project uses the default theme.</p>';
    return;
  }
  let html = '<table class="tbl"><thead><tr><th>Connection</th><th>Project</th><th>Accent</th><th>Logo</th><th>Sections</th><th></th></tr></thead><tbody>';
  styles.forEach((s, i) => {
    const secs = [s.includeSankey !== false ? 'Sankey' : '', s.includeHappyPath !== false ? 'Happy' : '', s.includeConformance !== false ? 'Conf' : ''].filter(Boolean).join(', ') || '—';
    const swatch = '<span style="display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:middle;background:' + esc(s.accent || '#4a3aa7') + '"></span> ' + esc(s.accent || '');
    html += '<tr><td>' + esc(nameOf[s.connectionId] || s.connectionId) + '</td><td><code>' + esc(s.projectId) + '</code></td>'
      + '<td>' + swatch + '</td>'
      + '<td>' + (s.hasLogo ? (esc(s.logoPos) + ' logo') : '—') + '</td>'
      + '<td class="subtle">' + esc(secs) + '</td>'
      + '<td style="text-align:right; white-space:nowrap">'
      + '<button class="btn small" onclick="editReportStyle(' + i + ')">Edit</button> '
      + '<button class="btn small danger" onclick="deleteReportStyleAt(' + i + ')">Remove</button>'
      + '</td></tr>';
  });
  $('rep_styleList').innerHTML = html + '</tbody></table>';
}

async function editReportStyle(i) {
  const s = _reportStyles[i];
  if (!s) return;
  $('rep_styleConn').value = s.connectionId;
  await loadStyleProjects();
  const sel = $('rep_styleProject');
  // Keep the linked project even if the DB is down / it was renamed.
  if (![...sel.options].some(o => o.value === s.projectId)) {
    sel.insertAdjacentHTML('afterbegin', '<option value="' + esc(s.projectId) + '">' + esc(s.projectId) + '</option>');
  }
  sel.value = s.projectId;
  await loadReportStyle();
}

async function testReportLLM() {
  $('rep_llmTest').textContent = 'Testing…';
  try {
    const r = await api('/api/reporting/test-llm', { method: 'POST', body: JSON.stringify({ llmUrl: $('rep_llmUrl').value.trim(), llmKey: $('rep_llmKey').value }) });
    $('rep_llmTest').textContent = r.error ? ('✗ ' + r.error) : ('✓ reachable' + (r.models && r.models.length ? ' — ' + r.models.length + ' models' : ''));
  } catch (e) { $('rep_llmTest').textContent = '✗ ' + e.message; }
}

async function saveReportPrompt() {
  const body = { connectionId: $('rep_promptConn').value, projectId: $('rep_promptProject').value.trim(), prompt: $('rep_promptText').value };
  if (!body.connectionId || !body.projectId) { toast('Pick a connection and enter a project id', true); return; }
  try {
    await api('/api/reporting/prompts', { method: 'POST', body: JSON.stringify(body) });
    $('rep_promptText').value = '';
    $('rep_promptResult').textContent = 'Saved.';
    toast('Report prompt saved');
    loadReporting().catch(() => {});
  } catch (e) { toast(e.message, true); }
}

async function deleteReportPrompt(i) {
  const p = _reportPrompts[i];
  if (!p) return;
  try {
    await api('/api/reporting/prompts', { method: 'POST', body: JSON.stringify({ connectionId: p.connectionId, projectId: p.projectId, prompt: '' }) });
    toast('Report prompt removed');
    loadReporting().catch(() => {});
  } catch (e) { toast(e.message, true); }
}

// ── Integration console ─────────────────────────────────────────────────────
async function loadIntegration() {
  const s = await api('/api/integration');
  $('int_enabled').checked = !!s.enabled;
  const host = location.hostname || '127.0.0.1';
  const running = s.running
    ? '<span class="pill neutral">launcher running</span>'
    : '<span class="pill off">launcher not detected</span>';
  $('int_status').innerHTML =
    '<div class="row" style="gap:8px; align-items:center">' + running + '</div>' +
    '<div class="subtle">HTTP: <code>http://' + esc(host) + ':' + s.httpPort + '</code></div>' +
    '<div class="subtle">HTTPS: <code>https://' + esc(host) + ':' + s.httpsPort +
      '</code> <span class="muted">(when TLS is optional or required)</span></div>';
}
async function toggleIntegrationEnabled() {
  const enabled = $('int_enabled').checked;
  try {
    await api('/api/integration/enabled', { method: 'POST', body: JSON.stringify({ enabled }) });
    toast(enabled ? 'Integration console enabled — restart to apply'
                  : 'Integration console disabled — restart to apply');
    await loadIntegration();
  } catch (e) { toast(e.message, true); $('int_enabled').checked = !enabled; }
}
async function loadActions() {
  const s = await api('/api/actions');
  $('act_enabled').checked = !!s.enabled;
  const host = location.hostname || '127.0.0.1';
  const running = s.running
    ? '<span class="pill neutral">launcher running</span>'
    : '<span class="pill off">launcher not detected</span>';
  $('act_status').innerHTML =
    '<div class="row" style="gap:8px; align-items:center">' + running + '</div>' +
    '<div class="subtle">HTTP: <code>http://' + esc(host) + ':' + s.httpPort + '</code></div>' +
    '<div class="subtle">HTTPS: <code>https://' + esc(host) + ':' + s.httpsPort +
      '</code> <span class="muted">(when TLS is optional or required)</span></div>';
}
async function toggleActionsEnabled() {
  const enabled = $('act_enabled').checked;
  try {
    await api('/api/actions/enabled', { method: 'POST', body: JSON.stringify({ enabled }) });
    toast(enabled ? 'Actions enabled — restart to apply'
                  : 'Actions disabled — restart to apply');
    await loadActions();
  } catch (e) { toast(e.message, true); $('act_enabled').checked = !enabled; }
}
async function loadSink() {
  const s = await api('/api/sink');
  $('sink_enabled').checked = !!s.enabled;
  const running = s.running
    ? '<span class="pill neutral">supervisor running</span>'
    : '<span class="pill off">supervisor not detected</span>';
  $('sink_status').innerHTML =
    '<div class="row" style="gap:8px; align-items:center">' + running + '</div>' +
    '<div class="subtle">' + s.sinkCount + ' sink(s) configured · pool of ' + s.poolSize + ' port(s)</div>';
}
async function toggleSinkEnabled() {
  const enabled = $('sink_enabled').checked;
  try {
    await api('/api/sink/enabled', { method: 'POST', body: JSON.stringify({ enabled }) });
    toast(enabled ? 'API Server - Event Receiver enabled' : 'API Server - Event Receiver disabled');
    await loadSink();
  } catch (e) { toast(e.message, true); $('sink_enabled').checked = !enabled; }
}

// ── MCP server ──────────────────────────────────────────────────────────────
async function loadMcp() {
  const s = await api('/api/mcp');
  $('mcp_enabled').checked = !!s.enabled;
  const running = s.running
    ? '<span class="pill neutral">launcher running</span>'
    : '<span class="pill off">launcher not detected</span>';
  $('mcp_status').innerHTML =
    '<div class="row" style="gap:8px; align-items:center">' + running + '</div>' +
    '<div class="subtle">Endpoint on HTTP ' + s.httpPort + ' / HTTPS ' + s.httpsPort +
    ' at path <code>/mcp</code> (host ports are +10000 under Docker).</div>';
  const cfg = s.settings || {};
  $('mcp_issuer').value = cfg.issuer || '';
  $('mcp_jwksUri').value = cfg.jwksUri || '';
  $('mcp_audience').value = cfg.audience || '';
  $('mcp_requiredGroup').value = cfg.requiredGroup || '';
  $('mcp_usernameClaim').value = cfg.usernameClaim || 'preferred_username';
}
async function toggleMcpEnabled() {
  const enabled = $('mcp_enabled').checked;
  try {
    await api('/api/mcp/enabled', { method: 'POST', body: JSON.stringify({ enabled }) });
    toast(enabled ? 'MCP server enabled' : 'MCP server disabled');
    await loadMcp();
  } catch (e) { toast(e.message, true); $('mcp_enabled').checked = !enabled; }
}
function _mcpBody() {
  return {
    issuer: $('mcp_issuer').value.trim(),
    jwksUri: $('mcp_jwksUri').value.trim(),
    audience: $('mcp_audience').value.trim(),
    requiredGroup: $('mcp_requiredGroup').value.trim(),
    usernameClaim: $('mcp_usernameClaim').value.trim() || 'preferred_username',
  };
}
async function saveMcpSettings() {
  try {
    await api('/api/mcp/settings', { method: 'POST', body: JSON.stringify(_mcpBody()) });
    toast('MCP settings saved');
    await loadMcp();
  } catch (e) { toast(e.message, true); }
}
async function testMcp() {
  $('mcp_testResult').textContent = 'Testing…';
  try {
    const r = await api('/api/mcp/test', { method: 'POST', body: JSON.stringify(_mcpBody()) });
    $('mcp_testResult').innerHTML = r.ok
      ? '<span style="color:var(--green)">✓ Reached Authentik — ' + r.keyCount + ' signing key(s), issuer ' + (r.issuer || '') + '</span>'
      : '<span style="color:var(--red)">✗ ' + (r.error || 'Failed') + '</span>';
  } catch (e) { $('mcp_testResult').innerHTML = '<span style="color:var(--red)">✗ ' + e.message + '</span>'; }
}

// ── Customize (login page background) ───────────────────────────────────────
let _loginImage = ''; // data: URI of the current / newly-picked background image

async function loadCustomize() {
  const a = await api('/api/customize/login');
  _loginImage = a.image || '';
  const type = ['default', 'color', 'image'].includes(a.type) ? a.type : 'default';
  $('lbg_' + type).checked = true;
  const hex = /^#[0-9a-fA-F]{6}$/.test(a.color) ? a.color : '#f2f2f7';
  $('lbg_colorHex').value = hex;
  $('lbg_colorPicker').value = hex;
  onLoginBgType();
}

function onLoginBgType() {
  const type = (document.querySelector('input[name="loginBg"]:checked') || {}).value || 'default';
  $('lbg_colorRow').style.display = type === 'color' ? 'flex' : 'none';
  $('lbg_imageRow').style.display = type === 'image' ? 'flex' : 'none';
  updateLoginPreview();
}

function syncLoginColor(from) {
  if (from === 'picker') $('lbg_colorHex').value = $('lbg_colorPicker').value;
  else if (/^#[0-9a-fA-F]{6}$/.test($('lbg_colorHex').value)) $('lbg_colorPicker').value = $('lbg_colorHex').value;
  updateLoginPreview();
}

function pickLoginImage() { processLoginImageFile($('lbg_imageFile').files[0]); }

// Accept a file from either the file picker or a drag-and-drop onto the preview.
function processLoginImageFile(f) {
  if (!f) return;
  if (f.size > 30 * 1024 * 1024) { toast('Image file is too large (max 30 MB)', true); $('lbg_imageFile').value = ''; return; }
  const setImg = (uri) => { _loginImage = uri; document.getElementById('lbg_image').checked = true; updateLoginPreview(); toast('Image ready — click Save to store it'); };
  // SVG is vector (and may be animated) — keep it as-is. Every raster format is
  // drawn to a canvas, scaled down to a sensible size and re-encoded, so any photo
  // — however large the original file — ends up well within the stored-image cap.
  if (f.type === 'image/svg+xml' || /\.svg$/i.test(f.name || '')) {
    const r = new FileReader();
    r.onload = () => setImg(r.result);
    r.onerror = () => toast('Could not read the image', true);
    r.readAsDataURL(f);
    return;
  }
  const url = URL.createObjectURL(f);
  const img = new Image();
  img.onload = () => {
    URL.revokeObjectURL(url);
    const MAX = 2560;  // long-edge cap — ample for a full-screen backdrop
    const scale = Math.min(1, MAX / Math.max(img.width, img.height));
    const w = Math.max(1, Math.round(img.width * scale));
    const h = Math.max(1, Math.round(img.height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    canvas.getContext('2d').drawImage(img, 0, 0, w, h);
    // Prefer WebP (smaller, keeps transparency); fall back to JPEG if unsupported.
    let uri = canvas.toDataURL('image/webp', 0.85);
    if (uri.indexOf('data:image/webp') !== 0) uri = canvas.toDataURL('image/jpeg', 0.85);
    if (uri.length > 4000000) uri = canvas.toDataURL('image/jpeg', 0.7);  // last resort
    setImg(uri);
  };
  img.onerror = () => { URL.revokeObjectURL(url); toast('Could not read the image', true); };
  img.src = url;
}

// Drag-and-drop onto the preview box — a reliable path that never touches the OS
// file-picker's confirm button. Drop an image from Finder straight onto the preview.
function dropLoginImage(e) {
  e.preventDefault();
  const box = document.getElementById('lbg_preview');
  if (box) box.classList.remove('drag-over');
  const f = (e.dataTransfer && e.dataTransfer.files || [])[0];
  processLoginImageFile(f);
}
function dragOverLoginImage(e) {
  e.preventDefault();
  const box = document.getElementById('lbg_preview');
  if (box) box.classList.add('drag-over');
}
function dragLeaveLoginImage(e) {
  const box = document.getElementById('lbg_preview');
  if (box) box.classList.remove('drag-over');
}

function updateLoginPreview() {
  const type = (document.querySelector('input[name="loginBg"]:checked') || {}).value || 'default';
  const el = $('lbg_preview');
  if (type === 'color') el.style.background = $('lbg_colorHex').value || 'var(--bg)';
  else if (type === 'image' && _loginImage) el.style.background = 'var(--bg) url("' + _loginImage + '") center / cover no-repeat';
  else el.style.background = 'var(--bg)';
}

async function saveLoginBg() {
  const type = (document.querySelector('input[name="loginBg"]:checked') || {}).value || 'default';
  const body = { type: type, color: $('lbg_colorHex').value };
  if (type === 'image') {
    if (!_loginImage) { toast('Choose a background image first', true); return; }
    body.image = _loginImage;
  }
  $('lbg_result').textContent = '';
  try {
    const a = await api('/api/customize/login', { method: 'POST', body: JSON.stringify(body) });
    _loginImage = a.image || _loginImage;
    $('lbg_result').textContent = 'Saved — new sign-ins use it immediately.';
    toast('Login background saved');
  } catch (e) { $('lbg_result').textContent = ''; toast(e.message, true); }
}

// ── Logging ───────────────────────────────────────────────────────────────
// Default display filter: show INFO + USAGE, hide WARN / ERROR / DEBUG.
let LOG_LEVELS = [], LOG_SEVS = new Set(['INFO', 'USAGE']), _logInited = false, _logReloadTimer = null;
let _logPage = 1, _logPerPage = 25, _logTotal = 0, _logPages = 1, _logEntries = [];

function _logParams() {
  const p = new URLSearchParams();
  if (LOG_SEVS.size) p.set('severities', [...LOG_SEVS].join(','));
  const ip = $('logIp').value.trim(); if (ip) p.set('clientIp', ip);
  const op = $('logOp').value; if (op) p.set('operation', op);
  const tg = $('logTag').value; if (tg) p.set('tag', tg);
  const q = $('logSearch').value.trim(); if (q) p.set('search', q);
  return p;
}
async function loadLogs() {
  const params = _logParams();
  params.set('page', String(_logPage));
  params.set('perPage', String(_logPerPage));
  const r = await api('/api/logs?' + params.toString());
  LOG_LEVELS = r.severities || [];
  if (!_logInited) {
    _logInited = true;
    $('logLevel').innerHTML = LOG_LEVELS.map(lv => `<option value="${lv}">${lv}</option>`).join('');
    $('logLevel').value = r.config.level;
    $('logMaxMb').value = Math.max(1, Math.round(r.config.maxBytes / 1000000));
  }
  renderSeverityChips();
  const curOp = $('logOp').value;
  $('logOp').innerHTML = '<option value="">All operations</option>' +
    (r.operations || []).map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
  $('logOp').value = curOp;
  const curTag = $('logTag').value;
  $('logTag').innerHTML = '<option value="">All tags</option>' +
    (r.tags || []).map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('');
  $('logTag').value = curTag;
  _logPage = r.page; _logPerPage = r.perPage; _logTotal = r.total; _logPages = r.pages;
  _logEntries = r.entries || [];
  renderLogRows(_logEntries);
  renderLogPager();
}
// Filters/search span the entire log, so any filter change returns to page 1.
function logResetReload() { _logPage = 1; loadLogs().catch(e => toast(e.message, true)); }
function logGoto(p) { _logPage = Math.max(1, Math.min(p, _logPages)); loadLogs().catch(e => toast(e.message, true)); }
function setLogPerPage() {
  _logPerPage = parseInt($('logPerPage').value, 10) || 25;
  _logPage = 1;
  loadLogs().catch(e => toast(e.message, true));
}
function renderLogPager() {
  const nav = $('logPagerNav');
  if (!_logTotal) { nav.innerHTML = '<span class="subtle">No entries</span>'; return; }
  const start = (_logPage - 1) * _logPerPage + 1;
  const end = Math.min(_logTotal, _logPage * _logPerPage);
  nav.innerHTML =
    `<span class="subtle">${start}–${end} of ${_logTotal}</span>` +
    `<button class="btn small" ${_logPage <= 1 ? 'disabled' : ''} onclick="logGoto(1)">« First</button>` +
    `<button class="btn small" ${_logPage <= 1 ? 'disabled' : ''} onclick="logGoto(${_logPage - 1})">‹ Prev</button>` +
    `<span class="subtle">Page ${_logPage} / ${_logPages}</span>` +
    `<button class="btn small" ${_logPage >= _logPages ? 'disabled' : ''} onclick="logGoto(${_logPage + 1})">Next ›</button>` +
    `<button class="btn small" ${_logPage >= _logPages ? 'disabled' : ''} onclick="logGoto(${_logPages})">Last »</button>`;
}
function renderSeverityChips() {
  $('logSeverityFilter').innerHTML = LOG_LEVELS.map(lv =>
    `<button class="${LOG_SEVS.size === 0 || LOG_SEVS.has(lv) ? 'sel' : ''}" onclick="toggleLogSeverity('${lv}')">${lv}</button>`
  ).join('');
}
function toggleLogSeverity(lv) {
  if (LOG_SEVS.size === 0) LOG_LEVELS.forEach(l => LOG_SEVS.add(l));  // 'all' → explicit
  if (LOG_SEVS.has(lv)) LOG_SEVS.delete(lv); else LOG_SEVS.add(lv);
  if (LOG_SEVS.size === LOG_LEVELS.length) LOG_SEVS.clear();          // all selected → 'all'
  logResetReload();
}
function renderLogRows(entries) {
  if (!entries.length) { $('logTable').innerHTML = '<p class="subtle">No matching log entries.</p>'; return; }
  let h = '<table><thead><tr><th>Date</th><th>Time</th><th>Severity</th><th>Tag</th><th>Client IP</th><th>User</th><th>Message</th></tr></thead><tbody>';
  entries.forEach((e, i) => {
    h += `<tr onclick="showLogEntry(${i})" title="Click to view the full entry">` +
      `<td class="mono">${e.date}</td><td class="mono">${e.time}</td>` +
      `<td><span class="pill log-${e.severity.toLowerCase()}">${e.severity}</span></td>` +
      `<td>${e.tag ? '<span class="pill neutral">' + esc(e.tag) + '</span>' : '<span class="muted">—</span>'}</td>` +
      `<td class="mono">${esc(e.clientIp || '—')}</td><td>${esc(e.user || '—')}</td>` +
      `<td>${esc(e.message)}</td></tr>`;
  });
  $('logTable').innerHTML = h + '</tbody></table>';
}
// Minimal, dependency-free SQL pretty-printer: breaks before major clauses and
// indents subqueries by parenthesis depth. String literals are tokenised first
// so their contents (e.g. 'GROUP …') are never treated as keywords.
function tokenizeSql(s) {
  const toks = []; let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c === "'") {                       // 'string' with '' escapes
      let j = i + 1;
      while (j < s.length) { if (s[j] === "'") { if (s[j+1] === "'") { j += 2; continue; } j++; break; } j++; }
      toks.push({ t: 'str', v: s.slice(i, j) }); i = j;
    } else if (c === '(' || c === ')' || c === ',') { toks.push({ t: c, v: c }); i++; }
    else if (/\s/.test(c)) { i++; }
    else { let j = i; while (j < s.length && !/[\s(),']/.test(s[j])) j++; toks.push({ t: 'word', v: s.slice(i, j) }); i = j; }
  }
  return toks;
}
function formatSql(raw) {
  // Drop the "SQL:" / "SQL (12.3 ms):" trace prefix before formatting.
  const s = String(raw).replace(/^\s*SQL\s*(\([^)]*\))?\s*:\s*/i, '').trim();
  const toks = tokenizeSql(s);
  const CLAUSE = new Set(['SELECT','FROM','WHERE','GROUP','ORDER','HAVING','LIMIT','UNION','ON','VALUES','SET']);
  const JOINQ = new Set(['LEFT','RIGHT','INNER','FULL','CROSS','OUTER']);
  // Keywords that keep a space before '(' (so it reads "IN (…)"); anything else
  // before '(' is treated as a function call and attaches ("COUNT(*)").
  const PAREN_SPACE = new Set(['IN','AND','OR','NOT','ON','EXISTS','ANY','ALL','SELECT','VALUES','BETWEEN','WHEN','THEN','ELSE','UNION','WHERE','HAVING']);
  const lines = []; let line = '', indent = 0, lineIndent = 0, betweenPending = false;
  const stack = [];
  const add = (t) => {
    if (line === '') { lineIndent = indent; line = t; }
    else if (line.endsWith('(')) line += t;
    else line += ' ' + t;
  };
  const flush = () => { if (line !== '') { lines.push('  '.repeat(Math.max(0, lineIndent)) + line); line = ''; } };
  for (let k = 0; k < toks.length; k++) {
    const tk = toks[k];
    const up = tk.t === 'word' ? tk.v.toUpperCase() : '';
    const prevUp = k > 0 && toks[k-1].t === 'word' ? toks[k-1].v.toUpperCase() : '';
    const nextUp = k + 1 < toks.length && toks[k+1].t === 'word' ? toks[k+1].v.toUpperCase() : '';
    if (tk.t === '(') {
      const sub = nextUp === 'SELECT';
      if (line !== '' && /\w$/.test(line) && !PAREN_SPACE.has(prevUp)) line += '(';  // function call
      else add('(');
      stack.push(sub); indent++; if (sub) flush(); continue;
    }
    if (tk.t === ')') { const sub = stack.pop(); indent = Math.max(0, indent - 1); if (sub) { flush(); add(')'); } else line += ')'; continue; }
    if (tk.t === ',') { line += ','; continue; }
    if (tk.t === 'str') { add(tk.v); continue; }
    if (up === 'BETWEEN') { betweenPending = true; add(tk.v); continue; }
    if ((up === 'AND' || up === 'OR') && prevUp !== 'CREATE') {
      if (up === 'AND' && betweenPending) { betweenPending = false; add(tk.v); continue; }  // "BETWEEN x AND y"
      flush(); add(tk.v); continue;
    }
    if (up === 'JOIN' && JOINQ.has(prevUp)) { add(tk.v); continue; }
    if (JOINQ.has(up) || up === 'JOIN') { flush(); add(tk.v); continue; }
    if (CLAUSE.has(up)) { if (!(up === 'SELECT' && line === '')) flush(); add(tk.v); continue; }
    add(tk.v);
  }
  flush();
  return lines.join('\n');
}
function showLogEntry(i) {
  const e = _logEntries[i];
  if (!e) return;
  const field = (k, v) =>
    `<div style="display:flex; gap:12px; margin-bottom:5px">` +
    `<span class="subtle" style="min-width:92px">${k}</span>` +
    `<span class="mono">${esc(v || '—')}</span></div>`;
  // The verbose SQL trace (operation 'sql') is pretty-printed and its execution
  // time surfaced as a field; anything else is shown verbatim.
  const isSql = e.operation === 'sql';
  const durMatch = isSql && e.message.match(/^\s*SQL\s*\(([^)]+)\)\s*:/i);
  const body = isSql ? formatSql(e.message) : e.message;
  $('logModalBody').innerHTML =
    field('Date', e.date) + field('Time', e.time) + field('Severity', e.severity) +
    field('Client IP', e.clientIp) + field('User', e.user) + field('Operation', e.operation) +
    field('Tag', e.tag) +
    (durMatch ? field('Execution time', durMatch[1]) : '') +
    `<div class="subtle" style="margin:12px 0 4px">${isSql ? 'SQL' : 'Message'}</div>` +
    `<pre class="codeblock" style="white-space:pre-wrap; word-break:break-word; max-height:52vh; overflow:auto">${esc(body)}</pre>`;
  $('logModal').hidden = false;
}
function closeLogModal() { $('logModal').hidden = true; }
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('logModal').hidden) closeLogModal(); });
function scheduleLogReload() {
  clearTimeout(_logReloadTimer);
  _logReloadTimer = setTimeout(logResetReload, 300);
}
async function saveLogConfig() {
  const level = $('logLevel').value;
  const maxBytes = Math.max(1, parseInt($('logMaxMb').value, 10) || 1) * 1000000;
  try { await api('/api/logs/config', { method: 'POST', body: JSON.stringify({ level, maxBytes }) });
    toast('Logging config saved'); await loadLogs(); }
  catch (e) { toast(e.message, true); }
}
async function clearLogs() {
  if (!confirm('Clear the live log?\n\nThis empties the current log (rotated archive files are kept).')) return;
  try { await api('/api/logs/clear', { method: 'POST' }); toast('Log cleared'); _logPage = 1; await loadLogs(); }
  catch (e) { toast(e.message, true); }
}
function downloadLog() {
  window.location = '/api/logs/download?' + _logParams().toString();
}

// ── Backup / restore ──────────────────────────────────────────────────────
let _bkContent = '';
const BACKUP_RESTORE_OPTS = [
  ['appSettings', 'App settings & preferences'],
  ['connections', 'Connections & servers'],
  ['username', 'Usernames'],
  ['llmApiKey', 'LLM API keys'],
  ['passwords', 'Database passwords'],
  ['layouts', 'Saved node layouts'],
  ['norms', 'Target norms'],
  ['happyPaths', 'Happy paths'],
  ['filterPresets', 'Filter presets'],
];

let _bkHasPassword = false; // whether an automatic-backup password is stored

function updateBackupWarn() {
  const wantSecrets = $('schedInclPw').checked || $('schedInclLlm').checked;
  const noPassword = !$('schedPw').value && !_bkHasPassword;
  $('bkSecretWarn').style.display = (wantSecrets && noPassword) ? 'block' : 'none';
}

async function downloadBackup() {
  try {
    const resp = await fetch('/api/backup/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        includeUsername: $('schedInclUser').checked,
        includePasswords: $('schedInclPw').checked,
        includeLlmApiKey: $('schedInclLlm').checked,
        password: $('schedPw').value,   // blank → reuse the stored backup password
        useStoredPassword: true,
      }),
    });
    if (resp.status === 401) { location.href = '/login'; return; }
    if (!resp.ok) { toast('Download failed', true); return; }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'ProcessMining-Backup-' + new Date().toISOString().slice(0, 10) + '.json';
    a.click();
    URL.revokeObjectURL(url);
    toast('Backup downloaded');
  } catch (e) { toast(e.message, true); }
}

function _fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => {
      const bytes = new Uint8Array(r.result);
      let s = '';
      for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
      resolve(btoa(s));
    };
    r.onerror = reject;
    r.readAsArrayBuffer(file);
  });
}

async function pickBackupFile() {
  const f = $('bkFile').files[0];
  if (!f) return;
  _bkContent = await _fileToBase64(f);
  $('bkSummary').style.display = 'none';
  $('bkError').style.display = 'none';
  inspectBackup();
}

async function inspectBackup() {
  if (!_bkContent) { toast('Choose a backup file first', true); return; }
  $('bkError').style.display = 'none';
  try {
    const s = await api('/api/backup/inspect', {
      method: 'POST',
      body: JSON.stringify({ content: _bkContent, password: $('bkRestorePw').value }),
    });
    renderBackupSummary(s);
  } catch (e) {
    $('bkSummary').style.display = 'none';
    $('bkError').textContent = e.message;
    $('bkError').style.display = 'block';
  }
}

function renderBackupSummary(s) {
  const inc = [
    s.includesUsername ? 'usernames' : '—',
    s.includesPasswords ? 'passwords' : 'no passwords',
    s.includesLlmApiKey ? 'API keys' : 'no API keys',
  ];
  const rows = [
    'Created: ' + (s.createdAt || '—'),
    'Connections: ' + (s.connectionCount || 0),
    'Projects with settings: ' + (s.projectCount || 0),
    'Includes: ' + inc.join(', '),
  ];
  if (s.connectionNames && s.connectionNames.length) {
    rows.push('Overwrites: ' + s.connectionNames.join(', '));
  }
  $('bkSummaryBody').innerHTML = rows.map((r) => '<span>' + esc(r) + '</span>').join('');
  $('bkRestoreOpts').innerHTML = BACKUP_RESTORE_OPTS.map(
    (o) =>
      '<label class="row" style="gap:8px; font-size:14px"><input type="checkbox" class="bk-opt" data-key="' +
      o[0] + '" checked style="width:auto"> ' + esc(o[1]) + '</label>'
  ).join('');
  $('bkSummary').style.display = 'block';
}

async function restoreBackup() {
  const opts = {};
  document.querySelectorAll('.bk-opt').forEach((c) => { opts[c.dataset.key] = c.checked; });
  if (!confirm('Restore the selected items from this backup?\n\nThis overwrites the current settings.')) return;
  try {
    await api('/api/backup/restore', {
      method: 'POST',
      body: JSON.stringify({ content: _bkContent, password: $('bkRestorePw').value, options: opts }),
    });
    toast('Backup restored');
  } catch (e) { toast(e.message, true); }
}

// ── Scheduled backups ──────────────────────────────────────────────────────
const WEEKDAYS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

function _fillSelect(id, from, to, labelFn) {
  const sel = $(id);
  if (sel.options.length) return; // populate once
  for (let i = from; i <= to; i++) {
    const o = document.createElement('option');
    o.value = String(i);
    o.textContent = labelFn ? labelFn(i) : (i < 10 ? '0' + i : String(i));
    sel.appendChild(o);
  }
}

function _initSchedSelects() {
  _fillSelect('schedHour', 0, 23);
  _fillSelect('schedMinute', 0, 59);
  _fillSelect('schedDow', 0, 6, (i) => WEEKDAYS[i]);
  _fillSelect('schedDom', 1, 28, (i) => String(i)); // 1..28: valid in every month
}

function onSchedFreqChange() {
  const f = $('schedFreq').value;
  $('schedMinuteWrap').style.display = (f === 'custom') ? 'none' : 'block';
  $('schedHourWrap').style.display = (f === 'hourly' || f === 'custom') ? 'none' : 'block';
  $('schedDowWrap').style.display = (f === 'weekly') ? 'block' : 'none';
  $('schedDomWrap').style.display = (f === 'monthly') ? 'block' : 'none';
  $('schedCustomWrap').style.display = (f === 'custom') ? 'block' : 'none';
  if (f === 'custom') onCustomCron(); else updateCron();
}

function buildCron() {
  const f = $('schedFreq').value;
  const m = $('schedMinute').value, h = $('schedHour').value;
  const dow = $('schedDow').value, dom = $('schedDom').value;
  if (f === 'hourly')  return m + ' * * * *';
  if (f === 'daily')   return m + ' ' + h + ' * * *';
  if (f === 'weekly')  return m + ' ' + h + ' * * ' + dow;
  if (f === 'monthly') return m + ' ' + h + ' ' + dom + ' * *';
  return $('schedCron').value.trim();
}

function pad2(n) { n = Number(n); return (n < 10 ? '0' : '') + n; }

function describeSched() {
  const f = $('schedFreq').value;
  const m = $('schedMinute').value, h = $('schedHour').value;
  if (f === 'hourly')  return 'Every hour at :' + pad2(m);
  if (f === 'daily')   return 'Every day at ' + pad2(h) + ':' + pad2(m);
  if (f === 'weekly')  return 'Every ' + WEEKDAYS[Number($('schedDow').value)] + ' at ' + pad2(h) + ':' + pad2(m);
  if (f === 'monthly') return 'On day ' + $('schedDom').value + ' of each month at ' + pad2(h) + ':' + pad2(m);
  return 'Custom schedule';
}

function updateCron() {
  $('schedCronOut').textContent = buildCron() || '(empty)';
  $('schedSummary').textContent = describeSched();
}

function onCustomCron() {
  $('schedCronOut').textContent = $('schedCron').value.trim() || '(empty)';
  $('schedSummary').textContent = 'Custom schedule';
}

function _applyCronToWizard(cron) {
  const parts = (cron || '').trim().split(/\s+/);
  const isNum = (s) => /^\d+$/.test(s);
  if (parts.length === 5) {
    const [m, h, dom, mon, dow] = parts;
    if (mon === '*' && isNum(m)) {
      if (h === '*' && dom === '*' && dow === '*') { $('schedFreq').value='hourly'; $('schedMinute').value=m; onSchedFreqChange(); return; }
      if (isNum(h) && dom === '*' && dow === '*') { $('schedFreq').value='daily'; $('schedMinute').value=m; $('schedHour').value=h; onSchedFreqChange(); return; }
      if (isNum(h) && dom === '*' && isNum(dow) && Number(dow) <= 6) { $('schedFreq').value='weekly'; $('schedMinute').value=m; $('schedHour').value=h; $('schedDow').value=dow; onSchedFreqChange(); return; }
      if (isNum(h) && isNum(dom) && Number(dom) >= 1 && Number(dom) <= 28 && dow === '*') { $('schedFreq').value='monthly'; $('schedMinute').value=m; $('schedHour').value=h; $('schedDom').value=dom; onSchedFreqChange(); return; }
    }
  }
  $('schedFreq').value = 'custom';
  $('schedCron').value = cron || '';
  onSchedFreqChange();
}

function _renderSchedStatus(s) {
  const el = $('schedStatus');
  if (!s) { el.textContent = 'No backup has run yet.'; return; }
  const when = s.at ? fmtDate(s.at) : '';
  if (s.ok) {
    el.textContent = 'Last backup: ' + when + ' — ' + (s.file || '') +
      (s.bytes ? ' (' + Math.round(s.bytes / 1024) + ' KB)' : '') +
      (s.trigger === 'manual' ? ' · manual' : '');
  } else {
    el.innerHTML = '<span style="color:#d9534f">Last attempt failed: ' + esc(s.error || '') + ' — ' + when + '</span>';
  }
}

async function loadSchedule() {
  _initSchedSelects();
  const s = await api('/api/backup/schedule');
  $('schedEnabled').checked = !!s.enabled;
  $('schedRetention').value = s.retention || 30;
  $('schedInclUser').checked = s.includeUsername !== false;
  $('schedInclPw').checked = s.includePasswords !== false;
  $('schedInclLlm').checked = s.includeLlmKey !== false;
  $('schedPw').value = '';
  _bkHasPassword = !!s.hasPassword;
  $('schedPwHint').textContent = s.hasPassword
    ? '(set — leave blank to keep it; also reused for downloads)'
    : '(none set — required for automatic backups)';
  updateBackupWarn();
  _applyCronToWizard(s.cron || '0 2 * * *');
  _renderSchedStatus(s.status);
}

async function saveSchedule() {
  const body = {
    enabled: $('schedEnabled').checked,
    cron: buildCron(),
    retention: Math.max(1, parseInt($('schedRetention').value, 10) || 30),
    includeUsername: $('schedInclUser').checked,
    includePasswords: $('schedInclPw').checked,
    includeLlmKey: $('schedInclLlm').checked,
  };
  const pw = $('schedPw').value;
  if (pw) body.password = pw; // omit to keep the stored password
  try {
    await api('/api/backup/schedule', { method: 'POST', body: JSON.stringify(body) });
    toast('Backup schedule saved');
    await loadSchedule();
  } catch (e) { toast(e.message, true); }
}

async function runBackupNow() {
  try {
    const s = await api('/api/backup/run-now', {
      method: 'POST',
      body: JSON.stringify({ password: $('schedPw').value }), // typed → else stored
    });
    toast('Backup written on server: ' + (s.file || 'ok'));
    _renderSchedStatus(s);
  } catch (e) { toast(e.message, true); }
}

// ── Directory (LDAP) ──────────────────────────────────────────────────────
async function loadLdap() {
  const c = await api('/api/ldap');
  $('l_enabled').checked = !!c.enabled;
  $('l_adminLogin').checked = !!c.adminLoginEnabled;
  $('l_showStatus').checked = c.showStatusOnLogin !== false;
  $('l_uri').value = c.serverURI || '';
  $('l_startTls').checked = !!c.startTLS;
  $('l_verify').checked = c.verifyCert !== false;
  $('l_caCert').value = c.caCert || '';
  $('l_bindDN').value = c.bindDN || '';
  $('l_bindPw').value = '';
  $('l_bindPwHint').textContent = c.hasBindPassword ? '(set — leave blank to keep)' : '';
  $('l_baseDN').value = c.baseDN || '';
  $('l_filter').value = c.userFilter || '(uid={username})';
  $('l_loginAttr').value = c.loginAttr || 'uid';
  $('l_emailAttr').value = c.emailAttr || 'mail';
  $('l_displayAttr').value = c.displayAttr || 'cn';
  $('l_testResult').innerHTML = '';
}
function ldapBody() {
  const body = {
    enabled: $('l_enabled').checked,
    adminLoginEnabled: $('l_adminLogin').checked,
    showStatusOnLogin: $('l_showStatus').checked,
    serverURI: $('l_uri').value.trim(),
    startTLS: $('l_startTls').checked,
    verifyCert: $('l_verify').checked,
    caCert: $('l_caCert').value,
    bindDN: $('l_bindDN').value.trim(),
    baseDN: $('l_baseDN').value.trim(),
    userFilter: $('l_filter').value.trim() || '(uid={username})',
    loginAttr: $('l_loginAttr').value.trim() || 'uid',
    emailAttr: $('l_emailAttr').value.trim() || 'mail',
    displayAttr: $('l_displayAttr').value.trim() || 'cn',
  };
  if ($('l_bindPw').value) body.bindPassword = $('l_bindPw').value;
  return body;
}
async function saveLdap() {
  try { await api('/api/ldap', { method: 'POST', body: JSON.stringify(ldapBody()) });
    toast('Directory settings saved'); await loadLdap(); }
  catch (e) { toast(e.message, true); }
}
async function testLdapServer() {
  // Server + service-bind only — no user is resolved (test username left blank).
  const body = ldapBody();
  body.testUsername = '';
  body.testPassword = '';
  $('l_serverTestResult').innerHTML = '<span class="muted">Testing…</span>';
  try {
    const r = await api('/api/ldap/test', { method: 'POST', body: JSON.stringify(body) });
    $('l_serverTestResult').innerHTML = r.ok
      ? '<div class="banner info">Server reachable — service bind OK</div>'
      : `<div class="banner warn">${esc(r.error)}</div>`;
  } catch (e) { $('l_serverTestResult').innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; }
}
async function testLdap() {
  const body = ldapBody();
  body.testUsername = $('l_testUser').value.trim();
  body.testPassword = $('l_testPw').value;
  $('l_testResult').innerHTML = '<span class="muted">Testing…</span>';
  try {
    const r = await api('/api/ldap/test', { method: 'POST', body: JSON.stringify(body) });
    let h = r.ok
      ? '<div class="banner info">Service bind: OK</div>'
      : `<div class="banner warn">Service bind failed: ${esc(r.error)}</div>`;
    if (r.matched != null) {
      const cls = r.matched === 1 ? 'info' : 'warn';
      h += `<div class="banner ${cls}">Search matched ${r.matched} entr${r.matched === 1 ? 'y' : 'ies'}` +
        `${r.foundDN ? ' <span class="subtle">(' + esc(r.foundDN) + ')</span>' : ''}</div>`;
    }
    if (r.userOk === true) {
      const u = r.user || {};
      h += `<div class="banner info">User login: OK — ${esc(u.username || '')}${u.dn ? ' <span class="subtle">(' + esc(u.dn) + ')</span>' : ''}</div>`;
    } else if (r.userOk === false) {
      h += `<div class="banner warn">${esc(r.error || 'User login failed')}</div>`;
    }
    $('l_testResult').innerHTML = h;
  } catch (e) { $('l_testResult').innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; }
}

// ── Database Connections ──────────────────────────────────────────────────
let CONNS = [];
let USERNAMES = [];

async function loadConnections() {
  const [conns, users] = await Promise.all([api('/api/connections'), api('/api/users')]);
  CONNS = conns;
  USERNAMES = users.map(u => u.username);
  let h = '<table><thead><tr><th>Name</th><th>Host</th><th>LLM</th><th>Assigned to</th><th></th></tr></thead><tbody>';
  if (!conns.length) h += '<tr><td colspan="5" class="muted">No connections defined yet.</td></tr>';
  for (const c of conns) {
    const who = c.assignments.length ? c.assignments.map(esc).join(', ') : '<span class="muted">nobody</span>';
    h += `<tr><td><strong>${esc(c.name)}</strong>${c.comment ? '<br><span class="subtle">' + esc(c.comment) + '</span>' : ''}</td>` +
      `<td class="muted">${esc(c.host)}:${c.port}</td>` +
      `<td>${c.hasLLMKey || c.llmURL ? '<span class="pill on">yes</span>' : '<span class="muted">—</span>'}</td>` +
      `<td class="muted">${who}</td>` +
      `<td style="text-align:right; white-space:nowrap">` +
        `<button class="btn small" data-id="${esc(c.id)}" onclick="editConnection(this.dataset.id)">Edit</button></td></tr>`;
  }
  $('connTable').innerHTML = h + '</tbody></table>';
}

function renderAssign(selected) {
  const set = new Set(selected || []);
  $('c_assign').innerHTML = USERNAMES.length
    ? USERNAMES.map(u => `<label><input type="checkbox" value="${esc(u)}"${set.has(u) ? ' checked' : ''} style="width:auto"> ${esc(u)}</label>`).join('')
    : '<span class="muted">No users to assign.</span>';
}
function selectedAssignments() {
  return [...$('c_assign').querySelectorAll('input:checked')].map(i => i.value);
}
function toggleTlsFields() { $('c_tlsFields').style.display = $('c_useTls').checked ? 'block' : 'none'; }

function fillEditor(c) {
  $('c_id').value = c.id || '';
  $('c_name').value = c.name || '';
  $('c_comment').value = c.comment || '';
  $('c_host').value = c.host || '';
  $('c_port').value = c.port || 8563;
  $('c_username').value = c.username || '';
  $('c_schema').value = c.schema || '';
  $('c_password').value = '';
  $('c_pwHint').textContent = c.hasPassword ? '(set — leave blank to keep)' : '';
  $('c_useTls').checked = !!c.useTLS; toggleTlsFields();
  $('c_certMode').value = c.certModeRaw || 'verify';
  $('c_fingerprint').value = c.fingerprint || '';
  $('c_minRsa').value = c.minRSAKeySizeBits || 2048;
  $('c_llmUrl').value = c.llmURL || '';
  $('c_llmModel').value = c.llmModel || '';
  $('c_llmKey').value = '';
  $('c_llmKeyHint').textContent = c.hasLLMKey ? '(set — leave blank to keep)' : '';
  renderAssign(c.assignments);
  $('c_useMaterialized').checked = !!c.useMaterializedTransitions;
  $('c_useInDbSampling').checked = !!c.useInDbSampling;
  renderMatStatus(c);
  $('c_matResult').textContent = '';
  $('c_rebuildBtn').disabled = !c.id;  // needs a saved connection to rebuild against
  $('c_rebuildBtn').title = c.id ? '' : 'Save the connection first';
  $('c_provisionBuildMat').checked = false;
  // Per-connection rebuild API: reset the shown-once token, collapse the box,
  // reflect whether this connection already has a token, and prime the example.
  LAST_TOKEN = '';
  $('rtValue').textContent = '';
  $('c_apiBox').open = false;
  renderTokenStatus(!!c.rebuildTokenSet);
  renderCurl();
  $('c_testResult').innerHTML = '';
  $('c_provisionResult').textContent = '';
  $('c_deleteBtn').style.display = c.id ? 'inline-flex' : 'none';
  // Reset the inner tabs to Database; Projects needs a saved connection to query.
  const projBtn = $('c_projectsTabBtn');
  projBtn.disabled = !c.id;
  projBtn.title = c.id ? '' : 'Save the connection first to list its projects';
  $('c_projectsList').innerHTML = c.id
    ? '<span class="muted">Open the Projects tab to load them.</span>'
    : '<span class="muted">Save the connection first to list its projects.</span>';
  selectConnTab('db');
  $('connEditor').style.display = 'block';
  $('connEditor').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function renderMatStatus(c) {
  const m = c && c.materialization;
  if (!m) { $('c_matStatus').textContent = 'Not built yet — the live query is used until you rebuild.'; return; }
  if (m.ok) {
    $('c_matStatus').innerHTML = `Last built: ${esc(fmtDate(m.built_at))} · ${Number(m.rows || 0).toLocaleString()} pairs.`;
  } else {
    $('c_matStatus').innerHTML = `<span style="color:var(--red)">Last rebuild failed: ${esc(m.error || 'unknown error')}</span>`;
  }
}
function newConnection() {
  renderAssign([]);
  fillEditor({ port: 8563, minRSAKeySizeBits: 2048, certModeRaw: 'verify' });
}
function editConnection(id) {
  const c = CONNS.find(x => x.id === id);
  if (c) fillEditor(c);
}
function cancelConnection() { $('connEditor').style.display = 'none'; }

// Inner tabs of the connection editor (Database / LLM / Projects).
function selectConnTab(name) {
  for (const b of document.querySelectorAll('.ctabs button'))
    b.classList.toggle('sel', b.dataset.ctab === name);
  for (const p of document.querySelectorAll('#connEditor .ctabpanel'))
    p.classList.toggle('sel', p.id === 'ctab-' + name);
  if (name === 'projects') loadProjects().catch(e => toast(e.message, true));
  // Switching to a shorter panel (LLM/Projects) shrinks the page; without this the
  // browser clamps the scroll upward and the connection list jumps back into view.
  // Keep the editor pinned to the top so the user stays on it. (No-op while the
  // editor is still hidden — e.g. the selectConnTab('db') fillEditor does at open.)
  const ed = document.getElementById('connEditor');
  if (ed && ed.style.display !== 'none')
    ed.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function loadProjects() {
  const id = $('c_id').value;
  const box = $('c_projectsList');
  $('c_projSchema').textContent = $('c_schema').value || '(no schema)';
  if (!id) { box.innerHTML = '<span class="muted">Save the connection first to list its projects.</span>'; return; }
  box.innerHTML = '<span class="muted">Loading projects…</span>';
  let res;
  try { res = await api('/api/connections/' + encodeURIComponent(id) + '/projects'); }
  catch (e) { box.innerHTML = '<span style="color:var(--red)">' + esc(e.message) + '</span>'; return; }
  if (!res.ok) { box.innerHTML = '<span style="color:var(--red)">' + esc(res.error || 'Could not read projects.') + '</span>'; return; }
  const ps = res.projects || [];
  if (!ps.length) { box.innerHTML = '<span class="muted">No projects found in this schema.</span>'; return; }
  let h = '<table><thead><tr><th>Project</th><th style="text-align:right">Journeys</th><th style="text-align:right">Events</th><th></th></tr></thead><tbody>';
  for (const p of ps) {
    const sub = p.title !== p.projectId ? '<br><span class="subtle">' + esc(p.projectId) + '</span>' : '';
    h += `<tr><td><strong>${esc(p.title)}</strong>${sub}</td>` +
      `<td style="text-align:right">${Number(p.journeys || 0).toLocaleString()}</td>` +
      `<td style="text-align:right">${Number(p.events || 0).toLocaleString()}</td>` +
      `<td style="text-align:right"><button class="btn small danger" data-pid="${esc(p.projectId)}" onclick="deleteProject(this.dataset.pid)">Delete</button></td></tr>`;
  }
  box.innerHTML = h + '</tbody></table>';
}

async function deleteProject(pid) {
  const id = $('c_id').value;
  if (!id) return;
  if (!confirm('Delete project "' + pid + '"?\n\nThis clears its rows from PROJECTS, JOURNEYS, STEPS, METAS, NOTES and TRANSITIONS_RAW in this schema. This cannot be undone.')) return;
  try {
    const res = await api('/api/connections/' + encodeURIComponent(id) + '/projects/delete',
      { method: 'POST', body: JSON.stringify({ projectId: pid }) });
    if (res && res.ok === false) { toast(res.error || 'Delete failed', true); return; }
    const n = res && res.events != null ? ' (' + Number(res.events).toLocaleString() + ' events)' : '';
    toast('Project deleted' + n);
    await loadProjects();
  } catch (e) { toast(e.message, true); }
}

function editorBody() {
  const body = {
    id: $('c_id').value || null,
    name: $('c_name').value.trim(),
    comment: $('c_comment').value.trim(),
    host: $('c_host').value.trim(),
    port: parseInt($('c_port').value, 10) || 8563,
    username: $('c_username').value.trim(),
    schema: $('c_schema').value.trim(),
    useTLS: $('c_useTls').checked,
    certModeRaw: $('c_certMode').value,
    fingerprint: $('c_fingerprint').value.trim(),
    minRSAKeySizeBits: parseInt($('c_minRsa').value, 10) || 2048,
    llmURL: $('c_llmUrl').value.trim(),
    llmModel: $('c_llmModel').value.trim(),
    assignments: selectedAssignments(),
    useMaterializedTransitions: $('c_useMaterialized').checked,
    useInDbSampling: $('c_useInDbSampling').checked,
  };
  // Only send secrets when the user typed something (blank ⇒ keep existing).
  if ($('c_password').value) body.password = $('c_password').value;
  if ($('c_llmKey').value) body.llmKey = $('c_llmKey').value;
  return body;
}
async function saveConnection() {
  const body = editorBody();
  if (!body.name) { toast('Name is required.', true); return; }
  try {
    const saved = await api('/api/connections', { method: 'POST', body: JSON.stringify(body) });
    toast('Connection saved');
    await loadConnections();
    const fresh = CONNS.find(x => x.id === saved.id);
    if (fresh) fillEditor(fresh);
  } catch (e) { toast(e.message, true); }
}
async function deleteConnection() {
  const id = $('c_id').value;
  if (!id) return;
  if (!confirm('Delete connection "' + $('c_name').value + '"?')) return;
  try {
    await api('/api/connections/' + encodeURIComponent(id), { method: 'DELETE' });
    toast('Connection deleted'); cancelConnection(); await loadConnections();
  } catch (e) { toast(e.message, true); }
}
async function testConnection() {
  const body = editorBody();
  const test = {
    host: body.host, port: body.port, username: body.username,
    password: $('c_password').value, schema: body.schema, useTLS: body.useTLS,
    certModeRaw: body.certModeRaw, fingerprint: body.fingerprint,
    minRSAKeySizeBits: body.minRSAKeySizeBits, llmURL: body.llmURL, llmKey: $('c_llmKey').value,
  };
  $('c_testResult').innerHTML = '<span class="muted">Testing…</span>';
  try {
    const r = await api('/api/connections/test', { method: 'POST', body: JSON.stringify(test) });
    let h = '';
    h += r.dbError
      ? `<div class="banner warn">Database: ${esc(r.dbError)}</div>`
      : '<div class="banner info">Database: connection OK</div>';
    if (body.llmURL) {
      h += r.llmError
        ? `<div class="banner warn">LLM: ${esc(r.llmError)}</div>`
        : `<div class="banner info">LLM: reachable${r.llmModels && r.llmModels.length ? ' — ' + r.llmModels.length + ' models' : ''}</div>`;
    }
    $('c_testResult').innerHTML = h;
  } catch (e) { $('c_testResult').innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; }
}
async function provisionSchema() {
  const body = editorBody();
  if (!body.schema) { toast('Enter a schema name first.', true); return; }
  const req = {
    host: body.host, port: body.port, username: body.username,
    password: $('c_password').value, schema: body.schema, useTLS: body.useTLS,
    certModeRaw: body.certModeRaw, fingerprint: body.fingerprint,
    minRSAKeySizeBits: body.minRSAKeySizeBits,
    buildTransitions: $('c_provisionBuildMat').checked,
  };
  const out = $('c_provisionResult');
  out.textContent = 'Creating…'; out.style.color = '';
  try {
    const r = await api('/api/connections/provision-schema', { method: 'POST', body: JSON.stringify(req) });
    if (r.ok) {
      out.style.color = 'var(--green)';
      out.textContent = 'Created: ' + (r.created || []).join(', ') +
        (r.materialization ? (r.materialization.ok
          ? ` · transitions built (${Number(r.materialization.rows || 0).toLocaleString()} pairs)`
          : ` · transitions build failed: ${r.materialization.error || 'error'}`) : '');
    } else {
      out.style.color = 'var(--red)';
      out.textContent = r.error || 'Could not create the schema.';
    }
  } catch (e) {
    out.style.color = 'var(--red)';
    out.textContent = e.message;
  }
}

async function rebuildTransitions() {
  const id = $('c_id').value;
  if (!id) { toast('Save the connection first.', true); return; }
  const out = $('c_matResult');
  out.textContent = 'Rebuilding… (this runs the pairing once and may take a while)';
  out.style.color = '';
  try {
    const r = await api('/api/connections/' + encodeURIComponent(id) + '/rebuild-transitions', { method: 'POST' });
    if (r.ok) {
      out.style.color = 'var(--green)';
      out.textContent = `Built ${Number(r.rows || 0).toLocaleString()} pairs.`;
    } else {
      out.style.color = 'var(--red)';
      out.textContent = r.error || 'Rebuild failed.';
    }
    await loadConnections();
    const fresh = CONNS.find(x => x.id === id);
    if (fresh) renderMatStatus(fresh);
  } catch (e) { out.style.color = 'var(--red)'; out.textContent = e.message; }
}

// The plaintext token for the connection currently open in the editor, kept only
// while it is visible after generation; the curl example uses it verbatim until
// then, then reverts to a <token> placeholder.
let LAST_TOKEN = '';

function renderTokenStatus(isSet) {
  const saved = !!$('c_id').value;
  $('rtStatus').textContent = !saved ? 'save the connection first'
    : isSet ? 'a token is set for this connection' : 'no token set';
  $('rtRevokeBtn').style.display = (saved && isSet) ? 'inline-flex' : 'none';
}

function renderCurl() {
  const connId = $('c_id').value || '<connection-id>';
  const token = LAST_TOKEN ? `<span class="tok">${esc(LAST_TOKEN)}</span>` : '&lt;token&gt;';
  // -k skips the TLS certificate check (handy with the self-signed admin cert).
  $('api_curl').innerHTML =
    'curl -k -X POST \\\n' +
    `  -H "Authorization: Bearer ${token}" \\\n` +
    `  "${esc(window.location.origin)}/api/connections/${esc(connId)}/rebuild-transitions"`;
}

function copyCurl() {
  const text = $('api_curl').textContent;  // plaintext incl. the real token if shown
  navigator.clipboard.writeText(text).then(
    () => toast('curl command copied'),
    () => toast('Copy failed', true),
  );
}

async function generateRebuildToken() {
  const id = $('c_id').value;
  if (!id) { toast('Save the connection first.', true); return; }
  if (!confirm('Generate a new token for this connection? Any existing token stops working.')) return;
  try {
    const r = await api('/api/connections/' + encodeURIComponent(id) + '/rebuild-token', { method: 'POST' });
    LAST_TOKEN = r.token;
    $('rtValue').innerHTML = 'New token (copy it now — it is not shown again):<br>' +
      `<code style="user-select:all; word-break:break-all">${esc(r.token)}</code>`;
    renderTokenStatus(true);
    renderCurl();
    toast('Rebuild token generated');
  } catch (e) { toast(e.message, true); }
}
async function revokeRebuildToken() {
  const id = $('c_id').value;
  if (!id) return;
  if (!confirm("Revoke this connection's token? A scheduler using it will stop working.")) return;
  try {
    await api('/api/connections/' + encodeURIComponent(id) + '/rebuild-token', { method: 'DELETE' });
    LAST_TOKEN = '';
    $('rtValue').textContent = '';
    renderTokenStatus(false);
    renderCurl();
    toast('Rebuild token revoked');
  } catch (e) { toast(e.message, true); }
}

// ── Passkeys (App Control) ──────────────────────────────────────────────────
// The signed-in admin manages their own passkeys here. A passkey registered on
// this host works for both this admin panel and the main app (same RP ID).
function pkB2a(s) { var pad = s.length % 4 === 0 ? '' : '='.repeat(4 - (s.length % 4));
  var bin = atob(s.replace(/-/g, '+').replace(/_/g, '/') + pad), a = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a.buffer; }
function pkB2b(b) { var a = new Uint8Array(b), s = '';
  for (var i = 0; i < a.length; i++) s += String.fromCharCode(a[i]);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }

function pkDomainValid() {
  // WebAuthn rejects bare IP addresses and single-label hosts as the RP ID.
  var h = location.hostname;
  if (h === 'localhost') return true;
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(h)) return false;
  if (h.indexOf(':') >= 0 || h.charAt(0) === '[') return false;
  return h.indexOf('.') >= 0;
}
async function loadAdminPasskeys() {
  const note = $('pkAdminNote'), list = $('pkAdminList'), add = $('pkAdminAdd');
  if (!window.PublicKeyCredential || !navigator.credentials) {
    note.className = 'banner warn';
    note.textContent = 'This browser does not support passkeys.';
    add.style.display = 'none'; list.innerHTML = ''; return;
  }
  if (!pkDomainValid()) {
    note.className = 'banner warn';
    note.textContent = 'Passkeys need a hostname, not an IP address. Reach this panel by its '
      + 'name over HTTPS — e.g. its “.local” name — instead of its IP to add or use one.';
    add.style.display = 'none'; list.innerHTML = ''; return;
  }
  try {
    const r = await api('/api/passkey/credentials');
    if (!r.passkeyAllowed) {
      note.className = 'banner warn';
      note.textContent = 'Passkeys are not enabled for your account — enable them in the Users tab first.';
      add.style.display = 'none'; list.innerHTML = ''; return;
    }
    note.className = 'banner info';
    note.textContent = 'Passkeys are enabled for your account.';
    add.style.display = 'flex';
    const creds = r.credentials || [];
    if (!creds.length) {
      list.innerHTML = '<div class="muted" style="font-size:13px">No passkeys registered yet.</div>'; return;
    }
    list.innerHTML = creds.map(c =>
      `<div class="row" style="gap:8px; align-items:center; padding:8px 10px; border-radius:8px; background:var(--l-fill)">
         <span aria-hidden>🔑</span>
         <div class="col" style="gap:0; min-width:0; line-height:1.2">
           <span style="font-size:13px">${esc(c.name || 'Passkey')}</span>
           <span class="muted" style="font-size:11px">Added ${esc(new Date(c.createdAt).toLocaleString())}</span>
         </div>
         <span class="spacer"></span>
         <button class="btn small" data-pk="${esc(c.id)}" onclick="removeAdminPasskey(this.dataset.pk)">Remove</button>
       </div>`).join('');
  } catch (e) {
    note.className = 'banner warn'; note.textContent = 'Could not load passkeys: ' + e.message;
    add.style.display = 'none';
  }
}

async function addAdminPasskey() {
  const out = $('pkAdminResult'); out.textContent = '';
  if (!window.PublicKeyCredential || !navigator.credentials) {
    out.style.color = 'var(--red)'; out.textContent = 'This browser does not support passkeys.'; return;
  }
  try {
    const opt = await api('/api/passkey/register/begin', { method: 'POST' });
    const publicKey = Object.assign({}, opt, {
      challenge: pkB2a(opt.challenge),
      user: Object.assign({}, opt.user, { id: pkB2a(opt.user.id) }),
      excludeCredentials: (opt.excludeCredentials || []).map(c => Object.assign({}, c, { id: pkB2a(c.id) })),
    });
    const cred = await navigator.credentials.create({ publicKey });
    if (!cred) throw new Error('cancelled');
    const r = cred.response;
    const transports = (typeof r.getTransports === 'function' ? r.getTransports() : []);
    const payload = {
      credential: {
        id: cred.id, rawId: pkB2b(cred.rawId), type: cred.type,
        response: { clientDataJSON: pkB2b(r.clientDataJSON), attestationObject: pkB2b(r.attestationObject), transports: transports },
        clientExtensionResults: cred.getClientExtensionResults(),
        authenticatorAttachment: cred.authenticatorAttachment || undefined,
      },
      name: ($('pkAdminName').value || '').trim() || 'Passkey',
      transports: transports.join(','),
    };
    await api('/api/passkey/register/finish', { method: 'POST', body: JSON.stringify(payload) });
    $('pkAdminName').value = '';
    toast('Passkey added');
    await loadAdminPasskeys();
  } catch (e) {
    if (e && (e.name === 'NotAllowedError' || e.name === 'AbortError')) return;  // user cancelled
    out.style.color = 'var(--red)';
    if (e && e.name === 'InvalidStateError') {
      out.textContent = 'A passkey for this account already exists on this device. If it isn’t '
        + 'listed above, remove it in your device’s passkey settings and try again.';
    } else if (e && e.name === 'SecurityError') {
      out.textContent = 'Passkeys need a hostname, not an IP address — reach this panel by its name over HTTPS.';
    } else {
      out.textContent = e.message || 'Could not add the passkey.';
    }
  }
}

async function removeAdminPasskey(id) {
  try {
    await api('/api/passkey/credentials/' + encodeURIComponent(id), { method: 'DELETE' });
    toast('Passkey removed'); await loadAdminPasskeys();
  } catch (e) { toast(e.message, true); }
}

// ── Two-factor (App Control) ────────────────────────────────────────────────
// The signed-in admin sets up TOTP here. The same secret protects the app and
// this admin panel (both check the one stored secret at sign-in).
function renderRecoveryCodes(codes) {
  const box = $('mfaRecovery');
  box.style.display = 'block';
  box.innerHTML =
    '<div class="banner warn"><strong>Save your recovery codes.</strong> Each works once if you '
    + 'lose your authenticator; they won’t be shown again.</div>'
    + '<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-family:monospace; '
    + 'font-size:13px; margin-top:8px">'
    + codes.map(c => `<span>${esc(c)}</span>`).join('') + '</div>'
    + '<div class="row" style="gap:8px; margin-top:8px">'
    + '<button class="btn small" onclick="copyRecovery()">Copy codes</button>'
    + '<button class="btn small" onclick="$(\'mfaRecovery\').style.display=\'none\'">Done</button></div>';
  box.dataset.codes = codes.join('\n');
}
function copyRecovery() {
  navigator.clipboard.writeText($('mfaRecovery').dataset.codes || '').then(
    () => toast('Recovery codes copied'), () => toast('Copy failed', true));
}
async function loadAdminMfa() {
  const note = $('mfaAdminNote'), actions = $('mfaAdminActions');
  try {
    const s = await api('/api/mfa/status');
    if (!s.mfaAllowed) {
      note.className = 'banner warn';
      note.textContent = 'Two-factor is not enabled for your account — enable it in the Users tab first.';
      actions.style.display = 'none'; return;
    }
    actions.style.display = 'flex';
    if (s.enabled) {
      note.className = 'banner ok';
      note.textContent = `Two-factor is on. ${s.recoveryRemaining} recovery code`
        + `${s.recoveryRemaining === 1 ? '' : 's'} left.`;
      $('mfaSetupBtn').style.display = 'none';
      $('mfaRegenBtn').style.display = 'inline-flex';
      $('mfaOffBtn').style.display = 'inline-flex';
    } else {
      note.className = 'banner info';
      note.textContent = 'Two-factor is off for your account.';
      $('mfaSetupBtn').style.display = 'inline-flex';
      $('mfaRegenBtn').style.display = 'none';
      $('mfaOffBtn').style.display = 'none';
    }
  } catch (e) {
    note.className = 'banner warn'; note.textContent = 'Could not load two-factor: ' + e.message;
    actions.style.display = 'none';
  }
}
async function beginAdminMfa() {
  try {
    const s = await api('/api/mfa/setup/begin', { method: 'POST' });
    $('mfaQr').innerHTML = s.qrSvg;      // SVG from our own server
    $('mfaSecret').textContent = s.secret;
    $('mfaCode').value = '';
    $('mfaAdminSetup').style.display = 'block';
    $('mfaAdminActions').style.display = 'none';
  } catch (e) { toast(e.message, true); }
}
function cancelAdminMfa() {
  $('mfaAdminSetup').style.display = 'none';
  $('mfaAdminActions').style.display = 'flex';
}
async function confirmAdminMfa() {
  const out = $('mfaAdminResult'); out.textContent = '';
  try {
    const r = await api('/api/mfa/setup/finish', { method: 'POST',
      body: JSON.stringify({ code: ($('mfaCode').value || '').trim() }) });
    $('mfaAdminSetup').style.display = 'none';
    toast('Two-factor enabled');
    renderRecoveryCodes(r.recoveryCodes || []);
    await loadAdminMfa();
  } catch (e) { out.style.color = 'var(--red)'; out.textContent = e.message; }
}
async function regenAdminMfa() {
  try {
    const r = await api('/api/mfa/recovery/regenerate', { method: 'POST' });
    toast('Recovery codes regenerated');
    renderRecoveryCodes(r.recoveryCodes || []);
    await loadAdminMfa();
  } catch (e) { toast(e.message, true); }
}
async function disableAdminMfa() {
  // Re-authenticate the downgrade: the current code is required to turn 2FA off.
  const code = prompt('Enter your current authentication code (or a recovery code) to turn off two-factor:');
  if (code === null) return;  // cancelled
  try {
    await api('/api/mfa/disable', { method: 'POST', body: JSON.stringify({ code: (code || '').trim() }) });
    $('mfaRecovery').style.display = 'none';
    toast('Two-factor turned off');
    await loadAdminMfa();
  } catch (e) { toast(e.message, true); }
}

// Passkeys + two-factor status load lazily when the Profile overlay is opened.
loadSession().then(loadTls).then(loadUsers).catch(() => {});

// ── Administration help overlay ─────────────────────────────────────────────
// Mirrors the "Administration" group in the main app's Help, so the same guidance
// is available here on the admin interface.
const ADMIN_HELP = [
  { id: 'interface', icon: '⚙︎', title: 'Admin Interface', html: `
    <h2>Admin Interface</h2>
    <p>This administration interface runs on its own port (8090 by default) and is where all security and access is configured. It has its own sign-in and admits administrators only.</p>
    <p>On first run it seeds a local administrator (Administrator / Administrator) and prompts you to change the password. Local admin accounts always work as a break-glass route.</p>
    <p><strong>Timezone.</strong> App Control has a display-timezone setting that governs every server-side timestamp &mdash; the log viewer and exported logs, backup times and the backup schedule (so &ldquo;daily at 02:00&rdquo; fires at 02:00 in the chosen zone). Timestamps rendered client-side in this panel follow it too. Leave it &ldquo;Server local&rdquo; to use the server's own clock. The main app always shows each user their own browser's local time.</p>
    <div class="note">Tabs: App Control, TLS / SSL, Users, Database Connections, Directory (LDAP), Logging, Backup and Customize.</div>` },
  { id: 'tls', icon: '🔒', title: 'TLS / SSL', html: `
    <h2>TLS / SSL</h2>
    <p>Choose how connections are accepted: Off (HTTP only), Optional (HTTP and HTTPS) or Required (HTTPS only). Generate a self-signed certificate or upload your own PEM cert and key, then mark one active.</p>
    <p>The app and this admin interface follow the same mode and share the active certificate. Changes take effect on restart (App Control &rarr; Restart app server); if a mode needs a certificate but none is active, each server falls back to HTTP so nothing is left unreachable.</p>
    <div class="note warn">Keep the active certificate valid &mdash; an expired certificate makes HTTPS clients refuse to connect.</div>` },
  { id: 'users', icon: '👤', title: 'Users & Sign-in', html: `
    <h2>Users &amp; Sign-in</h2>
    <p>Create local users, enable/disable access, grant or revoke the admin role, and reset passwords. Only enabled users can sign in. The <strong>Require sign-in</strong> toggle turns the login gate on or off (on by default) &mdash; with it off there is no user identity, so per-user settings and filter presets share one profile.</p>
    <p><strong>Failed sign-in lockout</strong> disables an account after N wrong passwords (0 = off); unlock it in the Users tab, or restart with PMW_RESET_LOCKOUTS=1. <strong>Power</strong> users manage their own connections and get the advanced-analysis views (Conformance Check, Happy Path, Simulation).</p>
    <p><strong>Developer.</strong> The <em>Developer</em> column grants the <span class="pill dev">dev</span> role, which admits the user to the <strong>Integration console</strong> (the data-source configuration surface — see the <strong>Integration</strong> tab). Admins may enter it too; power users may not. It is an additional access grant, independent of the power/admin level.</p>
    <p><strong>Passkeys (WebAuthn).</strong> The <em>Passkey</em> column lets each user sign in with Touch&nbsp;ID / Windows&nbsp;Hello / a security key as an alternative to their password (which always stays as a fallback); the header checkbox toggles it for everyone. Local and directory users alike can be allowed. A passkey registered on this host works for both the app and this admin panel. Admins enrol their own device in <strong>App Control &rarr; Passkeys</strong>; app users do so from the main app. Turning the permission off blocks passkey sign-in immediately.</p>
    <p><strong>Two-factor (TOTP).</strong> The <em>2FA</em> column (with an all-users master checkbox) requires a one-time authenticator-app code after the password. Enabling it makes 2FA <strong>mandatory</strong> for that user: if they haven&rsquo;t configured it, their next sign-in (app or this admin panel) stops after the password and forces them to set up an authenticator before they get in &mdash; they can&rsquo;t bypass it by not enrolling. Afterwards each sign-in asks for the current code (or a recovery code); a passkey sign-in skips it. Users set up from <strong>🔒 Two-factor</strong> in the app; admins from <strong>App Control &rarr; Two-factor</strong> or at the forced login step. Turning 2FA off requires the current code (so a hijacked session can&rsquo;t strip it). The secret is stored encrypted and recovery codes only as hashes &mdash; if a user loses their authenticator, untick 2FA for them so they can sign in with their password and re-enrol.</p>
    <div class="note warn">Passkeys need a secure context (HTTPS, or localhost). Off localhost, run with TLS Optional/Required. For split app/admin sub-domains set PMW_PASSKEY_RP_ID to the shared parent domain and list origins in PMW_PASSKEY_ORIGINS.</div>
    <div class="note warn">Passkeys also need a real hostname &mdash; WebAuthn rejects bare IP addresses. Reaching the app/admin by IP (e.g. a tablet on the LAN) blocks enrolment with &ldquo;the effective domain is not a valid domain&rdquo;; use the host&rsquo;s name (its &ldquo;.local&rdquo; name or a DNS entry) and a matching certificate. The passkey controls are hidden when an IP is detected.</div>` },
  { id: 'connections', icon: '🗄️', title: 'Database Connections', html: `
    <h2>Database Connections</h2>
    <p>Define each connection (Exasol host, port, user, password, schema, TLS, and an optional OpenAI-compatible LLM server) and assign it to users; each user sees only the connections assigned to them. Use Test connection to verify the database and LLM before saving; a blank password/key keeps the stored value.</p>
    <p>&ldquo;Create schema &amp; tables&rdquo; provisions the process-mining schema and tables (PROJECTS, JOURNEYS, STEPS, METAS, NOTES) if missing.</p>
    <div class="note warn">Provisioning needs a DB account with CREATE SCHEMA / CREATE TABLE rights &mdash; only the database administrator can grant those.</div>` },
  { id: 'api', icon: '🔌', title: 'Rebuild from a script (API)', html: `
    <h2>Rebuild from a script (API)</h2>
    <p>Each connection can issue its own bearer token so an external caller (a cron job or ETL step) can trigger that connection&rsquo;s pre-materialized transitions rebuild without an admin login. Open the connection in <strong>Database Connections</strong>, expand &ldquo;Rebuild from a script (API)&rdquo;, and Generate / rotate or revoke the token there &mdash; it is shown <strong>once</strong> (copy it then); only its hash is stored, and the token is scoped to that connection only.</p>
    <p>Call <code>POST /api/connections/&lt;id&gt;/rebuild-transitions</code> with header <code>Authorization: Bearer &lt;token&gt;</code>. That section shows a copy-able <code>curl</code> example &mdash; pre-filled with your real token while it is still visible, and using <code>-k</code> to skip the TLS certificate check. Token-triggered rebuilds are rate-limited per connection and never overlap. Run it right after each load of <code>JOURNEYS</code>.</p>` },
  { id: 'directory', icon: '📇', title: 'Directory (LDAP)', html: `
    <h2>Directory (LDAP)</h2>
    <p>When enabled, the main-app login also accepts directory accounts via search + bind. Set the server URI, service-account bind DN/password, base DN, user filter and attributes. Test server connection checks the server alone; Test a user login also resolves and signs in an account.</p>
    <p>Directory users are created locally on first sign-in as plain, enabled accounts. The admin interface stays local-only unless you tick &ldquo;Also allow directory sign-in to this admin interface&rdquo; &mdash; and even then only after a directory account is promoted to admin.</p>
    <div class="note">Admin is never granted from the directory; a local admin must promote the user.</div>` },
  { id: 'logging', icon: '🧾', title: 'Logging', html: `
    <h2>Logging</h2>
    <p>A shared, structured log written by all three servers. Each entry records a timestamp, severity, client IP, user, operation and message. Severity is a cumulative ladder &mdash; INFO, USAGE, WARN, ERROR, DEBUG; pick the maximum level to record. Filter by severity, client IP or operation, search by regular expression, page through, and Download or Clear.</p>
    <p>Audited actions carry an operation tag: sign-in/out (login/logout), LDAP tests and config (ldap), certificate actions (tls), connection actions and connection/LLM tests (connection/llm-test), backup export/inspect/restore (backup) and login-page customization (customize). Deletions are logged as warnings.</p>
    <div class="note">A new log file starts once the live log passes the configured size; rotated files are saved under data/logs/.</div>` },
  { id: 'backup', icon: '💾', title: 'Backup & Restore', html: `
    <h2>Backup &amp; Restore</h2>
    <p>Export everything except the event data itself &mdash; connections, filter presets, node layouts, norms, happy paths, LLM prompts and app preferences &mdash; as one JSON file, and restore it again. Tick the boxes to include usernames, connection passwords and LLM API keys, and optionally protect the file with an AES-256-GCM password. Restore inspects the file and shows a summary before you pick which categories to apply.</p>
    <p><strong>Automatic backups</strong> run an encrypted backup on a schedule while this server is up. Enable them, build the schedule like a crontab (a frequency + time, or a custom five-field cron expression, with a live preview), set the encryption password (stored encrypted so it can run unattended), and choose how many files to keep. Files are written under <code>data/backups/</code>; use &ldquo;Run backup now&rdquo; to test.</p>
    <div class="note warn">Including secrets without an encryption password writes them in plain text &mdash; always set a password when the backup contains secrets. The automatic-backup password is stored (encrypted) on the server; keep a copy safe, as backups can only be restored with it.</div>` },
  { id: 'customize', icon: '🎨', title: 'Customize', html: `
    <h2>Customize</h2>
    <p>Set the login-page background for both sign-in pages (the app and this admin interface): keep the default theme colour, choose a solid colour, or upload a background image (PNG, JPEG, GIF, WebP or SVG). Large photos are scaled down in the browser before upload, so even a multi-megapixel picture works; an SVG is kept as-is so it can stay animated. A live preview shows the result before you save, and the choice applies to new sign-ins immediately.</p>
    <p>Over a background image the login panel turns semi-transparent so the image shows through while the text and fields stay legible.</p>` },
  { id: 'license', icon: '🔑', title: 'License & Demo Mode', html: `
    <h2>License &amp; Demo Mode</h2>
    <p>The application requires a valid license &mdash; upload it in App Control &rarr; License. Without one, the app runs in Demo Mode for a one-time grace period, then the compute backend stops until a license is applied. Uploading a valid license during the grace period cancels the shutdown.</p>
    <div class="note">The admin interface keeps working even when the backend has stopped, so you can always apply a license here.</div>` },
];
let _helpTopic = ADMIN_HELP[0].id;

function renderHelp() {
  const nav = $('helpNav'), content = $('helpContent');
  if (!nav || !content) return;
  nav.innerHTML = '';
  for (const t of ADMIN_HELP) {
    const b = document.createElement('button');
    b.className = t.id === _helpTopic ? 'sel' : '';
    b.innerHTML = '<span aria-hidden style="width:18px;display:inline-block">' + t.icon + '</span>' + esc(t.title);
    b.onclick = () => { _helpTopic = t.id; renderHelp(); };
    nav.appendChild(b);
  }
  const topic = ADMIN_HELP.find(t => t.id === _helpTopic) || ADMIN_HELP[0];
  content.innerHTML = topic.html;
  content.scrollTop = 0;
}
function openHelp() { renderHelp(); $('helpOv').hidden = false; }
function closeHelp() { $('helpOv').hidden = true; }
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('helpOv').hidden) closeHelp(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('profOv').hidden) closeProfile(); });
"""
