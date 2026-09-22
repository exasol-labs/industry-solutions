/** KPI tiles — port of the `kpiPanel` / `singleChartKPITile` / `abPanelKPITile`
 *  section of ProcessMapView.swift. Order and visibility come from settings. */

import { useMemo, useState } from 'react'
import { formatDateShort, formatDurationLong } from '../graph/format'
import { readSetting, useSetting } from '../settings'
import { useStore, type ABSide, type Store } from '../store'
import {
  KPI_DEFAULT_ORDER,
  KPI_META,
  sampleShortLabel,
  type DurationStats,
  type ProcessGraph,
} from '../types'
import { Spinner } from './ui'

/** Σ (score × visits) over scored nodes; visits = max(incoming, outgoing). */
export function graphValue(graph: ProcessGraph): number | null {
  if (graph.transitions.length === 0) return null
  const incoming: Record<string, number> = {}
  const outgoing: Record<string, number> = {}
  for (const t of graph.transitions) {
    incoming[t.toStep] = (incoming[t.toStep] ?? 0) + t.occurrences
    outgoing[t.fromStep] = (outgoing[t.fromStep] ?? 0) + t.occurrences
  }
  let total = 0
  let hasScore = false
  for (const [name, step] of Object.entries(graph.steps)) {
    if (step.score == null) continue
    const visits = Math.max(incoming[name] ?? 0, outgoing[name] ?? 0)
    if (visits <= 0) continue
    total += step.score * visits
    hasScore = true
  }
  return hasScore ? total : null
}

function signed(value: number, digits = 0): string {
  const formatted =
    digits > 0 ? Math.abs(value).toFixed(digits) : Math.abs(value).toLocaleString()
  return `${value < 0 ? '−' : '+'}${formatted}`
}

/** Drag-to-reorder + hover-to-remove wiring for a strip tile. Absent on the fixed
 *  Individual-Journey tiles, which are neither reorderable nor removable. */
export interface KpiDnd {
  dragging: boolean
  onDragStart: () => void
  onDragEnd: () => void
  onDropOn: () => void
  onRemove?: () => void
}

export function KpiTile({
  label,
  icon,
  value,
  loading = false,
  color,
  dnd,
}: {
  label: string
  icon: string
  value: string
  loading?: boolean
  color?: string
  dnd?: KpiDnd
}) {
  return (
    <div
      className={`kpi-tile${dnd ? ' draggable' : ''}${dnd?.dragging ? ' dragging' : ''}`}
      style={color ? { borderColor: color, borderWidth: 1.5 } : undefined}
      draggable={dnd ? true : undefined}
      onDragStart={dnd?.onDragStart}
      onDragEnd={dnd?.onDragEnd}
      onDragOver={dnd ? (e) => e.preventDefault() : undefined}
      onDrop={dnd?.onDropOn}
    >
      {dnd?.onRemove && (
        <button
          className="kpi-remove"
          title={`Hide ${label}`}
          aria-label={`Hide ${label}`}
          draggable={false}
          onDragStart={(e) => e.preventDefault()}
          onClick={dnd.onRemove}
        >
          ×
        </button>
      )}
      <div className="kpi-label">
        <span aria-hidden style={{ color: color ?? 'var(--accent)' }}>
          {icon}
        </span>
        <span className="truncate">{label}</span>
      </div>
      {loading ? (
        <div style={{ height: 22, display: 'flex', alignItems: 'center' }}>
          <Spinner />
        </div>
      ) : (
        <span className="kpi-value truncate" style={color ? { color } : undefined}>
          {value}
        </span>
      )}
    </div>
  )
}

export function useOrderedKpiIds(): string[] {
  const [order] = useSetting<string>('kpi.order')
  return useMemo(() => {
    const stored = order.split(',').filter(Boolean)
    const all = KPI_DEFAULT_ORDER.split(',')
    return [...stored, ...all.filter((id) => !stored.includes(id))]
  }, [order])
}

interface TileInputs {
  graph: ProcessGraph
  journeyCount: number | null
  durations: DurationStats
  goodness: number | null
  /** Present in A/B mode — drives the green/red comparison colour. */
  otherGoodness?: number | null
  side?: ABSide
  loading: boolean
}

interface KpiTileSpec {
  label: string
  icon: string
  value: string
  loading?: boolean
  color?: string
}

/** The display values for one KPI by id, or null when it has no data / doesn't apply
 *  (e.g. graph value without scores, similarity outside A/B). Pure — no visibility. */
function tileSpec(id: string, store: Store, inputs: TileInputs): KpiTileSpec | null {
  const meta = KPI_META[id]
  if (!meta) return null
  const { graph, journeyCount, durations, goodness, otherGoodness, side, loading } =
    inputs

  switch (id) {
    case 'totalJourneys':
      return {
        label: meta.label,
        icon: meta.icon,
        value: store.totalJourneyCount?.toLocaleString() ?? '—',
        loading: loading && store.totalJourneyCount == null,
      }
    case 'filteredJourneys':
      return {
        label: meta.label,
        icon: meta.icon,
        value: journeyCount?.toLocaleString() ?? '—',
        loading,
      }
    case 'shortestJourney':
      return { label: meta.label, icon: meta.icon, value: formatDurationLong(durations.minSecs), loading }
    case 'avgJourney':
      return { label: meta.label, icon: meta.icon, value: formatDurationLong(durations.avgSecs), loading }
    case 'medianJourney':
      return { label: meta.label, icon: meta.icon, value: formatDurationLong(durations.medianSecs), loading }
    case 'stdDev':
      return { label: meta.label, icon: meta.icon, value: formatDurationLong(durations.stdDevSecs), loading }
    case 'longestJourney':
      return { label: meta.label, icon: meta.icon, value: formatDurationLong(durations.maxSecs), loading }
    case 'graphValue': {
      const value = graphValue(graph)
      if (value == null) return null
      return { label: meta.label, icon: meta.icon, value: signed(value), loading }
    }
    case 'processGoodness': {
      if (goodness == null) return null
      let color: string | undefined
      if (otherGoodness != null) {
        color =
          Math.abs(goodness - otherGoodness) < 0.005
            ? 'var(--blue)'
            : goodness > otherGoodness
              ? 'var(--green)'
              : 'var(--red)'
      }
      return { label: meta.label, icon: meta.icon, value: signed(goodness, 2), loading, color }
    }
    case 'processSimilarity': {
      // A/B Comparison only — it compares the two panels, so it is meaningless (and must
      // never appear) on A-Chart, B-Chart, Statistics or any other single-process view,
      // even when a stale score from an earlier A/B run lingers in the store.
      if (store.activeChartMode !== 'A/B Comparison') return null
      if (store.abSimilarityScore == null) return null
      const q = store.abSimilarityScore
      return {
        label: meta.label,
        icon: meta.icon,
        value: q.toFixed(2),
        color: q >= 0.7 ? 'var(--green)' : q <= 0.3 ? 'var(--red)' : 'var(--blue)',
      }
    }
    case 'activeSample': {
      // Reflect the side's actual data source: a sample set, or a Sim-A/Sim-B
      // simulation (which otherwise leaves the stale sample-set label showing).
      const source = (side ?? 'a') === 'a' ? store.abDataSourceA : store.abDataSourceB
      if (source.kind === 'simulation') {
        const result = source.slot === 'Sim-A' ? store.simResultA : store.simResultB
        return { label: source.slot, icon: meta.icon, value: result?.totalJourneys?.toLocaleString() ?? '—' }
      }
      const count = store.sampleCounts[source.sampleSet] ?? store.totalJourneyCount
      return { label: sampleShortLabel(source.sampleSet), icon: meta.icon, value: count?.toLocaleString() ?? '—' }
    }
    default:
      return null
  }
}

/** One strip tile: honours its `kpi.show.<id>` flag and carries the drag-reorder +
 *  hover-remove affordances. The × writes the same `kpi.show.<id>` the left-panel
 *  toggle does, so the panel and strip stay in lock-step (and persist per user). */
function Tile({
  id,
  inputs,
  dnd,
}: {
  id: string
  inputs: TileInputs
  dnd: Omit<KpiDnd, 'onRemove'>
}) {
  const store = useStore()
  const [visible, setVisible] = useSetting<boolean>(`kpi.show.${id}`, true)
  if (!visible) return null
  const spec = tileSpec(id, store, inputs)
  if (!spec) return null
  return <KpiTile {...spec} dnd={{ ...dnd, onRemove: () => setVisible(false) }} />
}

export function KpiStrip(inputs: TileInputs) {
  const ids = useOrderedKpiIds()
  const [, setOrder] = useSetting<string>('kpi.order')
  const [dragging, setDragging] = useState<string | null>(null)

  // Reorder the FULL id list (same as the left-panel Configuration → KPIs list), so the
  // two views share one `kpi.order`. Dragging a strip tile onto another moves it there.
  const reorder = (dragId: string, targetId: string) => {
    if (dragId === targetId) return
    const arr = ids.filter((x) => x !== dragId)
    const index = arr.indexOf(targetId)
    arr.splice(index < 0 ? arr.length : index, 0, dragId)
    setOrder(arr.join(','))
  }

  return (
    <div className="kpi-strip">
      {ids.map((id) => (
        <Tile
          key={id}
          id={id}
          inputs={inputs}
          dnd={{
            dragging: dragging === id,
            onDragStart: () => setDragging(id),
            onDragEnd: () => setDragging(null),
            onDropOn: () => {
              if (dragging) reorder(dragging, id)
            },
          }}
        />
      ))}
    </div>
  )
}

/** Individual-Journey mode replaces the standard tiles with journey facts. */
export function JourneyKpiStrip() {
  const store = useStore()
  const graph = store.processGraph

  const durationSecs =
    store.journeyDate && store.journeyEndDate
      ? (new Date(store.journeyEndDate).getTime() -
          new Date(store.journeyDate).getTime()) /
        1000
      : null

  const scoreSum = useMemo(() => {
    let total = 0
    let hasScore = false
    for (const step of Object.values(graph.steps)) {
      if (step.score == null) continue
      total += step.score
      hasScore = true
    }
    return hasScore ? total : null
  }, [graph])

  const stepStats = useMemo(() => {
    const distinct = Object.keys(graph.steps).length
    const total = graph.transitions.reduce((sum, t) => sum + t.occurrences, 0) + 1
    return { total, distinct }
  }, [graph])

  const metaTiles: { label: string; value: string }[] = []
  if (store.meta1Title && store.journeyMeta1)
    metaTiles.push({ label: store.meta1Title, value: store.journeyMeta1 })
  if (store.meta2Title && store.journeyMeta2)
    metaTiles.push({ label: store.meta2Title, value: store.journeyMeta2 })
  if (store.meta3Title && store.journeyMeta3)
    metaTiles.push({ label: store.meta3Title, value: store.journeyMeta3 })

  return (
    <div className="kpi-strip">
      <KpiTile
        label="Date"
        icon="📅"
        value={store.journeyDate ? formatDateShort(store.journeyDate) : '—'}
        loading={store.isLoading}
      />
      <KpiTile
        label="Duration"
        icon="⏱️"
        value={formatDurationLong(durationSecs)}
        loading={store.isLoading}
      />
      <KpiTile
        label="Sum of Scores"
        icon="ƒ"
        value={scoreSum == null ? '—' : signed(scoreSum)}
        loading={store.isLoading}
      />
      <KpiTile
        label="Steps visited / distinct"
        icon="⑂"
        value={`${stepStats.total} / ${stepStats.distinct}`}
        loading={store.isLoading}
      />
      {metaTiles.map((tile) => (
        <KpiTile key={tile.label} label={tile.label} icon="🏷" value={tile.value} />
      ))}
    </div>
  )
}

export { readSetting }
