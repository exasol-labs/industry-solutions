/** Design several aggregates for one map: each banked group of connected steps becomes a
 *  Σ super-step in ONE high-level project, plus its own detail project (for drill-down),
 *  written to a chosen (possibly new) schema/connection. Developer-only.
 *
 *  Two modes: creating a NEW high-level map (asks for its name + target), or ADDING groups
 *  to an existing high-level map (the map is re-collapsed from its source on the server). */

import { useMemo, useState } from 'react'
import { api } from '../api'
import { validateAggregateSelection } from '../aggregate/connectivity'
import type { AggregateGroupInput, AggregateSetResult } from '../aggregate/types'
import { useStore } from '../store'
import type { ProcessTransition } from '../types'
import { Sheet, Spinner } from '../components/ui'

interface GroupForm {
  members: string[]
  sigmaName: string
  detailName: string
  detailConn: string
  detailSchema: string
}

function TargetRow({
  label,
  connId,
  schema,
  onConn,
  onSchema,
  connections,
}: {
  label: string
  connId: string
  schema: string
  onConn: (v: string) => void
  onSchema: (v: string) => void
  connections: { id: string; name: string }[]
}) {
  return (
    <div className="row" style={{ gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
      <div className="field" style={{ flex: '1 1 180px', margin: 0 }}>
        <label>{label} — connection</label>
        <select value={connId} onChange={(e) => onConn(e.target.value)}>
          {connections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field" style={{ flex: '1 1 160px', margin: 0 }}>
        <label>{label} — schema</label>
        <input
          value={schema}
          onChange={(e) => onSchema(e.target.value)}
          placeholder="same as connection (or a new name)"
        />
      </div>
    </div>
  )
}

export function AggregateSetDialog({
  groups,
  transitions,
  projectId,
  connectionId,
  projectTitle,
  addMode,
  onClose,
  onDone,
}: {
  /** Each entry is a banked group's member step names. */
  groups: string[][]
  transitions: ProcessTransition[]
  projectId: number
  connectionId: string
  projectTitle: string
  /** True when projectId is already a high-level map — we append rather than create. */
  addMode: boolean
  onClose: () => void
  onDone: (result: AggregateSetResult) => void
}) {
  const store = useStore()
  const conns = store.connections.map((c) => ({ id: c.id, name: c.name }))

  const [highName, setHighName] = useState(`${projectTitle} (aggregated)`)
  const [hiConn, setHiConn] = useState(connectionId)
  const [hiSchema, setHiSchema] = useState('')
  const [forms, setForms] = useState<GroupForm[]>(() =>
    groups.map((members, i) => ({
      members,
      sigmaName: `Σ ${members[0] ?? `Aggregate ${i + 1}`}`,
      detailName: `${projectTitle} — ${members[0] ?? `detail ${i + 1}`}`,
      detailConn: connectionId,
      detailSchema: '',
    })),
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const validations = useMemo(
    () => forms.map((f) => validateAggregateSelection(f.members, transitions)),
    [forms, transitions],
  )
  const allConnected = validations.every((v) => v.ok)
  const namesOk =
    forms.every((f) => f.sigmaName.trim() && f.detailName.trim()) && (addMode || highName.trim())
  const canCreate = allConnected && namesOk && !busy && forms.length > 0

  const patch = (i: number, p: Partial<GroupForm>) =>
    setForms((fs) => fs.map((f, j) => (j === i ? { ...f, ...p } : f)))

  const submit = async () => {
    setBusy(true)
    setError(null)
    const aggregates: AggregateGroupInput[] = forms.map((f) => ({
      sigmaName: f.sigmaName.trim(),
      members: f.members,
      detail: { name: f.detailName.trim(), targetConnectionId: f.detailConn, targetSchema: f.detailSchema.trim() },
    }))
    try {
      const result = addMode
        ? await api.addAggregates(projectId, { connectionId, aggregates })
        : await api.createAggregateSet(projectId, {
            connectionId,
            highLevel: { name: highName.trim(), targetConnectionId: hiConn, targetSchema: hiSchema.trim() },
            aggregates,
          })
      onDone(result)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet
      title={addMode ? 'Add aggregates to the map' : 'Create high-level map'}
      icon="Σ"
      onClose={onClose}
      footer={
        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          {busy && <Spinner />}
          {error && <span style={{ color: 'var(--red)', fontSize: 13 }}>{error}</span>}
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={!canCreate} onClick={() => void submit()}>
            {addMode ? 'Add' : 'Create'}
          </button>
        </div>
      }
    >
      <p className="fg-secondary" style={{ marginTop: 0, fontSize: 13 }}>
        {addMode
          ? `Adding ${forms.length} aggregate${forms.length === 1 ? '' : 's'} to this high-level map. The map is rebuilt from its source with every Σ step.`
          : `Building one high-level map with ${forms.length} Σ step${forms.length === 1 ? '' : 's'}. The original project is untouched.`}
      </p>

      {!addMode && (
        <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: 12, marginBottom: 6 }}>
          <div className="field" style={{ maxWidth: 420 }}>
            <label>High-level project name (the map holding the Σ nodes)</label>
            <input value={highName} onChange={(e) => setHighName(e.target.value)} />
          </div>
          <TargetRow
            label="High-level"
            connId={hiConn}
            schema={hiSchema}
            onConn={setHiConn}
            onSchema={setHiSchema}
            connections={conns}
          />
        </div>
      )}

      {forms.map((f, i) => (
        <div
          key={i}
          style={{ borderTop: i ? '1px solid var(--border)' : 'none', marginTop: i ? 12 : 0, paddingTop: 10 }}
        >
          <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
            <strong style={{ fontSize: 13 }}>Aggregate {i + 1}</strong>
            {f.members.map((m) => (
              <span
                key={m}
                className="t-caption2"
                style={{
                  background: 'var(--bg-tertiary-grouped, var(--bg-secondary))',
                  borderRadius: 6,
                  padding: '2px 8px',
                  color: validations[i].isolated.includes(m) ? 'var(--red)' : 'inherit',
                }}
              >
                {m}
              </span>
            ))}
          </div>
          {!validations[i].ok && (
            <p style={{ color: 'var(--red)', fontSize: 13, margin: '0 0 8px' }}>
              {validations[i].isolated.length
                ? `Not connected to the rest of the group: ${validations[i].isolated.join(', ')}.`
                : validations[i].components > 1
                  ? `These steps form ${validations[i].components} separate groups — they must be one connected group.`
                  : 'A group needs at least two connected steps.'}
            </p>
          )}
          <div className="field" style={{ maxWidth: 360 }}>
            <label>Σ step name</label>
            <input value={f.sigmaName} onChange={(e) => patch(i, { sigmaName: e.target.value })} />
          </div>
          <div className="field" style={{ maxWidth: 420 }}>
            <label>Detail project name (drill-down)</label>
            <input value={f.detailName} onChange={(e) => patch(i, { detailName: e.target.value })} />
          </div>
          <TargetRow
            label="Detail"
            connId={f.detailConn}
            schema={f.detailSchema}
            onConn={(v) => patch(i, { detailConn: v })}
            onSchema={(v) => patch(i, { detailSchema: v })}
            connections={conns}
          />
        </div>
      ))}

      <p className="fg-secondary" style={{ fontSize: 12, marginTop: 10 }}>
        Leave a schema blank to use the connection's own schema; type a new name to create one.
      </p>
    </Sheet>
  )
}
