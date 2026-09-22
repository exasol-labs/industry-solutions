/** A-Chart / B-Chart panel — ports `aChartContent` / `bChartContent`. */

import { useEffect, useMemo, useState } from 'react'
import { FlowChart, type SyncState } from '../flow/FlowChart'
import { SankeyChart } from '../flow/SankeyChart'
import { Sheet, Unavailable } from '../components/ui'
import { ActionFlowchart } from '../components/ActionFlowchart'
import { useSetting } from '../settings'
import { useStore } from '../store'
import { simulationFilterNotice, TRANSITION_METRICS, type SliderMode } from '../types'
import { ChartControls } from './ChartControls'
import { useNoteHandlers } from './useNoteHandlers'
import { api } from '../api'
import { resolveScope } from '../actions/resolveScope'
import type { ActionRunResult, SavedAction } from '../actions/types'
import { ActionResultModal } from './ActionResultModal'
import { AggregateSetDialog } from './AggregateSetDialog'

export function ChartView({
  side,
  syncState,
}: {
  side: 'a' | 'b'
  syncState?: SyncState | null
}) {
  const store = useStore()
  const [sliderMode] = useSetting<SliderMode>('slider.mode')
  const [sankey, setSankey] = useSetting<boolean>('graph.sankeyView')
  const [flowHorizontal, setFlowHorizontal] = useSetting<boolean>('graph.flowHorizontal')
  const [expanded, setExpanded] = useSetting<boolean>(
    side === 'a' ? 'achart.controlsExpanded' : 'bchart.controlsExpanded',
  )
  const [sliderFrom, setSliderFrom] = useState(store.fromDate)
  const [sliderTo, setSliderTo] = useState(store.toDate)
  const notes = useNoteHandlers()

  // Node-menu actions: available to run for power/dev/admin when the feature is enabled.
  const runRole = store.authIsPower || store.authIsDeveloper || store.authIsAdmin
  const actionItems = store.actionsEnabled && runRole ? store.projectActions : []
  const [actionModal, setActionModal] = useState<{
    title: string
    result: ActionRunResult | null
    busy: boolean
    error: string | null
  } | null>(null)

  // Aggregate designer: developers can collapse a connected step selection into a Σ step.
  const canAggregate = store.authIsDeveloper || store.authIsAdmin
  const [aggregateGroups, setAggregateGroups] = useState<string[][] | null>(null)

  // A drill-down detail project (id "aggd_…") is a black-box sub-process: no Sankey, and a
  // Return button back to the high-level map it was reached from.
  const isDetailProject = !!store.selectedProject?.titleShort?.startsWith('#')
  // In-place drill: the detail graph is shown in this canvas (high-level project stays
  // selected). Treated like a detail view (no Sankey) with a Drill-up affordance.
  const inPlace = store.inPlaceDrill
  // Stable seed for the explode layout (recomputed only when the drill actually changes).
  const explodeSeed = useMemo(
    () =>
      inPlace && store.selectedProject
        ? {
            baseGraph: store.processGraph,
            baseProjectId: store.selectedProject.projectId,
            baseChartMode: side === 'a' ? ('A-Chart' as const) : ('B-Chart' as const),
            aggregates: inPlace.source.aggregates,
            expanded: inPlace.expanded,
          }
        : undefined,
    [inPlace, store.processGraph, store.selectedProject, side],
  )

  const runNodeAction = async (action: SavedAction, node: string) => {
    const connId = store.connection.activeProfileId ?? ''
    const projectId = store.selectedProject?.projectId ?? 0
    const resolvedSteps = resolveScope(action.spec.from.selectors, node, store.processGraph.transitions)
    setActionModal({ title: `${action.name} · ${node}`, result: null, busy: true, error: null })
    try {
      const result = await api.runAction(projectId, action.id, {
        connectionId: connId,
        filter: store.currentFilterSpec(),
        contextNode: node,
        resolvedSteps,
      })
      setActionModal({ title: `${action.name} · ${node}`, result, busy: false, error: null })
    } catch (e) {
      setActionModal({
        title: `${action.name} · ${node}`,
        result: null,
        busy: false,
        error: String((e as Error).message ?? e),
      })
    }
  }

  // Keep the slider in sync with the store's applied window. This covers project
  // load (the "last N days" default), a Day snap to the nearest date, and — the
  // reason this keys on fromDate/toDate rather than only the load-time values —
  // applying a preset from the left sidebar, which sets the window in the store
  // without going through the chart's own slider. A drag only moves local state
  // (the store commits on release), so this never clobbers a drag in progress.
  useEffect(() => {
    setSliderFrom(store.fromDate)
    setSliderTo(store.toDate)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.selectedProject, store.fromDate, store.toDate])

  const hasData = store.processGraph.transitions.length > 0
  const rangeMin =
    store.projectMinDate < store.initialToDate ? store.projectMinDate : store.initialFromDate

  if (!store.selectedProject) {
    return (
      <Unavailable
        glyph="🗺"
        title="No Project Selected"
        description="Select a project from the sidebar."
      />
    )
  }

  if (store.errorMessage && !store.isLoading) {
    return (
      <Unavailable glyph="⚠️" title="Failed to Load" description={store.errorMessage} />
    )
  }

  return (
    <div className="col" style={{ flex: 1, minHeight: 0, gap: 0 }}>
      {hasData && (
        <ChartControls
          expanded={expanded}
          onToggleExpanded={() => setExpanded(!expanded)}
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
              void store.reloadGraphForDay(from).then((actual) => {
                if (actual && actual !== from) {
                  setSliderFrom(actual)
                  setSliderTo(actual)
                }
              })
            } else {
              store.patch({ fromDate: from, toDate: to })
              void store.reloadGraph()
            }
          }}
          metric={store.transitionMetric}
          onMetricChange={(m) => store.setTransitionMetric(m)}
          metricsDisabled={!hasData}
          selectedPresetId={store.selectedFilterGroupId}
          onApplyPreset={(group) => {
            store.applyFilterGroup(group)
            setSliderFrom(group.fromDate.slice(0, 10))
            setSliderTo(group.toDate.slice(0, 10))
            void store.reloadGraph()
          }}
        />
      )}

      {!hasData ? (
        store.isLoading ? (
          <div className="center-fill">
            <span className="spinner large" />
            <span>
              {side === 'a' ? 'Loading process map' : 'Loading B-Chart'}
            </span>
          </div>
        ) : (
          <Unavailable
            glyph="📊"
            title="No Process Data"
            description={
              side === 'a'
                ? 'No event transitions found for this project.'
                : 'Use the sidebar filters and tap Apply to load the B-Chart.'
            }
            action={
              <button
                className="btn prominent"
                onClick={() => void store.reloadGraph()}
              >
                Load
              </button>
            }
          />
        )
      ) : (
        <div className="col" style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          {/* A detail view (a drilled-into project, or an in-place drill) shows a drill-up /
              return control instead of the flowchart/Sankey switch — and never shows Sankey. */}
          {inPlace ? (
            <div className="swim-toggle seg-toggle" role="toolbar">
              <button
                className="seg sel"
                onClick={() => store.drillUp()}
                title="Collapse the expanded aggregate(s) back to their Σ nodes"
              >
                ⤴ Drill up (collapse Σ)
              </button>
            </div>
          ) : isDetailProject ? (
            store.drillReturn && (
              <div className="swim-toggle seg-toggle" role="toolbar">
                <button
                  className="seg sel"
                  onClick={() => void store.returnFromDrill()}
                  title={`Back to “${store.drillReturn.title}”`}
                >
                  ← Return to high-level map
                </button>
              </div>
            )
          ) : (
            /* In-canvas view switch (flowchart ↕ / flowchart ↔ / Sankey). The two flowchart
               options are the same directed-follows map laid out top-down or left-to-right. */
            <div className="swim-toggle seg-toggle" role="tablist" aria-label="Chart view">
              <button
                className={`seg${!sankey && !flowHorizontal ? ' sel' : ''}`}
                role="tab"
                aria-selected={!sankey && !flowHorizontal}
                onClick={() => {
                  setSankey(false)
                  setFlowHorizontal(false)
                }}
                title="Directed-follows flowchart, top-down (loops shown)"
              >
                🕸 Flowchart
              </button>
              <button
                className={`seg${!sankey && flowHorizontal ? ' sel' : ''}`}
                role="tab"
                aria-selected={!sankey && flowHorizontal}
                onClick={() => {
                  setSankey(false)
                  setFlowHorizontal(true)
                }}
                title="Directed-follows flowchart, left-to-right (loops shown)"
              >
                ➡ Horizontal
              </button>
              <button
                className={`seg${sankey ? ' sel' : ''}`}
                role="tab"
                aria-selected={sankey}
                onClick={() => setSankey(true)}
                title="Sankey flow (looping clusters collapsed for readability)"
              >
                🌊 Sankey
              </button>
            </div>
          )}

          {inPlace ? (
            /* In-place explode: the Σ node expanded inside the high-level map. Remaining Σ
               nodes can be expanded too; drill up (node menu or the button) collapses all. */
            <FlowChart
              key={`inplace:${store.selectedProject.projectId}`}
              graph={inPlace.graph}
              projectId={`${store.selectedProject.projectId}#explode`}
              chartMode={side === 'a' ? 'A-Chart' : 'B-Chart'}
              metric={store.transitionMetric}
              journeyTotal={inPlace.journeyCount ?? 0}
              isLoading={store.isLoading}
              readOnly
              notes={store.projectNotes}
              aggregateLinks={store.projectAggregates}
              onDrillDownInPlace={(link) => void store.drillDownInPlace(link)}
              onDrillUp={() => store.drillUp()}
              explode={explodeSeed}
            />
          ) : sankey && !isDetailProject ? (
            <SankeyChart
              graph={store.processGraph}
              metric={store.transitionMetric}
              journeyTotal={store.journeyCount ?? 0}
            />
          ) : (
            <FlowChart
              // Remount on orientation change so the layout re-seeds from the
              // orientation-specific saved positions and re-fits the new flow direction.
              key={`flow:${store.selectedProject.projectId}:${flowHorizontal ? 'h' : 'v'}`}
              graph={store.processGraph}
              projectId={store.selectedProject.projectId}
              chartMode={side === 'a' ? 'A-Chart' : 'B-Chart'}
              metric={store.transitionMetric}
              journeyTotal={store.journeyCount ?? 0}
              horizontal={flowHorizontal}
              allowTransitionTable
              isLoading={store.isLoading}
              syncState={syncState}
              notice={simulationFilterNotice(
                side === 'a' ? store.abDataSourceA : store.abDataSourceB,
              )}
              readOnly={
                (side === 'a' ? store.abDataSourceA : store.abDataSourceB).kind ===
                'simulation'
              }
              onNodeAction={(node, action) => store.handleNodeAction(node, action)}
              onMetaInfo={(node) => store.openMetaInfo(node)}
              notes={store.projectNotes}
              onNodeNote={notes.openNodeNotes}
              onEdgeNote={notes.openEdgeNotes}
              actionItems={actionItems}
              onRunAction={(action, node) => void runNodeAction(action, node)}
              onCreateAggregate={canAggregate ? (groups) => setAggregateGroups(groups) : undefined}
              isHighLevelMap={store.projectAggregates.length > 0}
              aggregateLinks={store.projectAggregates}
              onDrillDown={(link) => void store.drillDownPanel(link)}
              onDrillDownInPlace={(link) => void store.drillDownInPlace(link)}
            />
          )}
        </div>
      )}

      {hasData && store.queryMs != null && (
        <div className="chart-footer" title="Server-side execution time of the queries behind this view">
          <span className="spacer" />
          <span>
            Query time:{' '}
            {store.queryMs < 1000
              ? `${store.queryMs} ms`
              : `${(store.queryMs / 1000).toFixed(2)} s`}
          </span>
        </div>
      )}

      {notes.element}

      {actionModal && (
        <ActionResultModal
          title={actionModal.title}
          result={actionModal.result}
          busy={actionModal.busy}
          error={actionModal.error}
          onClose={() => setActionModal(null)}
        />
      )}

      {aggregateGroups && store.selectedProject && (
        <AggregateSetDialog
          groups={aggregateGroups}
          transitions={store.processGraph.transitions}
          projectId={store.selectedProject.projectId}
          connectionId={store.connection.activeProfileId ?? ''}
          projectTitle={store.selectedProject.title}
          addMode={store.projectAggregates.length > 0}
          onClose={() => setAggregateGroups(null)}
          onDone={(result) => {
            setAggregateGroups(null)
            void store.loadProjects()
            void store.loadProjectAggregates()
            const here = result.highLevelConnectionId === store.connection.activeProfileId
            const n = result.aggregates.length
            store.showAlert({
              title: 'Aggregates created',
              message: here
                ? `Built the high-level map with ${n} new Σ step${n === 1 ? '' : 's'} and ${n === 1 ? 'its detail project' : 'their detail projects'} in this connection's schema. If you don't see them in the Projects list, refresh — they only appear here when the schema was left blank (same schema); a new schema/connection must be opened separately.`
                : `Wrote the high-level map and ${n} detail project${n === 1 ? '' : 's'} to another connection/schema. Connect to that schema to open them — they won't appear in this Projects list.`,
              primaryLabel: 'OK',
            })
          }}
        />
      )}

      {store.panelDrill && (
        <Sheet
          title={`${store.panelDrill.sigmaStep} — sub-process`}
          icon="Σ"
          resizable
          onClose={() => store.closeDrillPanel()}
        >
          <p className="fg-secondary" style={{ marginTop: 0, fontSize: 13 }}>
            The steps inside this aggregate and their incoming / outgoing connections, with
            real (un-aggregated) numbers.
          </p>
          <p className="fg-secondary" style={{ marginTop: 0, fontSize: 13 }}>
            🗓{' '}
            <strong>
              {store.fromDate && store.toDate
                ? store.fromDate === store.toDate
                  ? store.fromDate
                  : `${store.fromDate} – ${store.toDate}`
                : 'Full date range'}
            </strong>
            {store.panelDrill.journeyCount != null && ` · ${store.panelDrill.journeyCount} journeys`}
          </p>
          <div style={{ flex: 1, minHeight: 0 }}>
            <ActionFlowchart
              result={{
                kind: 'flowchart',
                columns: [],
                rows: [],
                graph: store.panelDrill.graph,
                journeyCount: store.panelDrill.journeyCount ?? 0,
                title: store.panelDrill.sigmaStep,
                metric: store.transitionMetric,
                metrics: [...TRANSITION_METRICS],
              }}
              height="100%"
              fitOnResize
            />
          </div>
        </Sheet>
      )}
    </div>
  )
}
