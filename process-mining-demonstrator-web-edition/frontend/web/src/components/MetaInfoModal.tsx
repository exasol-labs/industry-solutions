/** The "Meta Infos" panel, opened from a flowchart node's context menu. Lists the META
 *  values that actually occur on THAT node's events, in three tabs (Meta_1/2/3), each
 *  searchable, and gives every value an Include / Exclude toggle — the list-based journey
 *  filter that mirrors the node Include/Exclude for steps. Each row shows a second field
 *  with the date/time the value was last seen (and its occurrence count); the search box
 *  matches the value and that date/time. */

import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import type { MetaEntry } from '../types'
import { Sheet } from './ui'

export function MetaInfoModal({ onClose }: { onClose: () => void }) {
  const meta1Title = useStore((s) => s.meta1Title)
  const meta2Title = useStore((s) => s.meta2Title)
  const meta3Title = useStore((s) => s.meta3Title)
  const node = useStore((s) => s.metaInfoNode)
  const projectId = useStore((s) => s.selectedProject?.projectId)
  const metaFilters = useStore((s) => s.metaFilters)
  const handleMetaAction = useStore((s) => s.handleMetaAction)
  const clearMetaFilters = useStore((s) => s.clearMetaFilters)

  // The values valid for this node, fetched when the panel opens.
  const [values, setValues] = useState<{ meta1: MetaEntry[]; meta2: MetaEntry[]; meta3: MetaEntry[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!node || projectId == null) return
    let cancelled = false
    setValues(null)
    setError(null)
    void api
      .nodeMetaValues(projectId, node, 'ORIGINAL')
      .then((v) => !cancelled && setValues(v))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
    return () => { cancelled = true }
  }, [node, projectId])

  const cols = useMemo(
    () => [
      { title: meta1Title, values: values?.meta1 ?? [] },
      { title: meta2Title, values: values?.meta2 ?? [] },
      { title: meta3Title, values: values?.meta3 ?? [] },
    ],
    [meta1Title, meta2Title, meta3Title, values],
  )
  const [tab, setTab] = useState(0)
  const [query, setQuery] = useState('')

  const active = cols[tab]
  const included = metaFilters.included[tab]
  const excluded = metaFilters.excluded[tab]
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const vals = active.values ?? []
    // Search matches the value AND its date/time, so a user can find by either.
    return q ? vals.filter((e) => `${e.value} ${e.time}`.toLowerCase().includes(q)) : vals
  }, [active.values, query])

  const activeCount = metaFilters.included.reduce((n, l) => n + l.length, 0) +
    metaFilters.excluded.reduce((n, l) => n + l.length, 0)

  return (
    <Sheet
      title={node ? `Meta Infos — ${node}` : 'Meta Infos'}
      icon="▤"
      onClose={onClose}
      footer={
        <>
          {activeCount > 0 && (
            <button className="btn small" onClick={() => clearMetaFilters()}>
              Clear meta filters ({activeCount})
            </button>
          )}
          <span className="spacer" />
          <button className="btn prominent" onClick={onClose}>Done</button>
        </>
      }
    >
      <div className="col" style={{ gap: 10, minWidth: 340 }}>
        {/* Tabs: one per META column. */}
        <div className="row" style={{ gap: 6 }}>
          {cols.map((c, i) => {
            const inc = metaFilters.included[i].length
            const exc = metaFilters.excluded[i].length
            return (
              <button
                key={i}
                className={`btn small${i === tab ? ' prominent' : ''}`}
                onClick={() => { setTab(i); setQuery('') }}
                style={{ flex: 1 }}
                title={c.title || `Meta ${i + 1}`}
              >
                <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {c.title || `Meta ${i + 1}`}
                  {inc + exc > 0 && <span className="fg-tertiary"> · {inc + exc}</span>}
                </span>
              </button>
            )
          })}
        </div>

        <input
          className="text-input"
          placeholder={`Search ${active.title || `Meta ${tab + 1}`} value or date…`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
          autoFocus
        />

        <div className="col" style={{ gap: 4, maxHeight: 360, overflowY: 'auto', paddingRight: 2 }}>
          {error ? (
            <span className="t-caption2 fg-red" style={{ padding: '8px 2px' }}>{error}</span>
          ) : values === null ? (
            <span className="t-caption2 fg-tertiary" style={{ padding: '8px 2px' }}>Loading…</span>
          ) : (active.values ?? []).length === 0 ? (
            <span className="t-caption2 fg-tertiary" style={{ padding: '8px 2px' }}>
              This node has no values in this column.
            </span>
          ) : filtered.length === 0 ? (
            <span className="t-caption2 fg-tertiary" style={{ padding: '8px 2px' }}>
              No values match “{query}”.
            </span>
          ) : (
            filtered.map((e) => {
              const isInc = included.includes(e.value)
              const isExc = excluded.includes(e.value)
              return (
                <div
                  key={e.value}
                  className="row"
                  style={{
                    gap: 8, alignItems: 'center', padding: '5px 8px', borderRadius: 6,
                    background: isInc ? 'color-mix(in srgb, transparent, var(--green) 14%)'
                      : isExc ? 'color-mix(in srgb, transparent, var(--red) 14%)' : 'var(--bg-fill)',
                  }}
                >
                  <div className="col" style={{ flex: 1, minWidth: 0, gap: 1 }}>
                    <span
                      title={e.value}
                      style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: 13 }}
                    >
                      {e.value || <span className="fg-tertiary">(empty)</span>}
                    </span>
                    <span
                      className="t-caption2 fg-tertiary"
                      title={e.count > 1 ? `Last seen ${e.time} · ${e.count} events` : e.time}
                      style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                    >
                      {e.time || '—'}{e.count > 1 && ` · ×${e.count}`}
                    </span>
                  </div>
                  <button
                    className="icon-btn"
                    title={isInc ? 'Included — click to clear' : 'Include journeys with this value'}
                    aria-label={`Include ${e.value}`}
                    aria-pressed={isInc}
                    onClick={() => handleMetaAction(tab, e.value, 'include')}
                    style={{ color: isInc ? 'var(--green)' : 'var(--secondary)', fontWeight: 700 }}
                  >
                    ⊕
                  </button>
                  <button
                    className="icon-btn"
                    title={isExc ? 'Excluded — click to clear' : 'Exclude journeys with this value'}
                    aria-label={`Exclude ${e.value}`}
                    aria-pressed={isExc}
                    onClick={() => handleMetaAction(tab, e.value, 'exclude')}
                    style={{ color: isExc ? 'var(--red)' : 'var(--secondary)', fontWeight: 700 }}
                  >
                    ⊖
                  </button>
                </div>
              )
            })
          )}
        </div>

        <span className="t-caption2 fg-tertiary">
          ⊕ keeps only journeys that have an event with the value; ⊖ drops journeys that
          have it. Same as a step Include/Exclude, per Meta column.
        </span>
      </div>
    </Sheet>
  )
}
