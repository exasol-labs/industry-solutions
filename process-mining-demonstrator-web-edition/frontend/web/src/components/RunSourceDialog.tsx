/** Run a File source's extraction: pick the destination connection and a project id,
 *  then push the parsed JOURNEYS events through the abstraction layer. The backend opens
 *  the chosen connection itself with its stored credentials — no need to connect to it in
 *  the main app first. Progress + the result also show in the status panel. */

import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import type { ConnectionProject, Source, SourceCheckpoint } from '../types'
import { Sheet } from './ui'

/** Sentinel for the "create a new project" option — no real project id is empty. */
const NEW_PROJECT = ''

export function RunSourceDialog({
  source,
  onClose,
  onDone,
}: {
  source: Source
  onClose: () => void
  onDone: () => void | Promise<void>
}) {
  const store = useStore()
  const cfg = (source.config ?? {}) as Record<string, unknown>
  const linked = Boolean(cfg.sourceTypeId)

  // Where this source last imported to, remembered server-side by the run endpoint.
  const lastRun = (cfg.lastRun ?? {}) as { connectionId?: string; titleShort?: string }
  const lastConnection = store.connections.some((c) => c.id === lastRun.connectionId)
    ? (lastRun.connectionId as string)
    : '' // dropped: an assignment can be revoked between runs

  // Prefer the destination this source used last; otherwise whatever the main app is
  // connected to. Any assigned connection may be picked — the backend opens it with its
  // stored credentials.
  const [connectionId, setConnectionId] = useState(
    () => lastConnection || store.connection.activeProfileId || store.connections[0]?.id || '',
  )
  const target = store.connections.find((c) => c.id === connectionId)

  // The project is picked from the ones already in that connection's schema, or typed
  // when starting a new one. `picked` empty ⇒ the new-project input is in play.
  const [projects, setProjects] = useState<ConnectionProject[] | null>(null)
  const [projectsError, setProjectsError] = useState<string | null>(null)
  const [picked, setPicked] = useState(NEW_PROJECT)
  const [newProject, setNewProject] = useState('')
  const projectId = picked || newProject
  const existing = projects?.find((p) => p.titleShort === picked)

  // Delta upload: import only what was appended since the last run. Default on — a
  // second run should top the project up, not store the whole file again.
  const [delta, setDelta] = useState(true)
  const [checkpoint, setCheckpoint] = useState<SourceCheckpoint | null>(null)

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ records: number; detail: string; linesRead?: number } | null>(null)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)

  const loadCheckpoint = async () => {
    try {
      setCheckpoint(await api.sourceCheckpoint(source.id))
    } catch {
      /* the checkpoint is informational — a failure must not block the run */
    }
  }
  useEffect(() => {
    void loadCheckpoint()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.id])

  const resetCheckpoint = async () => {
    setError(null)
    try {
      await api.resetSourceCheckpoint(source.id)
      await loadCheckpoint()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  // Load the destination's projects whenever the connection changes. This opens the
  // database, so it is deliberately only done on demand (the dialog is already open).
  useEffect(() => {
    setProjects(null)
    setProjectsError(null)
    setPicked(NEW_PROJECT)
    if (!connectionId) return
    // Only restore the remembered project onto the connection it was imported into — the
    // same id may not exist, or may mean something else, in another schema.
    const remembered = connectionId === lastRun.connectionId ? (lastRun.titleShort ?? '') : ''
    let alive = true
    void (async () => {
      try {
        const r = await api.destinationProjects(connectionId)
        if (!alive) return
        // A reachable schema with no PROJECTS table yet is a normal first-import case,
        // not an error — it just yields an empty list.
        if (r.ok) setProjects(r.projects)
        else setProjectsError(r.error || 'Could not read the projects in that schema.')
        if (!remembered) return
        // Still there → preselect it. Gone (deleted since) → keep the id in the
        // new-project field rather than silently dropping what the user last used.
        if (r.ok && r.projects.some((p) => p.titleShort === remembered)) setPicked(remembered)
        else setNewProject(remembered)
      } catch (e) {
        if (!alive) return
        setProjectsError(e instanceof Error ? e.message : String(e))
        if (remembered) setNewProject(remembered)
      }
    })()
    return () => {
      alive = false
    }
    // `lastRun` is a fresh object each render but constant in value — keying on it too
    // would re-fetch the project list forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionId])

  // While the run is in flight, poll the live status for the progress bar.
  useEffect(() => {
    if (!busy) return
    let alive = true
    const tick = async () => {
      try {
        const s = await api.integrationStatus()
        if (alive && s.state === 'running') setProgress({ done: s.recordsDone, total: s.recordsTotal })
      } catch {
        /* ignore transient poll errors */
      }
    }
    void tick()
    const id = window.setInterval(tick, 350)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [busy])

  const run = async () => {
    if (!connectionId) {
      setError('Pick a destination connection.')
      return
    }
    if (!projectId.trim()) {
      setError('A project id is required.')
      return
    }
    setBusy(true)
    setError(null)
    setProgress({ done: 0, total: 0 })
    try {
      const r = await api.runSource(source.id, projectId.trim(), connectionId, delta)
      setResult(r)
      await loadCheckpoint()
      await onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const footer = (
    <>
      <span className="spacer" />
      <button className="btn" onClick={onClose} disabled={busy}>
        {result ? 'Close' : 'Cancel'}
      </button>
      {!result && (
        <button
          className="btn prominent"
          onClick={() => void run()}
          disabled={busy || !connectionId || !linked}
        >
          {busy ? 'Running…' : '▷ Run extraction'}
        </button>
      )}
    </>
  )

  return (
    <Sheet title={`Run “${source.name}”`} icon="▷" onClose={onClose} footer={footer}>
      <div className="iwiz-col narrow">
      <label className="col" style={{ gap: 4 }}>
        <span className="t-caption fg-secondary">Destination connection</span>
        <select
          className="text-input"
          value={connectionId}
          onChange={(e) => setConnectionId(e.target.value)}
          disabled={busy || store.connections.length === 0}
        >
          <option value="">— pick a connection —</option>
          {store.connections.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        {target && (
          <span className="t-caption2 fg-tertiary">
            {target.host}:{target.port} — writes into schema {target.schema || '(none set)'}
          </span>
        )}
      </label>

      {store.connections.length === 0 && (
        <div className="banner warn">
          No connections are assigned to you — ask an administrator, or create one in the
          main app.
        </div>
      )}

      {!linked && (
        <div className="banner warn">
          This source has no source type linked — edit it and pick one so the lines can be parsed.
        </div>
      )}

      <label className="col" style={{ gap: 4 }}>
        <span className="t-caption fg-secondary">Project</span>
        <select
          className="text-input"
          value={picked}
          onChange={(e) => setPicked(e.target.value)}
          disabled={busy || !connectionId}
          aria-label="Project"
        >
          <option value={NEW_PROJECT}>＋ New project…</option>
          {(projects ?? []).map((p) => (
            <option key={p.projectId} value={p.titleShort}>
              {p.titleShort}
              {p.title && p.title !== p.titleShort ? ` — ${p.title}` : ''}
            </option>
          ))}
        </select>
        {connectionId && projects === null && !projectsError && (
          <span className="t-caption2 fg-tertiary">Reading the projects in that schema…</span>
        )}
        {projectsError && (
          <span className="t-caption2" style={{ color: 'var(--orange)' }}>
            Could not list existing projects ({projectsError}) — you can still type a new
            project id below.
          </span>
        )}
        {projects !== null && projects.length === 0 && !projectsError && (
          <span className="t-caption2 fg-tertiary">
            That schema has no projects yet — this import creates the first one.
          </span>
        )}
      </label>

      {picked === NEW_PROJECT ? (
        <label className="col" style={{ gap: 4 }}>
          <span className="t-caption fg-secondary">New project code</span>
          <input
            className="text-input"
            value={newProject}
            onChange={(e) => setNewProject(e.target.value)}
            placeholder="e.g. RETAIL"
            maxLength={10}
            autoFocus
          />
          <span className="t-caption2 fg-tertiary">
            A short code (→ PROJECTS.TITLE_SHORT). A new integer PROJECT_ID is allocated,
            or the existing project with this code is topped up.
          </span>
        </label>
      ) : (
        <div className="banner warn">
          Events are <b>appended</b> to “{picked}”
          {existing ? ` (${existing.events.toLocaleString()} already stored)` : ''}
          {delta
            ? ' — with delta upload on, only lines added since the last import are read, so nothing is stored twice.'
            : ' — the whole file is read again, so everything already imported is stored a second time. To reload from scratch, delete the project first.'}
        </div>
      )}

      <div
        className="col"
        style={{
          gap: 8, padding: 10, borderRadius: 10,
          border: '1px solid var(--border-soft, var(--border))', background: 'var(--fill)',
        }}
      >
        <label className="row" style={{ gap: 8, alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={delta}
            onChange={(e) => setDelta(e.target.checked)}
            disabled={busy}
            style={{ width: 'auto' }}
          />
          <span className="t-caption" style={{ fontWeight: 600 }}>
            ⏩ Delta upload — import only what was appended since the last import
          </span>
        </label>
        <span className="t-caption2 fg-tertiary">
          {delta
            ? 'A checkpoint records how far this file has been read, so running again picks up only the new lines — no duplicates. Switch off to read the whole file from the top again.'
            : 'The whole file will be read from the top. Everything already imported into this project is stored a second time.'}
        </span>
        <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="t-caption2 fg-secondary" style={{ flex: 1, minWidth: 0 }}>
            {checkpoint?.lastError ? (
              <span className="fg-red">⚠ {checkpoint.lastError}</span>
            ) : checkpoint?.updatedAt ? (
              `✓ ${checkpoint.records.toLocaleString()} records imported · read to ${checkpoint.byteOffset.toLocaleString()} of ${checkpoint.size.toLocaleString()} bytes · last ${new Date(checkpoint.updatedAt).toLocaleString()}`
            ) : (
              'No checkpoint yet — this is the first import of this file.'
            )}
          </span>
          <button
            className="btn small"
            onClick={() => void resetCheckpoint()}
            disabled={busy || !checkpoint?.updatedAt}
            title="Forget how far the file has been read, so the next import starts from the top"
          >
            ↺ Reset checkpoint
          </button>
        </div>
      </div>

      {busy && (
        <div className="col" style={{ gap: 4 }}>
          <div className="iprogress-track">
            <div
              className={`iprogress-fill${progress && progress.total > 0 ? '' : ' indeterminate'}`}
              style={progress && progress.total > 0
                ? { width: `${Math.min(100, (progress.done / progress.total) * 100)}%` }
                : undefined}
            />
          </div>
          <span className="t-caption2 fg-secondary">
            {progress && progress.total > 0
              ? `Importing ${progress.done.toLocaleString()} / ${progress.total.toLocaleString()} log records…`
              : 'Reading the file…'}
          </span>
        </div>
      )}

      {result &&
        (result.records > 0 ? (
          <div className="t-caption" style={{ color: 'var(--green)' }}>✓ {result.detail}</div>
        ) : result.linesRead === 0 ? (
          // Nothing was appended since the checkpoint — the expected outcome of a delta
          // run with no new data, not a misconfiguration.
          <div className="t-caption fg-secondary">— {result.detail}</div>
        ) : (
          <div className="banner warn">
            ⚠ {result.detail}. No line matched — check the linked source type's regexes fit
            this file's format (edit the source type and test against a sample line).
          </div>
        ))}
      {error && <div className="t-caption fg-red">{error}</div>}
      </div>
    </Sheet>
  )
}
