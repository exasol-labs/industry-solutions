/** Connection editor for connection managers.
 *
 * Lets a *power* user, a *developer*, or an admin create and edit database/LLM
 * connections from the app, assign them to other users, and manage the projects
 * stored in a connection's schema — the same shape the admin interface exposes,
 * scoped to connections the user owns. */

import { useEffect, useState } from 'react'
import type { ConnectionProject, ManagedConnection } from '../types'
import { useStore } from '../store'
import { ConfirmSheet, Sheet, Spinner } from './ui'

const CERT_MODES = [
  { value: 'verify', label: 'Verify (system trust store)' },
  { value: 'fingerprint', label: 'Pin fingerprint' },
  { value: 'insecure', label: 'Accept any (insecure)' },
]

type Draft = {
  id: string | null
  name: string
  comment: string
  host: string
  port: number
  username: string
  schema: string
  useTLS: boolean
  certModeRaw: string
  fingerprint: string
  minRSAKeySizeBits: number
  llmURL: string
  llmModel: string
  assignments: string[]
}

function draftFrom(conn: ManagedConnection | null): Draft {
  return {
    id: conn?.id ?? null,
    name: conn?.name ?? '',
    comment: conn?.comment ?? '',
    host: conn?.host ?? '',
    port: conn?.port ?? 8563,
    username: conn?.username ?? '',
    schema: conn?.schema ?? '',
    useTLS: conn?.useTLS ?? false,
    certModeRaw: conn?.certModeRaw || 'verify',
    fingerprint: conn?.fingerprint ?? '',
    minRSAKeySizeBits: conn?.minRSAKeySizeBits ?? 2048,
    llmURL: conn?.llmURL ?? '',
    llmModel: conn?.llmModel ?? '',
    assignments: conn?.assignments ?? [],
  }
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="col" style={{ gap: 4 }}>
      <span className="t-caption fg-secondary">{label}</span>
      {children}
    </label>
  )
}

/** One demo dataset: title + description, then schema · journeys · Generate in a
 *  single row (the count is typed, not stepped). Owns its journey count + result. */
function DemoSection({
  icon,
  title,
  description,
  schema,
  onSchema,
  generate,
  defaultJourneys = 500,
}: {
  icon: string
  title: string
  description: string
  schema: string
  onSchema: (value: string) => void
  generate: (journeys: number) => Promise<{ ok: boolean; text: string }>
  defaultJourneys?: number
}) {
  const [journeys, setJourneys] = useState(defaultJourneys)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  const run = async () => {
    setBusy(true)
    setResult(null)
    setResult(await generate(journeys))
    setBusy(false)
  }

  return (
    <div
      role="group"
      aria-label={title}
      className="col"
      style={{
        gap: 8,
        padding: 12,
        border: '1px solid var(--separator-soft)',
        borderRadius: 10,
        background: 'var(--bg-fill)',
      }}
    >
      <div className="row" style={{ gap: 8, alignItems: 'center' }}>
        <span aria-hidden style={{ fontSize: 18, lineHeight: 1 }}>
          {icon}
        </span>
        <span className="t-caption" style={{ fontWeight: 600 }}>
          {title}
        </span>
      </div>
      <span className="t-caption2 fg-tertiary">{description}</span>

      <div className="row" style={{ gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 150 }}>
          <Field label="Schema">
            <input
              className="text-input"
              value={schema}
              placeholder="DEMO"
              onChange={(e) => onSchema(e.target.value)}
            />
          </Field>
        </div>
        <div style={{ width: 130 }}>
          <Field label="Journeys">
            {/* No upper bound — large datasets (e.g. Airport Passenger Flow) stream. */}
            <input
              className="text-input"
              type="number"
              min={1}
              step={1}
              value={journeys}
              onChange={(e) => setJourneys(Math.max(1, Number(e.target.value) || 0))}
            />
          </Field>
        </div>
        <button
          className="btn prominent"
          disabled={busy || !schema.trim() || journeys < 1}
          onClick={() => void run()}
        >
          {busy ? (
            <>
              <Spinner /> Generating…
            </>
          ) : (
            <>
              {icon} Generate
            </>
          )}
        </button>
        {result && (
          <span
            className="t-caption2"
            title={result.text}
            style={{
              flexBasis: '100%',
              color: result.ok ? 'var(--green)' : 'var(--red)',
            }}
          >
            {result.text}
          </span>
        )}
      </div>
    </div>
  )
}

export function ConnectionEditor({
  connection,
  onClose,
}: {
  connection: ManagedConnection | null
  onClose: () => void
}) {
  const store = useStore()
  const isNew = connection === null
  const hasPassword = connection?.hasPassword ?? false
  const hasLLMKey = connection?.hasLLMKey ?? false

  const [draft, setDraft] = useState<Draft>(() => draftFrom(connection))
  // Secrets are write-only: left blank keeps the stored value untouched.
  const [password, setPassword] = useState('')
  const [passwordTouched, setPasswordTouched] = useState(false)
  const [llmKey, setLlmKey] = useState('')
  const [llmKeyTouched, setLlmKeyTouched] = useState(false)

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Test outcome shown next to the Test button — green ok, orange one component
  // failed, red both failed.
  const [testResult, setTestResult] = useState<{
    tone: 'ok' | 'warn' | 'bad'
    text: string
  } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  // Schema provisioning outcome.
  const [provision, setProvision] = useState<{ ok: boolean; text: string } | null>(null)
  const [tab, setTab] = useState<'details' | 'demo' | 'projects'>('details')
  // Projects stored in this connection's schema (loaded lazily on the Projects tab).
  const [projects, setProjects] = useState<ConnectionProject[] | null>(null)
  const [projectsBusy, setProjectsBusy] = useState(false)
  const [projectsError, setProjectsError] = useState<string | null>(null)
  const [confirmProject, setConfirmProject] = useState<ConnectionProject | null>(null)

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const body = (): Record<string, unknown> => {
    const b: Record<string, unknown> = {
      id: draft.id,
      name: draft.name.trim(),
      comment: draft.comment.trim(),
      host: draft.host.trim(),
      port: draft.port,
      username: draft.username.trim(),
      schema: draft.schema.trim(),
      useTLS: draft.useTLS,
      certModeRaw: draft.certModeRaw,
      fingerprint: draft.fingerprint.trim(),
      minRSAKeySizeBits: draft.minRSAKeySizeBits,
      llmURL: draft.llmURL.trim(),
      llmModel: draft.llmModel.trim(),
      assignments: draft.assignments,
    }
    if (passwordTouched) b.password = password
    if (llmKeyTouched) b.llmKey = llmKey
    return b
  }

  const runTest = async () => {
    setBusy(true)
    setError(null)
    setTestResult(null)
    const res = await store.testManagedConnection({
      host: draft.host.trim(),
      port: draft.port,
      username: draft.username.trim(),
      password,
      schema: draft.schema.trim(),
      useTLS: draft.useTLS,
      certModeRaw: draft.certModeRaw,
      fingerprint: draft.fingerprint.trim(),
      minRSAKeySizeBits: draft.minRSAKeySizeBits,
      llmURL: draft.llmURL.trim(),
      llmKey,
    })
    setBusy(false)
    const llmConsidered = draft.llmURL.trim() !== ''
    const dbOk = !res.dbError
    const llmOk = !llmConsidered || !res.llmError
    const parts: string[] = []
    parts.push(res.dbError ? `Database: ${res.dbError}` : 'Database OK')
    if (llmConsidered) {
      parts.push(
        res.llmError
          ? `LLM: ${res.llmError}`
          : `LLM OK${res.llmModels.length ? ` (${res.llmModels.length} models)` : ''}`,
      )
    }
    const failures = (dbOk ? 0 : 1) + (llmConsidered && !llmOk ? 1 : 0)
    const total = llmConsidered ? 2 : 1
    const tone = failures === 0 ? 'ok' : failures >= total ? 'bad' : 'warn'
    setTestResult({ tone, text: parts.join('  ·  ') })
  }

  const runProvision = async () => {
    setBusy(true)
    setError(null)
    setProvision(null)
    const res = await store.provisionSchema({
      host: draft.host.trim(),
      port: draft.port,
      username: draft.username.trim(),
      password,
      schema: draft.schema.trim(),
      useTLS: draft.useTLS,
      certModeRaw: draft.certModeRaw,
      fingerprint: draft.fingerprint.trim(),
      minRSAKeySizeBits: draft.minRSAKeySizeBits,
    })
    setBusy(false)
    setProvision(
      res.ok
        ? { ok: true, text: `Created: ${res.created.join(', ')}` }
        : { ok: false, text: res.error || 'Could not create the schema.' },
    )
  }

  const runDemo = async (
    dataset: 'retail' | 'finance' | 'transportation' | 'airport',
    journeys: number,
  ): Promise<{ ok: boolean; text: string }> => {
    const res = await store.generateDemo({
      dataset,
      host: draft.host.trim(),
      port: draft.port,
      username: draft.username.trim(),
      password,
      schema: draft.schema.trim(),
      useTLS: draft.useTLS,
      certModeRaw: draft.certModeRaw,
      fingerprint: draft.fingerprint.trim(),
      minRSAKeySizeBits: draft.minRSAKeySizeBits,
      journeys,
    })
    return res.ok
      ? { ok: true, text: res.message || `Created ${res.journeys} journeys.` }
      : { ok: false, text: res.error || 'Could not generate demo content.' }
  }

  const save = async () => {
    if (!draft.name.trim()) {
      setError('Name is required.')
      return
    }
    setBusy(true)
    setError(null)
    const { ok, error: err } = await store.saveManagedConnection(body())
    setBusy(false)
    if (ok) onClose()
    else setError(err)
  }

  const remove = async () => {
    if (!draft.id) return
    setBusy(true)
    const ok = await store.deleteManagedConnection(draft.id)
    setBusy(false)
    if (ok) onClose()
    else {
      setConfirmDelete(false)
      setError('Delete failed.')
    }
  }

  const loadProjectsList = async () => {
    if (!draft.id) return
    setProjectsBusy(true)
    setProjectsError(null)
    const res = await store.listConnectionProjects(draft.id)
    setProjectsBusy(false)
    if (res.ok) setProjects(res.projects)
    else {
      setProjects([])
      setProjectsError(res.error || 'Could not read the projects for this connection.')
    }
  }

  // Load the project list the first time the Projects tab is opened.
  useEffect(() => {
    if (tab === 'projects' && draft.id && projects === null) void loadProjectsList()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const removeProject = async (p: ConnectionProject) => {
    if (!draft.id) return
    setProjectsBusy(true)
    const res = await store.deleteConnectionProject(draft.id, p.projectId)
    setProjectsBusy(false)
    setConfirmProject(null)
    if (res.ok) {
      setProjects(null)
      await loadProjectsList()
    } else {
      setProjectsError(res.error || 'Could not delete the project.')
    }
  }

  const toggleAssignment = (username: string) =>
    set(
      'assignments',
      draft.assignments.includes(username)
        ? draft.assignments.filter((u) => u !== username)
        : [...draft.assignments, username],
    )

  return (
    <Sheet
      title={isNew ? 'New Connection' : 'Edit Connection'}
      icon="⛁"
      wide
      onClose={onClose}
      footer={
        <>
          <button className="btn" disabled={busy} onClick={() => void runTest()}>
            Test
          </button>
          {testResult && (
            <span
              className="t-caption2"
              title={testResult.text}
              style={{
                maxWidth: 300,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                color:
                  testResult.tone === 'ok'
                    ? 'var(--green)'
                    : testResult.tone === 'warn'
                      ? 'var(--orange)'
                      : 'var(--red)',
              }}
            >
              {testResult.text}
            </span>
          )}
          {!isNew && (
            <button
              className="btn"
              style={{ color: 'var(--red)' }}
              disabled={busy}
              onClick={() => setConfirmDelete(true)}
            >
              Delete
            </button>
          )}
          <span className="spacer" />
          <button className="btn" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button className="btn prominent" disabled={busy} onClick={() => void save()}>
            Save
          </button>
        </>
      }
    >
      <div className="col" style={{ gap: 12 }}>
        {error && <span className="t-caption fg-red">{error}</span>}

        <div className="sheet-tabs">
          <button
            className={tab === 'details' ? 'sel' : ''}
            onClick={() => setTab('details')}
          >
            Database / LLM Details
          </button>
          <button className={tab === 'demo' ? 'sel' : ''} onClick={() => setTab('demo')}>
            Demo Content
          </button>
          {!isNew && (
            <button
              className={tab === 'projects' ? 'sel' : ''}
              onClick={() => setTab('projects')}
            >
              Projects
            </button>
          )}
        </div>

        {tab === 'details' && (
        <>
        <Field label="Name">
          <input
            className="text-input"
            value={draft.name}
            onChange={(e) => set('name', e.target.value)}
          />
        </Field>
        <Field label="Comment">
          <input
            className="text-input"
            value={draft.comment}
            onChange={(e) => set('comment', e.target.value)}
          />
        </Field>

        <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
          Database
        </span>
        <div className="row" style={{ gap: 8 }}>
          <Field label="Host">
            <input
              className="text-input"
              value={draft.host}
              onChange={(e) => set('host', e.target.value)}
            />
          </Field>
          <div style={{ width: 96 }}>
            <Field label="Port">
              <input
                className="text-input"
                type="number"
                value={draft.port}
                onChange={(e) => set('port', Number(e.target.value) || 0)}
              />
            </Field>
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Field label="Username">
            <input
              className="text-input"
              value={draft.username}
              autoComplete="off"
              onChange={(e) => set('username', e.target.value)}
            />
          </Field>
          <Field label="Schema">
            <input
              className="text-input"
              value={draft.schema}
              onChange={(e) => set('schema', e.target.value)}
            />
          </Field>
        </div>
        <Field label="Password">
          <input
            className="text-input"
            type="password"
            value={password}
            autoComplete="new-password"
            placeholder={hasPassword ? '•••••• (unchanged)' : ''}
            onChange={(e) => {
              setPassword(e.target.value)
              setPasswordTouched(true)
            }}
          />
        </Field>

        <div
          className="col"
          style={{
            gap: 6,
            padding: 10,
            borderRadius: 8,
            border: '1px solid var(--separator-soft)',
            background: 'var(--bg-fill)',
          }}
        >
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <button
              className="btn"
              disabled={busy || !draft.schema.trim()}
              onClick={() => void runProvision()}
            >
              Create schema &amp; tables
            </button>
            {provision && (
              <span
                className="t-caption2"
                title={provision.text}
                style={{
                  maxWidth: 300,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  color: provision.ok ? 'var(--green)' : 'var(--red)',
                }}
              >
                {provision.text}
              </span>
            )}
          </div>
          <span className="t-caption2 fg-tertiary">
            Creates the “{draft.schema.trim() || '…'}” schema and the process-mining
            tables (PROJECTS, JOURNEYS, STEPS, METAS, NOTES) if they don’t exist. This
            needs a database account permitted to <strong>CREATE SCHEMA</strong> and{' '}
            <strong>CREATE TABLE</strong> — only your database administrator can grant
            those rights; the app cannot. Uses the credentials entered above.
          </span>
        </div>

        <label className="row" style={{ gap: 8 }}>
          <input
            type="checkbox"
            style={{ width: 'auto' }}
            checked={draft.useTLS}
            onChange={(e) => set('useTLS', e.target.checked)}
          />
          <span className="t-caption">Use TLS</span>
        </label>
        {draft.useTLS && (
          <div className="col" style={{ gap: 12, paddingLeft: 8 }}>
            <Field label="Certificate mode">
              <select
                className="text-input"
                value={draft.certModeRaw}
                onChange={(e) => set('certModeRaw', e.target.value)}
              >
                {CERT_MODES.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Fingerprint (SHA-256)">
              <input
                className="text-input"
                value={draft.fingerprint}
                placeholder="optional"
                onChange={(e) => set('fingerprint', e.target.value)}
              />
            </Field>
            <Field label="Minimum RSA key size">
              <input
                className="text-input"
                type="number"
                value={draft.minRSAKeySizeBits}
                onChange={(e) => set('minRSAKeySizeBits', Number(e.target.value) || 0)}
              />
            </Field>
          </div>
        )}

        <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
          LLM (optional)
        </span>
        <Field label="Server URL">
          <input
            className="text-input"
            value={draft.llmURL}
            placeholder="https://…"
            onChange={(e) => set('llmURL', e.target.value)}
          />
        </Field>
        <Field label="Model">
          <input
            className="text-input"
            value={draft.llmModel}
            onChange={(e) => set('llmModel', e.target.value)}
          />
        </Field>
        <Field label="API key">
          <input
            className="text-input"
            type="password"
            value={llmKey}
            autoComplete="new-password"
            placeholder={hasLLMKey ? '•••••• (unchanged)' : ''}
            onChange={(e) => {
              setLlmKey(e.target.value)
              setLlmKeyTouched(true)
            }}
          />
        </Field>

        <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
          Assigned users
        </span>
        {store.assignableUsers.length === 0 ? (
          <span className="t-caption2 fg-tertiary">No users available.</span>
        ) : (
          <div
            className="col"
            style={{
              gap: 2,
              maxHeight: 160,
              overflowY: 'auto',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: 8,
            }}
          >
            {store.assignableUsers.map((username) => (
              <label key={username} className="row" style={{ gap: 8 }}>
                <input
                  type="checkbox"
                  style={{ width: 'auto' }}
                  checked={draft.assignments.includes(username)}
                  onChange={() => toggleAssignment(username)}
                />
                <span className="t-caption">{username}</span>
              </label>
            ))}
          </div>
        )}
        </>
        )}

        {tab === 'demo' && (
          <div className="col" style={{ gap: 16 }}>
            <span className="t-caption2 fg-tertiary">
              Generate a ready-made dataset into this connection’s schema — it creates the
              schema and the process-mining tables if needed, then loads the journeys
              (replacing only that dataset’s own project). Needs a database account
              permitted to <strong>CREATE SCHEMA</strong>, <strong>CREATE TABLE</strong>{' '}
              and <strong>INSERT</strong> — only your database administrator can grant
              those; the app cannot. Uses the credentials on the Database / LLM Details
              tab.
            </span>

            <div className="col" style={{ gap: 6 }}>
              <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
                Retail
              </span>
              <DemoSection
                icon="📚"
                title="Online Bookstore"
                description="Order lifecycle: login → browse → basket → checkout → payment → fulfilment → delivery, with a returns flow and a deliberately flaky bank-transfer path. Each EVENT_ID is the MD5 hash of “ORD-000001”, “ORD-000002”, … (the prefix ORD- plus a 6-digit sequence number)."
                schema={draft.schema}
                onSchema={(v) => set('schema', v)}
                generate={(j) => runDemo('retail', j)}
              />
            </div>

            <div className="col" style={{ gap: 6 }}>
              <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
                Finance/Insurance
              </span>
              <DemoSection
                icon="💶🪙"
                title="Online Credit Application"
                description="Bank/affiliate intake → application check (with a rework loop) → credit assessment → score- and sum-driven approval with agent-review loops, ending in payment or rejection. Each EVENT_ID is the MD5 hash of “CRA-000001”, “CRA-000002”, … (the prefix CRA- plus a 6-digit sequence number)."
                schema={draft.schema}
                onSchema={(v) => set('schema', v)}
                generate={(j) => runDemo('finance', j)}
              />
            </div>

            <div className="col" style={{ gap: 6 }}>
              <span className="t-caption fg-secondary" style={{ fontWeight: 600 }}>
                Transportation
              </span>
              <DemoSection
                icon="✈️"
                title="Flight Booking & Management"
                description="Star Alliance-style booking: login → search (with a modify loop) → select → book → payment (Credit Card, SEPA, Apple Pay, Google Pay, Advance Payment) → confirm. 50% of bookings are interline (multi-airline) and query a partner airline’s system; 20% only manage an existing booking (seat reservation / ancillary services). Each EVENT_ID is the MD5 hash of “FLT-000001”, “FLT-000002”, … (the prefix FLT- plus a 6-digit sequence number)."
                schema={draft.schema}
                onSchema={(v) => set('schema', v)}
                generate={(j) => runDemo('transportation', j)}
              />
              <DemoSection
                icon="🛫"
                title="Airport Passenger Flow"
                description="A departing passenger’s terminal walk: departure hall → baggage drop / check-in → security → the airside amenities (duty free, lounge, dining) in any order → boarding. Passport Control switches the airside and boarding steps from their domestic (Dom) to their international (Int) variant; 2% leave the hall without travelling and 5% of boardings are denied. Loads into the “APF” project; defaults to 1,000,000 journeys (streamed, so the count is effectively unlimited). Each EVENT_ID is the MD5 hash of “APF-0000001”, “APF-0000002”, … (the prefix APF- plus a 7-digit sequence number)."
                schema={draft.schema}
                onSchema={(v) => set('schema', v)}
                generate={(j) => runDemo('airport', j)}
                defaultJourneys={1_000_000}
              />
            </div>
          </div>
        )}

        {tab === 'projects' && (
          <div className="col" style={{ gap: 12 }}>
            <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
              <span className="t-caption2 fg-tertiary" style={{ flex: 1 }}>
                Projects stored in the “{draft.schema.trim() || '…'}” schema, with their
                journey and event counts. Deleting a project clears its rows from every
                table (PROJECTS, JOURNEYS, STEPS, METAS, NOTES, TRANSITIONS_RAW) — this
                cannot be undone.
              </span>
              <button
                className="btn small"
                disabled={projectsBusy}
                onClick={() => void loadProjectsList()}
              >
                ↻ Refresh
              </button>
            </div>

            {projectsError && <span className="t-caption fg-red">{projectsError}</span>}

            {projectsBusy && projects === null ? (
              <span className="t-caption2 fg-tertiary row" style={{ gap: 6 }}>
                <Spinner /> Loading projects…
              </span>
            ) : projects && projects.length === 0 ? (
              <span className="t-caption2 fg-tertiary">
                No projects found in this schema.
              </span>
            ) : projects ? (
              <div
                className="col"
                style={{
                  gap: 2,
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: 8,
                }}
              >
                {projects.map((p) => (
                  <div
                    key={p.projectId}
                    className="row"
                    style={{ gap: 10, alignItems: 'center', padding: '4px 2px' }}
                  >
                    <div className="col" style={{ flex: 1, minWidth: 0, gap: 0 }}>
                      <span
                        className="t-caption"
                        style={{
                          fontWeight: 600,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {p.title}
                      </span>
                      {p.title !== p.titleShort && (
                        <span className="t-caption2 fg-tertiary">{p.titleShort}</span>
                      )}
                    </div>
                    <span className="t-caption2 fg-secondary" style={{ whiteSpace: 'nowrap' }}>
                      {p.journeys.toLocaleString()} journeys
                    </span>
                    <span className="t-caption2 fg-tertiary" style={{ whiteSpace: 'nowrap' }}>
                      {p.events.toLocaleString()} events
                    </span>
                    <button
                      className="btn small"
                      style={{ color: 'var(--red)' }}
                      disabled={projectsBusy}
                      onClick={() => setConfirmProject(p)}
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>

      {confirmDelete && (
        <ConfirmSheet
          title="Delete connection?"
          message={`“${draft.name}” will be removed for all assigned users. This cannot be undone.`}
          confirmLabel="Delete"
          destructive
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => void remove()}
        />
      )}

      {confirmProject && (
        <ConfirmSheet
          title="Delete project?"
          message={`“${confirmProject.title}” (${confirmProject.journeys.toLocaleString()} journeys, ${confirmProject.events.toLocaleString()} events) will be cleared from PROJECTS, JOURNEYS, STEPS, METAS, NOTES and TRANSITIONS_RAW in this schema. This cannot be undone.`}
          confirmLabel="Delete project"
          destructive
          onCancel={() => setConfirmProject(null)}
          onConfirm={() => void removeProject(confirmProject)}
        />
      )}
    </Sheet>
  )
}
