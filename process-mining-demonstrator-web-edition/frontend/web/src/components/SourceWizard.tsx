/** "Add / edit source" wizard. Generic over source *kinds* (see `sourceKinds.ts`):
 *  step 1 picks a kind, step 2 fills that kind's config fields, step 3 reviews & saves.
 *  Only "File" is selectable for now; other kinds appear disabled to show the structure. */

import { useEffect, useState } from 'react'
import { api } from '../api'
import { SOURCE_KINDS, sourceKind, type SourceKindDef } from '../integration/sourceKinds'
import type { AssignedConnection, Source, SourceCheckpoint, SourceType, WatchdogConfig } from '../types'
import { SinkIngestModal } from './SinkIngestModal'
import { Sheet } from './ui'

const LAST_STEP = 3

export function SourceWizard({
  existing,
  onClose,
  onSaved,
}: {
  existing?: Source
  onClose: () => void
  onSaved: () => void | Promise<void>
}) {
  const [step, setStep] = useState(existing ? 2 : 1)
  const [kindId, setKindId] = useState(existing?.kind ?? 'file')
  const [name, setName] = useState(existing?.name ?? '')
  const [config, setConfig] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {}
    const kind = sourceKind(existing?.kind ?? 'file')
    for (const f of kind?.fields ?? []) init[f.key] = String(existing?.config?.[f.key] ?? f.default ?? '')
    return init
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sourceTypes, setSourceTypes] = useState<SourceType[]>([])
  const [previewLines, setPreviewLines] = useState(5)
  const [preview, setPreview] = useState<{ lines: string[]; truncated: boolean } | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  // Optional watchdog (File sources): auto-import new lines into a stored destination.
  const wd0 = (existing?.config?.watchdog ?? {}) as Partial<WatchdogConfig>
  const [wdEnabled, setWdEnabled] = useState(!!wd0.enabled)
  const [wdConnection, setWdConnection] = useState(wd0.connectionId ?? '')
  const [wdProject, setWdProject] = useState(wd0.projectId ?? '')
  const [wdInterval, setWdInterval] = useState(Number(wd0.intervalSecs) || 30)
  // Transaction bracket: rows committed together. 0 = one transaction for the whole
  // import. Applies to BOTH a manual run and the watchdog, so it lives outside the
  // watchdog block. Kept in sync with the backend's DEFAULT_TRANSACTION_ROWS.
  const [txRows, setTxRows] = useState(
    existing?.config?.transactionRows === undefined
      ? 5000
      : Number(existing.config.transactionRows) || 0,
  )
  const [connections, setConnections] = useState<AssignedConnection[]>([])
  const [checkpoint, setCheckpoint] = useState<SourceCheckpoint | null>(null)
  // API Server - Event Receiver: the port pool + those already taken, and the one-time token
  // shown after a sink is created (only its hash is stored server-side).
  const [sinkPorts, setSinkPorts] = useState<{
    pool: number[]
    https: Record<string, number>
    used: Record<string, string>
  }>({ pool: [], https: {}, used: {} })
  const [created, setCreated] = useState<{ id: string; token: string; port: string } | null>(null)
  const [showDetails, setShowDetails] = useState(false)

  const kind = sourceKind(kindId)

  useEffect(() => {
    void api.listConnections().then(setConnections).catch(() => setConnections([]))
  }, [])

  // Load the sink port pool when the sink kind is in play (for the port picker).
  useEffect(() => {
    if (kindId !== 'ai-agent-logging-sink') return
    void api
      .listSinkPorts()
      .then(setSinkPorts)
      .catch(() => setSinkPorts({ pool: [], https: {}, used: {} }))
  }, [kindId])

  // Show the watchdog's read checkpoint (records imported, last run, any error).
  const loadCheckpoint = () => {
    if (!existing) return
    void api.sourceCheckpoint(existing.id).then(setCheckpoint).catch(() => setCheckpoint(null))
  }
  useEffect(loadCheckpoint, [existing])

  // The picker of source types (for a 'sourceType' field).
  useEffect(() => {
    void api.listSourceTypes().then(setSourceTypes).catch(() => setSourceTypes([]))
  }, [])

  // Live preview of the first N lines of a file source, refreshed as path/lines change.
  const filePath = kindId === 'file' ? (config.path ?? '').trim() : ''
  useEffect(() => {
    if (!filePath) {
      setPreview(null)
      setPreviewError(null)
      return
    }
    let alive = true
    const t = window.setTimeout(() => {
      void api
        .previewSource(filePath, previewLines)
        .then((p) => {
          if (!alive) return
          setPreview(p)
          setPreviewError(null)
        })
        .catch((e) => {
          if (!alive) return
          setPreview(null)
          setPreviewError(e instanceof Error ? e.message : String(e))
        })
    }, 350)
    return () => {
      alive = false
      window.clearTimeout(t)
    }
  }, [filePath, previewLines])

  const pickKind = (k: SourceKindDef) => {
    if (!k.available) return
    setKindId(k.id)
    // Seed defaults for the newly chosen kind's fields.
    setConfig((prev) => {
      const next: Record<string, string> = {}
      for (const f of k.fields) next[f.key] = prev[f.key] ?? f.default ?? ''
      return next
    })
  }

  const setField = (key: string, value: string) => setConfig((c) => ({ ...c, [key]: value }))

  const missingRequired = (kind?.fields ?? []).find((f) => f.required && !config[f.key]?.trim())

  const save = async () => {
    if (!name.trim()) {
      setError('A name is required.')
      return
    }
    if (missingRequired) {
      setError(`${missingRequired.label} is required.`)
      setStep(2)
      return
    }
    if (kindId === 'file' && wdEnabled && (!wdConnection || !wdProject.trim())) {
      setError('The watchdog needs a destination connection and a project id.')
      setStep(2)
      return
    }
    setBusy(true)
    setError(null)
    // Only keep the current kind's declared fields (trimmed, non-empty).
    const cleaned: Record<string, unknown> = {}
    for (const f of kind?.fields ?? []) {
      const v = config[f.key]?.trim()
      if (v) cleaned[f.key] = v
    }
    if (kindId === 'file') cleaned.transactionRows = Math.max(0, txRows)
    if (kindId === 'file' && wdEnabled) {
      cleaned.watchdog = {
        enabled: true,
        connectionId: wdConnection,
        projectId: wdProject.trim(),
        intervalSecs: Math.max(5, wdInterval),
      } satisfies WatchdogConfig
    }
    const body = { name: name.trim(), kind: kindId, config: cleaned }
    try {
      if (existing) {
        await api.updateSource(existing.id, body)
      } else {
        const res = await api.createSource(body)
        if (res.token) {
          // A new sink — show its one-time bearer token; keep the wizard open until the
          // user has copied it (it is never shown again). The list is refreshed underneath.
          await onSaved()
          setCreated({ id: res.id, token: res.token, port: String(config.port ?? '') })
          setBusy(false)
          return
        }
      }
      await onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  const resetCheckpoint = async () => {
    if (!existing) return
    await api.resetSourceCheckpoint(existing.id).catch(() => {})
    loadCheckpoint()
  }

  const footer = (
    <>
      <span className="t-caption2 fg-tertiary">Step {step} of {LAST_STEP}</span>
      <span className="spacer" />
      <button className="btn" onClick={onClose} disabled={busy}>
        Cancel
      </button>
      {step > 1 && (
        <button className="btn" onClick={() => setStep((s) => s - 1)} disabled={busy}>
          Back
        </button>
      )}
      {step < LAST_STEP && (
        <button
          className="btn prominent"
          disabled={busy || (step === 2 && !name.trim())}
          onClick={() => setStep((s) => s + 1)}
        >
          Next
        </button>
      )}
      {step === LAST_STEP && (
        <button className="btn prominent" onClick={() => void save()} disabled={busy}>
          {busy ? 'Saving…' : existing ? 'Save changes' : 'Create source'}
        </button>
      )}
    </>
  )

  if (created) {
    return (
      <Sheet
        title="Sink created"
        icon="🤖"
        onClose={onClose}
        footer={
          <>
            <span className="spacer" />
            <button className="btn prominent" onClick={onClose}>Done</button>
          </>
        }
      >
        <div className="iwiz-col narrow">
          <div className="t-body">
            Your API Server - Event Receiver is ready. <strong>Copy its bearer token now</strong> — it
            is shown only once (only its hash is stored).
          </div>
          <Field label="Bearer token">
            <input
              className="text-input"
              readOnly
              value={created.token}
              onFocus={(e) => e.currentTarget.select()}
              style={{ fontFamily: 'var(--mono, monospace)' }}
            />
          </Field>
          <div className="row" style={{ gap: 8 }}>
            <button
              className="btn small"
              onClick={() => void navigator.clipboard?.writeText(created.token)}
            >
              Copy token
            </button>
            {/* The exact request — URL + curl with the right scheme/port/host — computed
                for the user so they don't build the endpoint by hand. */}
            <button className="btn small" onClick={() => setShowDetails(true)}>
              🔌 Show the exact request
            </button>
          </div>
          <div className="t-caption2 fg-tertiary">
            The module must be enabled in the admin interface (Event Receiver tab).
          </div>
        </div>
        {showDetails && (
          <SinkIngestModal
            sourceId={created.id}
            token={created.token}
            name={name.trim()}
            onClose={() => setShowDetails(false)}
          />
        )}
      </Sheet>
    )
  }

  return (
    <Sheet
      title={existing ? 'Edit source' : 'New source'}
      icon={kind?.icon ?? '🗂️'}
      onClose={onClose}
      footer={footer}
    >
      <div className="iwiz-col narrow">
      {step === 1 && (
        <>
          <span className="t-caption fg-secondary">Choose a source kind</span>
          <div className="col" style={{ gap: 8 }}>
            {SOURCE_KINDS.map((k) => (
              <div
                key={k.id}
                className={`card${kindId === k.id ? ' selected' : ''}`}
                style={{ minHeight: 56, cursor: k.available ? 'pointer' : 'not-allowed', opacity: k.available ? 1 : 0.55 }}
                onClick={() => pickKind(k)}
              >
                <span aria-hidden style={{ fontSize: 20 }}>{k.icon}</span>
                <div className="card-body">
                  <span className="card-title">
                    {k.label}
                    {!k.available && <span className="fg-tertiary"> · coming soon</span>}
                  </span>
                  <span className="card-sub fg-tertiary">{k.description}</span>
                </div>
                {kindId === k.id && k.available && (
                  <span className="status-dot" style={{ background: 'var(--green)' }} />
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {step === 2 && kind && (
        <>
          <Field label="Name">
            <input
              className="text-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={`e.g. ${kind.label} — access log`}
              autoFocus
            />
          </Field>
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <span aria-hidden>{kind.icon}</span>
            <span className="t-caption fg-secondary">{kind.label}</span>
            {SOURCE_KINDS.filter((k) => k.available).length > 1 && (
              <button className="btn small" onClick={() => setStep(1)}>Change kind</button>
            )}
          </div>
          <div className="row" style={{ flexWrap: 'wrap', gap: 12, alignItems: 'flex-start' }}>
          {kind.fields.map((f) => (
            <div
              key={f.key}
              style={{
                minWidth: 0,
                flex:
                  f.layout === 'narrow' ? '0 0 150px' : f.layout === 'grow' ? '1 1 220px' : '1 1 100%',
              }}
            >
            <Field label={f.required ? `${f.label} *` : f.label}>
              {f.type === 'select' ? (
                <select
                  className="text-input"
                  value={config[f.key] ?? f.default ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                >
                  {(f.options ?? []).map((o) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                </select>
              ) : f.type === 'sourceType' ? (
                <select
                  className="text-input"
                  value={config[f.key] ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                >
                  <option value="">— none —</option>
                  {sourceTypes.map((st) => (
                    <option key={st.id} value={st.id}>{st.name}</option>
                  ))}
                </select>
              ) : f.type === 'connection' ? (
                <select
                  className="text-input"
                  value={config[f.key] ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                >
                  <option value="">— pick a connection —</option>
                  {connections.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              ) : f.type === 'sinkPort' ? (
                <select
                  className="text-input"
                  value={config[f.key] ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                >
                  <option value="">— pick a port —</option>
                  {sinkPorts.pool
                    .filter((p) => !sinkPorts.used[String(p)] || String(p) === config[f.key])
                    .map((p) => (
                      <option key={p} value={String(p)}>
                        HTTP {p}
                        {sinkPorts.https?.[String(p)] ? ` · HTTPS ${sinkPorts.https[String(p)]}` : ''}
                      </option>
                    ))}
                </select>
              ) : f.type === 'checkbox' ? (
                (() => {
                  const checked = (config[f.key] ?? f.default) === 'true'
                  return (
                    <label className="row" style={{ gap: 6, alignItems: 'center', height: 30 }}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => setField(f.key, e.target.checked ? 'true' : 'false')}
                      />
                      <span className="t-caption">{checked ? 'HTTPS' : 'HTTP'}</span>
                    </label>
                  )
                })()
              ) : (
                <input
                  className="text-input"
                  type={f.type === 'password' ? 'password' : f.type === 'number' ? 'number' : 'text'}
                  value={config[f.key] ?? ''}
                  onChange={(e) => setField(f.key, e.target.value)}
                  placeholder={f.placeholder}
                />
              )}
              {f.help && <span className="t-caption2 fg-tertiary">{f.help}</span>}
              {f.type === 'sourceType' && sourceTypes.length === 0 && (
                <span className="t-caption2 fg-tertiary">
                  No source types yet — define one in the Source types section first.
                </span>
              )}
            </Field>
            </div>
          ))}
          </div>

          {kindId === 'file' && (
            <div className="col" style={{ gap: 4 }}>
              <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                <span className="t-caption fg-secondary">Preview</span>
                <span className="t-caption2 fg-tertiary">first</span>
                <input
                  className="text-input"
                  type="number"
                  min={1}
                  max={50}
                  value={previewLines}
                  onChange={(e) => setPreviewLines(Math.max(1, Math.min(50, Number(e.target.value) || 5)))}
                  style={{ width: 64 }}
                />
                <span className="t-caption2 fg-tertiary">lines</span>
              </div>
              {previewError ? (
                <div className="t-caption fg-red">{previewError}</div>
              ) : (
                <div
                  className="text-input"
                  style={{
                    fontFamily: 'var(--mono, monospace)', fontSize: 12, whiteSpace: 'pre',
                    overflow: 'auto', maxHeight: 160,
                  }}
                >
                  {!filePath ? (
                    <span className="fg-tertiary">Enter a file path to preview it.</span>
                  ) : preview && preview.lines.length ? (
                    preview.lines.join('\n') + (preview.truncated ? '\n…' : '')
                  ) : (
                    <span className="fg-tertiary">No lines.</span>
                  )}
                </div>
              )}
            </div>
          )}

          {kindId === 'file' && (
            <div
              className="col"
              style={{
                gap: 6, padding: 10, borderRadius: 10,
                border: '1px solid var(--border-soft, var(--border))', background: 'var(--fill)',
              }}
            >
              <span className="t-caption" style={{ fontWeight: 600 }}>
                ⇄ Transaction bracket
              </span>
              <label className="row" style={{ gap: 8, alignItems: 'center' }}>
                <input
                  className="text-input"
                  type="number"
                  min={0}
                  step={1000}
                  value={txRows}
                  onChange={(e) => setTxRows(Math.max(0, Number(e.target.value) || 0))}
                  style={{ width: 120 }}
                />
                <span className="t-caption2 fg-secondary">
                  rows per transaction {txRows === 0 && '(one transaction for the whole import)'}
                </span>
              </label>
              <span className="t-caption2 fg-tertiary">
                Rows are inserted inside a transaction and committed once this many have
                been written. A <strong>larger</strong> bracket means fewer, bigger
                transactions — more atomic, but the database holds more open at once. A{' '}
                <strong>smaller</strong> one commits steadily, so a failure part-way
                leaves the already-committed rows in place. <strong>0</strong> imports
                everything in a single transaction: all-or-nothing. Applies to a manual
                run and to the watchdog.
              </span>
            </div>
          )}

          {kindId === 'file' && (
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
                  checked={wdEnabled}
                  onChange={(e) => setWdEnabled(e.target.checked)}
                  style={{ width: 'auto' }}
                />
                <span className="t-caption" style={{ fontWeight: 600 }}>
                  👁 Watchdog — auto-import new lines when the file grows
                </span>
              </label>
              <span className="t-caption2 fg-tertiary">
                A background job watches this file and imports only the newly-appended
                lines into the destination below. A checkpoint is kept per file, so nothing
                is imported twice — even across restarts.
              </span>

              {wdEnabled && (
                <>
                  <Field label="Destination connection *">
                    <select
                      className="text-input"
                      value={wdConnection}
                      onChange={(e) => setWdConnection(e.target.value)}
                    >
                      <option value="">— pick a connection —</option>
                      {connections.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  </Field>
                  <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                    <div style={{ flex: '1 1 160px', minWidth: 0 }}>
                      <Field label="Project id *">
                        <input
                          className="text-input"
                          value={wdProject}
                          onChange={(e) => setWdProject(e.target.value)}
                          placeholder="e.g. LIVE-LOG"
                        />
                      </Field>
                    </div>
                    <div style={{ width: 130 }}>
                      <Field label="Every (seconds)">
                        <input
                          className="text-input"
                          type="number"
                          min={5}
                          value={wdInterval}
                          onChange={(e) => setWdInterval(Math.max(5, Number(e.target.value) || 30))}
                        />
                      </Field>
                    </div>
                  </div>
                  {connections.length === 0 && (
                    <span className="t-caption2 fg-tertiary">
                      No connections are assigned to you — ask an administrator, or create
                      one in the main app.
                    </span>
                  )}
                  {existing && checkpoint && (
                    <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span className="t-caption2 fg-secondary" style={{ flex: 1, minWidth: 0 }}>
                        {checkpoint.lastError ? (
                          <span className="fg-red">⚠ {checkpoint.lastError}</span>
                        ) : checkpoint.updatedAt ? (
                          `✓ ${checkpoint.records.toLocaleString()} records imported · last checked ${new Date(checkpoint.updatedAt).toLocaleString()}`
                        ) : (
                          'Not run yet — the watchdog will pick it up shortly.'
                        )}
                      </span>
                      <button className="btn small" onClick={() => void resetCheckpoint()}>
                        ↺ Reset checkpoint
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </>
      )}

      {step === 3 && kind && (
        <div className="col" style={{ gap: 8 }}>
          <div className="row" style={{ gap: 8, alignItems: 'baseline' }}>
            <span aria-hidden>{kind.icon}</span>
            <strong>{name || '(unnamed)'}</strong>
            <span className="t-caption2 fg-tertiary">{kind.label}</span>
          </div>
          {kind.fields.map((f) => (
            <div key={f.key} className="row" style={{ gap: 10, alignItems: 'baseline' }}>
              <span className="t-caption fg-tertiary" style={{ minWidth: 130 }}>{f.label}</span>
              <span className="t-body" style={{ fontFamily: f.type === 'password' ? undefined : 'var(--mono, monospace)', wordBreak: 'break-all' }}>
                {config[f.key]?.trim()
                  ? f.type === 'password'
                    ? '••••••'
                    : f.type === 'sourceType'
                      ? sourceTypes.find((st) => st.id === config[f.key])?.name ?? '(unknown)'
                      : f.type === 'connection'
                        ? connections.find((c) => c.id === config[f.key])?.name ?? '(unknown)'
                        : config[f.key]
                  : <span className="fg-tertiary">—</span>}
              </span>
            </div>
          ))}
        </div>
      )}

      {error && <div className="t-caption fg-red">{error}</div>}
      </div>
    </Sheet>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="col" style={{ gap: 4 }}>
      <span className="t-caption fg-secondary">{label}</span>
      {children}
    </label>
  )
}
