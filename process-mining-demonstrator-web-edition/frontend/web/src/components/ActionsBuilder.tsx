/** The Actions builder — author, test and save the business-readable action scripts
 *  for a chosen (connection, project). Reuses the app store to connect and load the
 *  project graph, then talks to the /api/projects/{id}/actions* endpoints.
 *
 *  Layout mirrors the other surfaces: a left panel with Connections, Projects and
 *  Actions sections (＋ to add), the shared identity/authentication footer pinned at
 *  the bottom, and the editor in the main area. */

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { describeAction } from '../actions/describe'
import { insertAvailabilityStep } from '../actions/editAvailability'
import { formatSql } from '../actions/formatSql'
import { parseAction } from '../actions/parseAction'
import { resolveScope } from '../actions/resolveScope'
import type { ActionRunResult, SavedAction } from '../actions/types'
import { useStore } from '../store'
import type { AssignedConnection } from '../types'
import { ActionFlowchart } from './ActionFlowchart'
import { AuthFooter } from './AuthFooter'
import { Logo } from './Logo'
import { SectionHeader } from './SectionHeader'
import { ThemeBar } from './ThemeBar'
import { ActionResultTable } from './ActionResultTable'
import { Chevron, Divider, Spinner } from './ui'

/** A collapsible section header for the editor canvas (chevron + title). */
function CollapseHeader({ title, open, onToggle }: { title: string; open: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className="row"
      style={{
        gap: 6,
        alignItems: 'center',
        width: '100%',
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        padding: '10px 0',
        color: 'inherit',
        textAlign: 'left',
      }}
    >
      <Chevron open={open} />
      <span style={{ fontSize: 14, fontWeight: 600 }}>{title}</span>
    </button>
  )
}

const TEMPLATE = `AVAILABILITY
\tALL NODES
SHOW
\tLAST 1 LOG ENTRY
FROM
\tNODE(THIS)
SORT
\tDESCENDING`

const KEYWORDS = 'AVAILABILITY · SHOW · FROM · SORT · WHERE — NODE(THIS/PREVIOUS/FOLLOWING/ALL FOLLOWING)'

type SectionId = 'connections' | 'projects' | 'actions'

export function ActionsBuilder({ onShowHelp }: { onShowHelp: () => void }) {
  const store = useStore()
  const connId = store.connection.activeProfileId ?? ''
  const projectId = store.selectedProject?.projectId ?? 0
  const steps = useMemo(() => Object.keys(store.processGraph.steps), [store.processGraph])
  const transitions = store.processGraph.transitions

  const [openSection, setOpenSection] = useState<SectionId>('connections')
  const toggle = (id: SectionId) => setOpenSection((cur) => (cur === id ? cur : id))

  const [saved, setSaved] = useState<SavedAction[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [script, setScript] = useState(TEMPLATE)
  const [testNode, setTestNode] = useState('')
  const [pickStep, setPickStep] = useState('')
  const [sql, setSql] = useState('')
  const [result, setResult] = useState<ActionRunResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ text: string; error?: boolean } | null>(null)
  const [sqlOpen, setSqlOpen] = useState(false)
  const [testOpen, setTestOpen] = useState(false)

  const parsed = useMemo(() => parseAction(script), [script])
  const spec = parsed.spec
  const canEdit = Boolean(connId && projectId)

  // Load the saved actions for the current (connection, project).
  useEffect(() => {
    if (!connId || !projectId) {
      setSaved([])
      return
    }
    void api
      .listActions(projectId, connId)
      .then((r) => setSaved(r.actions))
      .catch((e) => setMsg({ text: String(e.message ?? e), error: true }))
  }, [connId, projectId])

  // Default the Test context node to the first available step.
  useEffect(() => {
    if (steps.length && !steps.includes(testNode)) setTestNode(steps[0])
  }, [steps, testNode])

  // Default the AVAILABILITY step picker to the first available step.
  useEffect(() => {
    if (steps.length && !steps.includes(pickStep)) setPickStep(steps[0])
  }, [steps, pickStep])

  // Live SQL preview (debounced) for the current spec + context node.
  const sqlTimer = useRef<number | undefined>(undefined)
  useEffect(() => {
    window.clearTimeout(sqlTimer.current)
    if (!sqlOpen || !spec || !connId || !projectId) {
      // Only fetch the translated SQL while its (collapsed-by-default) pane is open.
      return
    }
    const resolved = testNode ? resolveScope(spec.from.selectors, testNode, transitions) : []
    sqlTimer.current = window.setTimeout(() => {
      void api
        .previewActionSql(projectId, {
          connectionId: connId,
          spec,
          filter: store.currentFilterSpec(),
          contextNode: testNode,
          resolvedSteps: resolved,
        })
        .then((r) => setSql(formatSql(r.sql)))
        .catch((e) => setSql(`-- ${String(e.message ?? e)}`))
    }, 250)
    return () => window.clearTimeout(sqlTimer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [script, testNode, connId, projectId, transitions, sqlOpen])

  const connectOrDisconnect = async (conn: AssignedConnection) => {
    const isActive = store.connection.activeProfileId === conn.id
    setResult(null)
    setBusy(true)
    try {
      if (store.connection.isConnected && isActive) {
        await store.disconnect()
        return
      }
      if (store.connection.isConnected) await store.disconnect()
      await store.connectConnection(conn)
      setOpenSection('projects')
    } finally {
      setBusy(false)
    }
  }

  const pickProject = async (pid: number) => {
    const project = store.projects.find((p) => p.projectId === pid)
    if (!project) return
    setBusy(true)
    setResult(null)
    try {
      await store.selectProject(project)
      await store.reloadGraph()
      setOpenSection('actions')
    } finally {
      setBusy(false)
    }
  }

  const newAction = () => {
    setSelectedId(null)
    setName('')
    setScript(TEMPLATE)
    setResult(null)
    setMsg(null)
    setOpenSection('actions')
  }

  const editAction = (a: SavedAction) => {
    setSelectedId(a.id)
    setName(a.name)
    setScript(a.script)
    setResult(null)
    setMsg(null)
  }

  const save = async () => {
    if (!spec) return setMsg({ text: 'Fix the script errors before saving.', error: true })
    if (!name.trim()) return setMsg({ text: 'Give the action a name.', error: true })
    if (!canEdit) return setMsg({ text: 'Choose a connection and project first.', error: true })
    setBusy(true)
    try {
      const body = { connectionId: connId, name: name.trim(), script, spec, enabled: true }
      const saved_ = selectedId
        ? await api.updateAction(projectId, selectedId, body)
        : await api.createAction(projectId, body)
      setSelectedId(saved_.id)
      setSaved((await api.listActions(projectId, connId)).actions)
      setMsg({ text: 'Saved.' })
    } catch (e) {
      setMsg({ text: String((e as Error).message ?? e), error: true })
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!selectedId) return
    setBusy(true)
    try {
      await api.deleteAction(projectId, selectedId, connId)
      setSaved((await api.listActions(projectId, connId)).actions)
      newAction()
      setMsg({ text: 'Deleted.' })
    } catch (e) {
      setMsg({ text: String((e as Error).message ?? e), error: true })
    } finally {
      setBusy(false)
    }
  }

  const test = async () => {
    if (!spec) return
    if (!store.connection.isConnected) return setMsg({ text: 'Connect to the database first.', error: true })
    const resolved = resolveScope(spec.from.selectors, testNode, transitions)
    setBusy(true)
    setResult(null)
    try {
      const r = await api.previewRunAction(projectId, {
        connectionId: connId,
        spec,
        filter: store.currentFilterSpec(),
        contextNode: testNode,
        resolvedSteps: resolved,
      })
      setResult(r)
      setMsg(null)
    } catch (e) {
      setMsg({ text: String((e as Error).message ?? e), error: true })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app">
      {/* ── Left panel ─────────────────────────────────────────────────────── */}
      <aside className="sidebar">
        <div className="sidebar-scroll">
          <div className="brand-header">
            <div className="brand-logo" aria-hidden>
              <Logo />
            </div>
            <div className="col" style={{ gap: 2 }}>
              <span className="t-title3">Actions</span>
              <span className="t-caption fg-secondary">Node-menu action builder</span>
            </div>
          </div>

          <Divider />
          <SectionHeader
            title="Connections"
            count={store.connections.length}
            open={openSection === 'connections'}
            onToggle={() => toggle('connections')}
            trailing={
              <button className="icon-btn" title="Refresh connections" onClick={() => void store.refreshConnections()}>
                ↻
              </button>
            }
          />
          {openSection === 'connections' && (
            <div className="card-list" style={{ maxHeight: 216 }}>
              {store.connections.length === 0 && (
                <span className="t-caption fg-tertiary" style={{ padding: '0 4px' }}>
                  No connections assigned to you. Ask an administrator to grant access.
                </span>
              )}
              {store.connections.map((conn) => {
                const isActive = store.connection.activeProfileId === conn.id
                const isConnected = store.connection.isConnected && isActive
                return (
                  <button
                    key={conn.id}
                    className={`card${isActive ? ' selected' : ''}`}
                    style={{ minHeight: 56 }}
                    onClick={() => void connectOrDisconnect(conn)}
                  >
                    <span aria-hidden style={{ fontSize: 16, color: isConnected ? 'var(--green)' : 'var(--accent)' }}>
                      ⛁
                    </span>
                    <div className="card-body">
                      <span className="card-title">{conn.name || '(unnamed)'}</span>
                      <span className="card-sub">
                        {conn.host || '(no host)'}:{conn.port}
                      </span>
                    </div>
                    {isActive && (
                      <span
                        className="status-dot"
                        style={{ background: isConnected ? 'var(--green)' : 'var(--orange)' }}
                        title={isConnected ? 'Connected' : 'Not connected'}
                      />
                    )}
                  </button>
                )
              })}
            </div>
          )}

          <Divider />
          <SectionHeader
            title="Projects"
            count={store.projects.length}
            open={openSection === 'projects'}
            onToggle={() => toggle('projects')}
          />
          {openSection === 'projects' && (
            <div className="card-list" style={{ maxHeight: 216 }}>
              {!store.connection.isConnected && (
                <span className="t-caption fg-tertiary" style={{ padding: '0 4px' }}>
                  Connect to a database to list its projects.
                </span>
              )}
              {store.projects.map((project) => {
                const selected = store.selectedProject?.projectId === project.projectId
                return (
                  <button
                    key={project.projectId}
                    className={`card${selected ? ' selected' : ''}`}
                    onClick={() => void pickProject(project.projectId)}
                  >
                    <span aria-hidden className="fg-accent">
                      📈
                    </span>
                    <div className="card-body">
                      <span className="card-title">{project.title || project.projectId}</span>
                      {project.description && <span className="card-sub">{project.description}</span>}
                    </div>
                    {selected && <span className="fg-accent">✓</span>}
                  </button>
                )
              })}
            </div>
          )}

          <Divider />
          <SectionHeader
            title="Actions"
            count={saved.length}
            open={openSection === 'actions'}
            onToggle={() => toggle('actions')}
            trailing={
              <button
                className="icon-btn"
                title="New action"
                disabled={!canEdit}
                onClick={newAction}
              >
                ＋
              </button>
            }
          />
          {openSection === 'actions' && (
            <div className="card-list" style={{ maxHeight: 260 }}>
              {!canEdit && (
                <span className="t-caption fg-tertiary" style={{ padding: '0 4px' }}>
                  Choose a connection and project first.
                </span>
              )}
              {canEdit &&
                saved.map((a) => (
                  <button
                    key={a.id}
                    className={`card${a.id === selectedId ? ' selected' : ''}`}
                    onClick={() => editAction(a)}
                  >
                    <span aria-hidden className="fg-accent">
                      ⚡
                    </span>
                    <div className="card-body">
                      <span className="card-title">{a.name || '(unnamed)'}</span>
                    </div>
                  </button>
                ))}
              {canEdit && !saved.length && (
                <span className="t-caption fg-tertiary" style={{ padding: '0 4px' }}>
                  No actions yet. Use ＋ to create one.
                </span>
              )}
            </div>
          )}
        </div>

        <AuthFooter />
        <Divider />
        <ThemeBar />
      </aside>

      {/* ── Editor ─────────────────────────────────────────────────────────── */}
      <main className="integration-body" style={{ overflowY: 'auto' }}>
        <div
          className="row"
          style={{ gap: 8, alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid var(--border)' }}
        >
          <strong>{selectedId ? name || '(unnamed action)' : 'New action'}</strong>
          {busy && <Spinner />}
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={onShowHelp}>
            ? Help
          </button>
        </div>

        {!canEdit ? (
          <div className="center-fill" style={{ flex: 1, gap: 8, padding: 24, textAlign: 'center' }}>
            <p className="fg-secondary" style={{ maxWidth: 440 }}>
              Choose a connection and a project in the left panel to author its node-menu actions.
              Actions are saved per connection and project, so different customers keep their own sets.
            </p>
          </div>
        ) : (
          <div style={{ padding: 16 }}>
            {/* Name + Save / Delete on the same row. */}
            <div className="row" style={{ gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div className="field" style={{ flex: 1, minWidth: 220, maxWidth: 420, margin: 0 }}>
                <label>Name</label>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Last log entry" />
              </div>
              <button className="btn primary" disabled={busy} onClick={() => void save()}>
                Save
              </button>
              {selectedId && (
                <button className="btn" disabled={busy} onClick={() => void remove()}>
                  Delete
                </button>
              )}
              {msg && (
                <span style={{ color: msg.error ? 'var(--red)' : 'var(--green)', fontSize: 13 }}>{msg.text}</span>
              )}
            </div>

            {/* Script editor. */}
            <div style={{ marginTop: 14 }}>
              <label className="fg-secondary" style={{ fontSize: 13 }}>
                Script
              </label>
              <textarea
                value={script}
                onChange={(e) => setScript(e.target.value)}
                spellCheck={false}
                style={{
                  width: '100%',
                  height: 240,
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                  fontSize: 13,
                  tabSize: 4,
                  whiteSpace: 'pre',
                }}
              />
              {/* Step picker → inserts the exact node name into AVAILABILITY, so the
                  awkward Σ of aggregate steps never has to be typed by hand. */}
              <div className="row" style={{ gap: 8, alignItems: 'flex-end', flexWrap: 'wrap', margin: '8px 0 2px' }}>
                <div className="field" style={{ maxWidth: 260, margin: 0 }}>
                  <label>Add step to AVAILABILITY</label>
                  <select value={pickStep} onChange={(e) => setPickStep(e.target.value)}>
                    {steps.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  className="btn"
                  disabled={!pickStep}
                  onClick={() => setScript((prev) => insertAvailabilityStep(prev, pickStep))}
                  title="Insert this step's exact name into the AVAILABILITY clause"
                >
                  ＋ Add to AVAILABILITY
                </button>
              </div>
              <p className="fg-secondary" style={{ fontSize: 12, margin: '4px 0' }}>
                Keywords: {KEYWORDS}
              </p>
              {parsed.errors.length ? (
                <ul style={{ color: 'var(--red)', fontSize: 13, margin: '4px 0', paddingLeft: 18 }}>
                  {parsed.errors.map((e, i) => (
                    <li key={i}>
                      {e.line ? `Line ${e.line}: ` : ''}
                      {e.message}
                    </li>
                  ))}
                </ul>
              ) : (
                <p style={{ color: 'var(--green)', fontSize: 13, margin: '4px 0' }}>
                  ✓ {spec ? describeAction(spec) : 'Valid.'}
                </p>
              )}
            </div>

            {/* Translated SQL — below the editor, collapsible (collapsed by default). */}
            <div style={{ borderTop: '1px solid var(--border)', marginTop: 8 }}>
              <CollapseHeader title="Translated SQL" open={sqlOpen} onToggle={() => setSqlOpen((v) => !v)} />
              {sqlOpen && (
                <>
                  <p className="fg-secondary" style={{ fontSize: 12, margin: '0 0 4px' }}>
                    Guided by the chart filters at run time.
                  </p>
                  <pre
                    style={{
                      background: 'var(--bg-tertiary-grouped, var(--bg-secondary))',
                      padding: 10,
                      borderRadius: 6,
                      fontSize: 12,
                      overflowX: 'auto',
                      maxHeight: 260,
                      margin: '2px 0 12px',
                    }}
                  >
                    {sql || '—'}
                  </pre>
                </>
              )}
            </div>

            {/* Test / result — below the SQL, collapsible (collapsed by default). */}
            <div style={{ borderTop: '1px solid var(--border)' }}>
              <CollapseHeader title="Test" open={testOpen} onToggle={() => setTestOpen((v) => !v)} />
              {testOpen && (
                <div style={{ paddingBottom: 12 }}>
                  <div className="row" style={{ gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                    <div className="field" style={{ maxWidth: 260, margin: 0 }}>
                      <label>Test on node (stands in for THIS)</label>
                      <select value={testNode} onChange={(e) => setTestNode(e.target.value)}>
                        {steps.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                    </div>
                    <button className="btn" disabled={!spec || busy} onClick={() => void test()}>
                      ▶ Test
                    </button>
                  </div>
                  <p className="fg-secondary" style={{ fontSize: 12, marginTop: 6 }}>
                    Test runs against the project&rsquo;s current default filters; in the app the action uses whatever
                    filters the viewer has set.
                  </p>
                  {result && result.kind === 'flowchart' && result.graph && (
                    <div style={{ marginTop: 8 }}>
                      <ActionFlowchart result={result} height={420} />
                    </div>
                  )}
                  {result && result.kind !== 'flowchart' && (
                    <div style={{ marginTop: 8 }}>
                      <ActionResultTable result={result} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
