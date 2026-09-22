/** The transition table behind a process map.
 *
 *  Every edge on the flowchart is one row of the directly-follows graph: a (from → to)
 *  pair with its occurrence count and elapsed-time statistics. This panel shows that
 *  underlying table in full — the raw data the chart is drawn from — with search and
 *  column sorting, so a user can read the exact numbers rather than eyeball edge widths.
 *  Opened from the ▦ button on the A-Chart / B-Chart / A-B panels (off by default; enabled
 *  under Configuration → Layout).
 */

import { useMemo, useState } from 'react'
import { Sheet } from '../components/ui'
import { formatCount, formatDuration, formatPercent } from '../graph/format'
import {
  journeyPercentage,
  outgoingPercentage,
  type ProcessGraph,
  type ProcessTransition,
} from '../types'

type SortKey = 'from' | 'to' | 'count' | 'pct' | 'jpct' | 'avg' | 'median' | 'min' | 'max' | 'std'

const NUM_KEYS: ReadonlySet<SortKey> = new Set(['count', 'pct', 'jpct', 'avg', 'median', 'min', 'max', 'std'])

/** The sort value for a row under a given key; nulls sort to the end regardless of order. */
function sortValue(
  t: ProcessTransition,
  key: SortKey,
  outgoingTotals: Map<string, number>,
  journeyTotal: number,
): number | string | null {
  switch (key) {
    case 'from':
      return t.fromStep
    case 'to':
      return t.toStep
    case 'count':
      return t.occurrences
    case 'pct':
      return outgoingPercentage(t, outgoingTotals.get(t.fromStep) ?? 0)
    case 'jpct':
      return journeyPercentage(t, journeyTotal)
    case 'avg':
      return t.avgSecs
    case 'median':
      return t.medianSecs
    case 'min':
      return t.minSecs
    case 'max':
      return t.maxSecs
    case 'std':
      return t.stdDevSecs
  }
}

const time = (v: number | null) => (v == null ? '—' : formatDuration(v))

export function TransitionTablePanel({
  graph,
  journeyTotal,
  title,
  onClose,
}: {
  graph: ProcessGraph
  journeyTotal: number
  title: string
  onClose: () => void
}) {
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('count')
  const [asc, setAsc] = useState(false)
  const [copied, setCopied] = useState(false)

  // Occurrences leaving each source node — the denominator for the outgoing-share %.
  const outgoingTotals = useMemo(() => {
    const m = new Map<string, number>()
    for (const t of graph.transitions) {
      m.set(t.fromStep, (m.get(t.fromStep) ?? 0) + t.occurrences)
    }
    return m
  }, [graph.transitions])

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = q
      ? graph.transitions.filter(
          (t) =>
            t.fromStep.toLowerCase().includes(q) || t.toStep.toLowerCase().includes(q),
        )
      : graph.transitions
    const dir = asc ? 1 : -1
    return [...filtered].sort((a, b) => {
      const va = sortValue(a, sortKey, outgoingTotals, journeyTotal)
      const vb = sortValue(b, sortKey, outgoingTotals, journeyTotal)
      // Nulls always last, whichever direction.
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      if (typeof va === 'string' && typeof vb === 'string') return dir * va.localeCompare(vb)
      return dir * ((va as number) - (vb as number))
    })
  }, [graph.transitions, search, sortKey, asc, outgoingTotals, journeyTotal])

  const totalOccurrences = useMemo(
    () => graph.transitions.reduce((s, t) => s + t.occurrences, 0),
    [graph.transitions],
  )

  // Copy the *visible* rows (current filter + sort order) as tab-separated values, so they
  // paste straight into a spreadsheet. Times are raw seconds (blank when unavailable) and
  // shares are plain numbers, which is far more useful for analysis than the "17m" / "71%"
  // display strings. Step names are stripped of tabs/newlines so columns never break.
  const copyTsv = async () => {
    const cell = (s: string) => s.replace(/[\t\r\n]+/g, ' ')
    const round2 = (n: number) => Math.round(n * 100) / 100
    const header = [
      'From', 'To', 'Count', '% Outgoing', 'Journey %', 'Avg (s)', 'Median (s)', 'Min (s)', 'Max (s)', 'Std Dev (s)',
    ]
    const lines = [header.join('\t')]
    for (const t of rows) {
      lines.push(
        [
          cell(t.fromStep),
          cell(t.toStep),
          t.occurrences,
          round2(outgoingPercentage(t, outgoingTotals.get(t.fromStep) ?? 0)),
          round2(journeyPercentage(t, journeyTotal)),
          t.avgSecs ?? '',
          t.medianSecs ?? '',
          t.minSecs ?? '',
          t.maxSecs ?? '',
          t.stdDevSecs ?? '',
        ].join('\t'),
      )
    }
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  const sort = (key: SortKey) => {
    if (key === sortKey) setAsc((v) => !v)
    else {
      setSortKey(key)
      // Text columns read best ascending; numeric columns default to largest-first.
      setAsc(!NUM_KEYS.has(key))
    }
  }

  const Th = ({ k, label, num }: { k: SortKey; label: string; num?: boolean }) => (
    <th
      className={`ttable-th${num ? ' num' : ''}${sortKey === k ? ' sorted' : ''}`}
      onClick={() => sort(k)}
      title={`Sort by ${label}`}
    >
      {label}
      {sortKey === k && <span className="ttable-caret">{asc ? ' ▲' : ' ▼'}</span>}
    </th>
  )

  return (
    <Sheet title={`Transition table — ${title}`} icon="▦" wide onClose={onClose}>
      <div className="ttable-toolbar">
        <div className="search-row" style={{ maxWidth: 260 }}>
          <span aria-hidden className="fg-secondary">🔍</span>
          <input
            value={search}
            placeholder="Filter by step name"
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button className="fg-secondary" onClick={() => setSearch('')} title="Clear">
              ⊗
            </button>
          )}
        </div>
        <div className="row" style={{ gap: 10, alignItems: 'center' }}>
          <span className="t-caption2 fg-tertiary">
            {rows.length} of {graph.transitions.length} transitions ·{' '}
            {formatCount(totalOccurrences)} occurrences total
          </span>
          <button
            className="btn small"
            onClick={copyTsv}
            disabled={rows.length === 0}
            title="Copy the visible rows as tab-separated values (paste into a spreadsheet)"
          >
            {copied ? '✓ Copied' : '⧉ Copy'}
          </button>
        </div>
      </div>

      <div className="ttable-scroll">
        <table className="ttable">
          <thead>
            <tr>
              <Th k="from" label="From" />
              <Th k="to" label="To" />
              <Th k="count" label="# Count" num />
              <Th k="pct" label="% Outgoing" num />
              <Th k="jpct" label="Journey %" num />
              <Th k="avg" label="Avg Time" num />
              <Th k="median" label="Median Time" num />
              <Th k="min" label="Min Time" num />
              <Th k="max" label="Max Time" num />
              <Th k="std" label="Std Dev" num />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="ttable-empty">
                  No transitions match “{search}”.
                </td>
              </tr>
            ) : (
              rows.map((t) => {
                const selfLoop = t.fromStep === t.toStep
                return (
                  <tr key={`${t.fromStep}->${t.toStep}`} className={selfLoop ? 'self' : ''}>
                    <td className="truncate">{t.fromStep}</td>
                    <td className="truncate">
                      {selfLoop ? <span title="Self-loop">↺ {t.toStep}</span> : t.toStep}
                    </td>
                    <td className="num">{formatCount(t.occurrences)}</td>
                    <td className="num">
                      {formatPercent(outgoingPercentage(t, outgoingTotals.get(t.fromStep) ?? 0))}
                    </td>
                    <td className="num">{formatPercent(journeyPercentage(t, journeyTotal))}</td>
                    <td className="num">{time(t.avgSecs)}</td>
                    <td className="num">{time(t.medianSecs)}</td>
                    <td className="num">{time(t.minSecs)}</td>
                    <td className="num">{time(t.maxSecs)}</td>
                    <td className="num">{time(t.stdDevSecs)}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </Sheet>
  )
}
