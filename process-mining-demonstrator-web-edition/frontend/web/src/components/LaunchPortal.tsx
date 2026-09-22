/** The end-user launch page (served at /home). Shown after the standard sign-in, it is
 *  the workbench-side sibling of the static suite launcher: the same dark, glassy look and
 *  the admin-configured background, but its tiles are the **processes available to the
 *  signed-in user, grouped by connection**. Clicking a tile connects to that connection,
 *  opens that project and drops the user straight onto its process map. */

import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { loginBackground, type LoginAppearance } from '../loginAppearance'
import { useStore } from '../store'
import type { PortalConnection, PortalProcess } from '../types'

const FALLBACK_BG =
  '#0d1220 radial-gradient(1100px 600px at 15% -10%, rgba(58,155,255,.28), transparent 60%),' +
  ' radial-gradient(900px 550px at 90% 0%, rgba(107,92,240,.30), transparent 60%),' +
  ' radial-gradient(800px 700px at 50% 110%, rgba(20,184,166,.16), transparent 60%)'

const STYLE = `
.pl-root{position:fixed;inset:0;overflow:auto;color:#eaf0fa;
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.pl-veil{position:fixed;inset:0;background:rgba(8,12,22,.42);backdrop-filter:blur(2px);
  -webkit-backdrop-filter:blur(2px);pointer-events:none}
.pl-stage{position:relative;z-index:1;min-height:100%;display:flex;flex-direction:column;
  align-items:center;padding:40px 20px 64px}
.pl-top{width:min(1080px,100%);display:flex;justify-content:flex-end;gap:10px;margin-bottom:8px}
.pl-top button{background:rgba(255,255,255,.08);color:#eaf0fa;border:1px solid rgba(255,255,255,.16);
  border-radius:999px;padding:7px 14px;font-size:13px;font-weight:600;cursor:pointer;
  transition:background .2s,border-color .2s}
.pl-top button:hover{background:rgba(255,255,255,.16);border-color:rgba(255,255,255,.32)}
.pl-head{display:flex;flex-direction:column;align-items:center;gap:8px;margin-bottom:30px;text-align:center}
.pl-mark{width:54px;height:54px;filter:drop-shadow(0 8px 22px rgba(58,155,255,.45))}
.pl-h1{margin:0;font-size:27px;font-weight:800;letter-spacing:-.01em;
  background:linear-gradient(100deg,#fff 20%,#b7cdf7 55%,#c9bfff 85%);
  -webkit-background-clip:text;background-clip:text;color:transparent}
.pl-sub{margin:0;color:rgba(234,240,250,.75);font-size:14px}
.pl-group{width:min(1080px,100%);margin-top:26px}
.pl-ghead{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.pl-ghead .pl-line{flex:1;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.22),transparent)}
.pl-gname{font-size:13.5px;font-weight:750;letter-spacing:.02em}
.pl-gschema{font:600 11.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:rgba(234,240,250,.6);
  padding:3px 9px;border-radius:999px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.05)}
.pl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(216px,1fr));gap:16px}
.pl-tile{position:relative;display:flex;flex-direction:column;gap:10px;padding:18px 18px 16px;
  border-radius:18px;text-align:left;cursor:pointer;color:#eaf0fa;
  background:rgba(18,24,38,.62);border:1px solid rgba(255,255,255,.14);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  box-shadow:0 10px 18px rgba(4,8,18,.4),0 30px 60px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.1);
  transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease}
.pl-tile:hover{transform:translateY(-8px);border-color:rgba(255,255,255,.32);
  box-shadow:0 14px 24px rgba(4,8,18,.42),0 44px 90px rgba(0,0,0,.66),0 0 40px rgba(58,155,255,.34)}
.pl-tico{width:44px;height:44px;border-radius:13px;display:grid;place-items:center;
  background:linear-gradient(135deg,#3a9bff,#6b5cf0);box-shadow:inset 0 1px 0 rgba(255,255,255,.3)}
.pl-tico svg{width:24px;height:24px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.pl-tname{font-size:15.5px;font-weight:700;letter-spacing:-.01em;line-height:1.25;word-break:break-word}
.pl-tmeta{font-size:12px;color:rgba(234,240,250,.72)}
.pl-tstamp{font-size:11px;color:rgba(234,240,250,.5)}
.pl-note{color:rgba(234,240,250,.7);font-size:13px;padding:6px 2px}
.pl-warn{color:#ffb4a8;font-size:12.5px;padding:8px 2px}
.pl-empty{margin-top:60px;color:rgba(234,240,250,.75);font-size:15px;text-align:center;max-width:520px}
.pl-foot{margin-top:44px;color:rgba(234,240,250,.5);font-size:12px;text-align:center}
.pl-docs{width:min(1080px,100%);margin-top:52px}
.pl-docs-head{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.pl-docs-head .pl-line{flex:1;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.22),transparent)}
.pl-docs-head .pl-label{font-size:12.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:rgba(234,240,250,.75)}
.pl-dgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}
@media (max-width:720px){.pl-dgrid{grid-template-columns:1fr}}
.pl-dgroup{border:1px solid rgba(255,255,255,.12);border-radius:14px;background:rgba(18,24,38,.42);
  overflow:hidden}
.pl-dsum{list-style:none;cursor:pointer;display:flex;align-items:center;gap:10px;padding:13px 16px;
  font-size:14px;font-weight:700;color:#eaf0fa;user-select:none}
.pl-dsum::-webkit-details-marker{display:none}
.pl-dsum:hover{background:rgba(255,255,255,.05)}
.pl-dsum .pl-chev{transition:transform .18s ease;color:rgba(234,240,250,.6);font-size:12px}
.pl-dgroup[open] .pl-chev{transform:rotate(90deg)}
.pl-dcount{margin-left:auto;font-size:11px;font-weight:800;letter-spacing:.04em;color:rgba(234,240,250,.6);
  border:1px solid rgba(255,255,255,.14);border-radius:999px;padding:2px 8px;background:rgba(255,255,255,.05)}
.pl-dbody{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;padding:4px 14px 16px}
.pl-guide{display:flex;align-items:center;gap:11px;padding:11px 13px;border-radius:11px;text-decoration:none;
  color:#eaf0fa;background:rgba(18,24,38,.5);border:1px solid rgba(255,255,255,.12);
  transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease}
.pl-guide:hover{transform:translateY(-4px);border-color:rgba(255,255,255,.3);box-shadow:0 12px 26px rgba(0,0,0,.4)}
.pl-gtile{flex:0 0 auto;width:34px;height:34px;border-radius:10px;display:grid;place-items:center;
  background:linear-gradient(135deg,#2e3d63,#22304f);box-shadow:inset 0 1px 0 rgba(255,255,255,.2)}
.pl-gtile svg{width:18px;height:18px;fill:none;stroke:#9db8ef;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.pl-guide.pl-pdf .pl-gtile{background:linear-gradient(135deg,#e2574c,#b3372c)}
.pl-guide.pl-pdf .pl-gtile svg{stroke:#fff}
.pl-gtitle{font-size:13px;font-weight:600;line-height:1.3}
.pl-gbadge{margin-left:auto;flex:0 0 auto;font-size:9.5px;font-weight:800;letter-spacing:.06em;color:#ff9d94;
  border:1px solid rgba(226,87,76,.5);border-radius:5px;padding:2px 5px;background:rgba(226,87,76,.12)}
`

const FLOW_ICON = (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <rect x="3" y="4" width="7" height="5" rx="1.4" />
    <rect x="14" y="15" width="7" height="5" rx="1.4" />
    <path d="M10 6.5h4a3 3 0 0 1 3 3v5.5" />
    <circle cx="6.5" cy="17.5" r="2.3" />
    <path d="M6.5 9v6" />
  </svg>
)

const BOOK_ICON = (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15.5H6.5A2.5 2.5 0 0 0 4 21z" />
    <path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20" /><path d="M9 7.5h7M9 11h7" />
  </svg>
)
const DOC_ICON = (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /><path d="M8.5 13.5h7M8.5 16.5h5" />
  </svg>
)

interface Guide {
  file: string
  title: string
  type: string
}

// Doc groups keyed by the leading number's DECADE (the tens of the "NN-" filename prefix),
// mirroring how the guides are numbered (10s install, 20s admin, 30s integration, …). An
// unknown decade falls back to a generic label; the PDF manual(s) get their own group.
const DECADE_LABEL: Record<number, string> = {
  0: 'Introduction',
  1: 'Installation',
  2: 'Administration',
  3: 'Integration & Import',
  4: 'Actions',
  5: 'Work-Bench & Analysis',
  8: 'Concepts Explained',
}

interface DocGroup {
  key: string
  label: string
  order: number
  guides: Guide[]
}

/** Group guides by the decade of their leading "NN-" number; PDFs in a trailing group. */
function groupGuides(guides: Guide[]): DocGroup[] {
  const groups = new Map<string, DocGroup>()
  for (const g of guides) {
    const isPdf = g.type === 'pdf' || /\.pdf$/i.test(g.file)
    const m = /^(\d+)-/.exec(g.file)
    let key: string, label: string, order: number
    if (isPdf) {
      key = 'pdf'
      label = 'Full Manual'
      order = 999
    } else if (m) {
      const decade = Math.floor(parseInt(m[1], 10) / 10)
      key = `d${decade}`
      label = DECADE_LABEL[decade] ?? `Guides ${decade}0–${decade}9`
      order = decade
    } else {
      key = 'other'
      label = 'More guides'
      order = 500
    }
    if (!groups.has(key)) groups.set(key, { key, label, order, guides: [] })
    groups.get(key)!.guides.push(g)
  }
  return [...groups.values()].sort((a, b) => a.order - b.order)
}

/** Open a URL in a NEW tab on a plain left-click, robust across browsers. Opens explicitly
 *  during the click gesture (Safari can swallow a plain target="_blank"); a modified click
 *  falls through to the browser, and a blocked pop-up falls back to same-tab so it still
 *  opens. No "noopener" — with it window.open returns null on success, which would double-open. */
function openInNewTab(e: React.MouseEvent, url: string): void {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
  e.preventDefault()
  const w = window.open(url, '_blank')
  if (!w) window.location.assign(url)
}

function relAge(iso: string | null): string | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  const days = Math.floor((Date.now() - t) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

export function LaunchPortal({
  onOpen,
  onWorkbench,
}: {
  onOpen: (connId: string, project: PortalProcess) => void
  onWorkbench: () => void
}) {
  const logout = useStore((s) => s.logout)
  const authUser = useStore((s) => s.authUser)
  const [appearance, setAppearance] = useState<LoginAppearance | null>(null)
  const [data, setData] = useState<{ connections: PortalConnection[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openingId, setOpeningId] = useState<number | null>(null)
  const [guides, setGuides] = useState<Guide[]>([])

  useEffect(() => {
    let cancelled = false
    void api.loginAppearance().then((a) => !cancelled && setAppearance(a)).catch(() => {})
    void api
      .portal()
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
    // The training guides are best-effort: if the index can't be read, hide the section.
    void api.guides().then((g) => !cancelled && Array.isArray(g) && setGuides(g)).catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const docGroups = useMemo(() => groupGuides(guides), [guides])

  const bg = useMemo(
    () => (appearance ? loginBackground(appearance) : FALLBACK_BG),
    [appearance],
  )
  const groups = data?.connections ?? []
  const anyProcess = groups.some((g) => g.projects.length > 0)

  const open = async (connId: string, p: PortalProcess) => {
    if (openingId != null) return
    setOpeningId(p.projectId)
    try {
      await onOpen(connId, p)
    } finally {
      setOpeningId(null)
    }
  }

  return (
    <div className="pl-root" style={{ background: bg }}>
      <style>{STYLE}</style>
      {appearance?.type === 'image' && <div className="pl-veil" />}
      <div className="pl-stage">
        <div className="pl-top">
          <button onClick={onWorkbench} title="Open the full Work-Bench">Work-Bench ↗</button>
          <button onClick={() => void logout()} title="Sign out">Sign out</button>
        </div>

        <div className="pl-head">
          <svg className="pl-mark" viewBox="0 0 48 48" aria-hidden="true">
            <defs>
              <linearGradient id="plbg" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#3a9bff" />
                <stop offset="1" stopColor="#6b5cf0" />
              </linearGradient>
            </defs>
            <rect x="2" y="2" width="44" height="44" rx="12" fill="url(#plbg)" />
            <path d="M15 16 L33 16 L24 34 Z" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" opacity="0.9" />
            <g fill="#fff"><circle cx="15" cy="16" r="4.6" /><circle cx="33" cy="16" r="4.6" /><circle cx="24" cy="34" r="4.6" /></g>
          </svg>
          <h1 className="pl-h1">Your Processes</h1>
          <p className="pl-sub">
            {authUser ? `Signed in as ${authUser} — ` : ''}pick a process to open its map.
          </p>
          {appearance?.version && <p className="pl-sub" style={{ opacity: 0.7 }}>{appearance.version}</p>}
        </div>

        {error && <div className="pl-warn">Couldn't load your processes: {error}</div>}

        {!data && !error && <div className="pl-note">Loading your processes…</div>}

        {data && !anyProcess && groups.length === 0 && (
          <div className="pl-empty">
            No connections are assigned to you yet. Ask an administrator to assign one, or use
            the Work-Bench once you have access.
          </div>
        )}
        {data && !anyProcess && groups.length > 0 && (
          <div className="pl-empty">
            No processes found in your connections yet. Once data is loaded, the projects
            appear here as tiles.
          </div>
        )}

        {groups.map((g) => (
          <section className="pl-group" key={g.id}>
            <div className="pl-ghead">
              <span className="pl-gname">🛢️ {g.name}</span>
              {g.schema && <span className="pl-gschema">{g.schema}</span>}
              <span className="pl-line" />
            </div>
            {g.error ? (
              <div className="pl-warn">⚠ {g.error}</div>
            ) : g.projects.length === 0 ? (
              <div className="pl-note">No processes in this connection yet.</div>
            ) : (
              <div className="pl-grid">
                {g.projects.map((p) => {
                  const age = relAge(p.lastEventAt)
                  return (
                    <button
                      className="pl-tile"
                      key={p.projectId}
                      onClick={() => void open(g.id, p)}
                      disabled={openingId != null}
                      title={`Open ${p.title || p.titleShort}`}
                    >
                      <span className="pl-tico">{FLOW_ICON}</span>
                      <span className="pl-tname">{p.title || p.titleShort || `Project ${p.projectId}`}</span>
                      <span className="pl-tmeta">
                        ▦ {p.events.toLocaleString()} events · {p.journeys.toLocaleString()} journeys
                      </span>
                      {age && <span className="pl-tstamp">🕒 last event {age}</span>}
                      {openingId === p.projectId && <span className="pl-tstamp">opening…</span>}
                    </button>
                  )
                })}
              </div>
            )}
          </section>
        ))}

        {docGroups.length > 0 && (
          <section className="pl-docs">
            <div className="pl-docs-head">
              <span className="pl-line" />
              <span className="pl-label">Training &amp; Documentation</span>
              <span className="pl-line" />
            </div>
            <div className="pl-dgrid">
              {docGroups.map((grp) => (
                <details className="pl-dgroup" key={grp.key}>
                  <summary className="pl-dsum">
                    <span className="pl-chev">▶</span>
                    {grp.label}
                    <span className="pl-dcount">{grp.guides.length}</span>
                  </summary>
                  <div className="pl-dbody">
                    {grp.guides.map((g) => {
                      const isPdf = g.type === 'pdf' || /\.pdf$/i.test(g.file)
                      const url = `/guides/${encodeURIComponent(g.file)}`
                      return (
                        <a
                          className={`pl-guide${isPdf ? ' pl-pdf' : ''}`}
                          key={g.file}
                          href={url}
                          onClick={(e) => openInNewTab(e, url)}
                        >
                          <span className="pl-gtile">{isPdf ? DOC_ICON : BOOK_ICON}</span>
                          <span className="pl-gtitle">
                            {g.title || g.file.replace(/^\d+-/, '').replace(/\.(html|pdf)$/i, '').replace(/-/g, ' ')}
                          </span>
                          {isPdf && <span className="pl-gbadge">PDF</span>}
                        </a>
                      )
                    })}
                  </div>
                </details>
              ))}
            </div>
          </section>
        )}

        <div className="pl-foot">Process Mining Demonstrator · Process Launcher</div>
      </div>
    </div>
  )
}
