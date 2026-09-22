/** A/B Comparison — ports `abComparisonContent` / `abPanel` / `valveButton`.
 *
 * A is the master viewport. With the valve open both panels share one
 * `SyncState`, so pan, zoom and node drags mirror; closing the valve snapshots
 * A's state into B's own copy so they move independently from then on. */

import { useCallback, useMemo, useRef, useState } from 'react'
import { KpiStrip } from '../components/KpiStrip'
import { Chevron, Unavailable } from '../components/ui'
import { FlowChart, createSyncState, type SyncState } from '../flow/FlowChart'
import { useSetting } from '../settings'
import { useStore, type ABSide } from '../store'
import { simulationFilterNotice, type SliderMode } from '../types'
import { ChartControls } from './ChartControls'
import { useNoteHandlers } from './useNoteHandlers'

export function ABComparison() {
  const store = useStore()
  const [valveOpen, setValveOpen] = useSetting<boolean>('abComparison.valveOpen')
  const [flowHorizontal, setFlowHorizontal] = useSetting<boolean>('graph.flowHorizontal')
  const notes = useNoteHandlers()

  const masterSync = useRef<SyncState>(createSyncState())
  const bSync = useRef<SyncState>(createSyncState())
  const [, forceRender] = useState(0)
  const onSyncChange = useCallback(() => forceRender((n) => n + 1), [])

  const toggleValve = () => {
    if (valveOpen) {
      // Closing: B keeps A's current viewport and node positions.
      bSync.current = {
        viewport: masterSync.current.viewport,
        nodeOverrides: { ...masterSync.current.nodeOverrides },
        version: 0,
      }
    }
    setValveOpen(!valveOpen)
  }

  const toggleHorizontal = () => {
    // An orientation change invalidates the shared drag positions (they're in the old
    // layout axis), so clear the sync overrides and viewport — both panels then re-layout
    // and re-fit fresh in the new orientation.
    masterSync.current = { viewport: null, nodeOverrides: {}, version: masterSync.current.version + 1 }
    bSync.current = { viewport: null, nodeOverrides: {}, version: bSync.current.version + 1 }
    setFlowHorizontal(!flowHorizontal)
    forceRender((n) => n + 1)
  }

  const copyLayoutAtoB = () => {
    bSync.current = {
      viewport: masterSync.current.viewport,
      nodeOverrides: { ...masterSync.current.nodeOverrides },
      version: bSync.current.version + 1,
    }
    forceRender((n) => n + 1)
  }

  if (!store.selectedProject) {
    return (
      <Unavailable
        glyph="🗺"
        title="No Project Selected"
        description="Select a project from the sidebar."
      />
    )
  }

  const similarity = store.abSimilarityScore

  return (
    <div className="ab-wrap">
      <div className="ab-split" style={{ position: 'relative' }}>
      <ABPanel
        side="a"
        syncState={masterSync.current}
        onSyncChange={onSyncChange}
        onCopyLayout={copyLayoutAtoB}
        horizontal={flowHorizontal}
        notes={notes}
      />
      <div className="ab-divider">
        <button
          className={`valve-btn${valveOpen ? ' open' : ''}`}
          onClick={toggleValve}
          title={
            valveOpen
              ? 'Valve open — pan, zoom and reset are synchronised'
              : 'Valve closed — charts move independently'
          }
          aria-label={valveOpen ? 'Sync viewport: on' : 'Sync viewport: off'}
        >
          ⇄
        </button>
        <button
          className="valve-btn"
          onClick={toggleHorizontal}
          title={
            flowHorizontal
              ? 'Flowchart layout: left-to-right — switch to top-down'
              : 'Flowchart layout: top-down — switch to left-to-right'
          }
          aria-label={flowHorizontal ? 'Layout: horizontal' : 'Layout: top-down'}
        >
          {flowHorizontal ? '⬇' : '➡'}
        </button>
      </div>
      <ABPanel
        side="b"
        syncState={valveOpen ? masterSync.current : bSync.current}
        onSyncChange={onSyncChange}
        skipInitialFit={valveOpen || bSync.current.viewport != null}
        horizontal={flowHorizontal}
        notes={notes}
      />

      {notes.element}
      </div>

      {similarity != null && (
        <div className="ab-similarity-row">
          <div className="similarity-badge">
            <span aria-hidden>⇄</span>
            <span>Similarity</span>
            <span
              className="value"
              style={{
                color:
                  similarity >= 0.7
                    ? 'var(--green)'
                    : similarity <= 0.3
                      ? 'var(--red)'
                      : 'var(--blue)',
              }}
            >
              {similarity.toFixed(2)}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

function ABPanel({
  side,
  syncState,
  onSyncChange,
  skipInitialFit = false,
  onCopyLayout,
  horizontal = false,
  notes,
}: {
  side: ABSide
  syncState: SyncState
  onSyncChange: () => void
  skipInitialFit?: boolean
  onCopyLayout?: () => void
  horizontal?: boolean
  notes: ReturnType<typeof useNoteHandlers>
}) {
  const store = useStore()
  const [sliderMode] = useSetting<SliderMode>('slider.mode')
  const [kpiExpanded, setKpiExpanded] = useSetting<boolean>(
    side === 'a' ? 'abpanel.a.kpiExpanded' : 'abpanel.b.kpiExpanded',
  )
  const [controlsExpanded, setControlsExpanded] = useSetting<boolean>(
    side === 'a' ? 'abpanel.a.controlsExpanded' : 'abpanel.b.controlsExpanded',
  )

  const graph = side === 'a' ? store.abGraphA : store.abGraphB
  const journeyCount = side === 'a' ? store.abJourneyCountA : store.abJourneyCountB
  const durations = side === 'a' ? store.abDurationsA : store.abDurationsB
  const goodness = side === 'a' ? store.abGoodnessA : store.abGoodnessB
  const otherGoodness = side === 'a' ? store.abGoodnessB : store.abGoodnessA
  const metric = side === 'a' ? store.abMetricA : store.abMetricB
  const loading = side === 'a' ? store.isLoadingA : store.isLoadingB
  const isActive = store.abActiveSide === side
  const label = side === 'a' ? 'A-Chart' : 'B-Chart'

  const savedState = store.savedChartStates[label]
  const [sliderFrom, setSliderFrom] = useState(savedState?.fromDate ?? store.fromDate)
  const [sliderTo, setSliderTo] = useState(savedState?.toDate ?? store.toDate)

  const rangeMin = useMemo(
    () =>
      store.projectMinDate < store.initialToDate
        ? store.projectMinDate
        : store.initialFromDate,
    [store.projectMinDate, store.initialToDate, store.initialFromDate],
  )

  const hasData = graph.transitions.length > 0

  return (
    <div className="ab-panel">
      <div className={`ab-panel-head${isActive ? ' active' : ''}`}>
        <button className="side-btn" onClick={() => store.switchABSide(side)}>
          <span aria-hidden>{isActive ? '✎' : '○'}</span>
          {label}
          {isActive && <span className="t-caption2">· editing</span>}
        </button>
        {side === 'a' && hasData && onCopyLayout && (
          <button
            className="icon-btn"
            style={{ color: 'var(--secondary)', fontSize: 13 }}
            title="Copy A's node layout to B"
            onClick={onCopyLayout}
          >
            ⧉
          </button>
        )}
        {journeyCount != null && (
          <span className="t-caption2 fg-secondary tnum" style={{ padding: '0 6px' }}>
            {journeyCount.toLocaleString()} journeys
          </span>
        )}
        {hasData && (
          <button
            className="icon-btn"
            style={{ fontSize: 11, color: 'var(--secondary)' }}
            title={kpiExpanded ? 'Hide KPIs' : 'Show KPIs'}
            onClick={() => setKpiExpanded(!kpiExpanded)}
          >
            <Chevron open={kpiExpanded} />
          </button>
        )}
      </div>

      {hasData && kpiExpanded && (
        <KpiStrip
          graph={graph}
          journeyCount={journeyCount}
          durations={durations}
          goodness={goodness}
          otherGoodness={otherGoodness}
          side={side}
          loading={loading}
        />
      )}

      {hasData && (
        <ChartControls
          expanded={controlsExpanded}
          onToggleExpanded={() => setControlsExpanded(!controlsExpanded)}
          sliderMode={sliderMode}
          rangeMin={rangeMin}
          rangeMax={store.initialToDate}
          fromDate={sliderFrom}
          toDate={sliderTo}
          onSliderChange={(from, to) => {
            setSliderFrom(from)
            setSliderTo(to)
          }}
          onSliderCommit={(from, to) => {
            if (sliderMode === 'Day') {
              void store.reloadABSideForDay(side, from).then((actual) => {
                if (actual && actual !== from) {
                  setSliderFrom(actual)
                  setSliderTo(actual)
                }
              })
            } else {
              void store.reloadABSide(side, from, to)
            }
          }}
          metric={metric}
          onMetricChange={(m) => store.setABMetric(m, side)}
          metricsDisabled={!hasData}
          selectedPresetId={
            side === 'a' ? store.abFilterGroupIdA : store.abFilterGroupIdB
          }
          onApplyPreset={(group) => {
            store.switchABSide(side)
            store.applyFilterGroup(group)
            store.patch(
              side === 'a'
                ? { abFilterGroupIdA: group.id }
                : { abFilterGroupIdB: group.id },
            )
            setSliderFrom(group.fromDate.slice(0, 10))
            setSliderTo(group.toDate.slice(0, 10))
            void store.reloadGraph()
          }}
        />
      )}

      {!hasData ? (
        loading ? (
          <div className="center-fill">
            <span className="spinner large" />
            <span>Loading {label}</span>
          </div>
        ) : (
          <Unavailable
            glyph="📈"
            title={label}
            description={
              isActive
                ? 'Apply filters in the sidebar to load.'
                : 'Tap the header to make this side active, then load.'
            }
            action={
              <button
                className="btn prominent"
                onClick={() => {
                  store.switchABSide(side)
                  void store.reloadGraph()
                }}
              >
                Load
              </button>
            }
          />
        )
      ) : (
        <FlowChart
          // Remount on orientation change so the panel re-seeds and re-fits the new axis.
          key={`ab:${side}:${horizontal ? 'h' : 'v'}`}
          graph={graph}
          projectId={store.selectedProject?.projectId ?? 0}
          chartMode={label}
          metric={metric}
          journeyTotal={(side === 'a' ? store.abJourneyCountA : store.abJourneyCountB) ?? 0}
          horizontal={horizontal}
          allowTransitionTable
          isLoading={loading}
          syncState={syncState}
          notice={simulationFilterNotice(
            side === 'a' ? store.abDataSourceA : store.abDataSourceB,
          )}
          readOnly={
            (side === 'a' ? store.abDataSourceA : store.abDataSourceB).kind ===
            'simulation'
          }
          onSyncChange={onSyncChange}
          skipInitialFit={skipInitialFit}
          onNodeAction={(node, action) => {
            store.switchABSide(side)
            store.handleNodeAction(node, action)
          }}
          onMetaInfo={(node) => store.openMetaInfo(node)}
          notes={store.projectNotes}
          onNodeNote={notes.openNodeNotes}
          onEdgeNote={notes.openEdgeNotes}
        />
      )}
    </div>
  )
}
