/** Right-hand detail area — port of ProcessMapView.swift's chrome:
 *  title capsule, view-mode menu, KPI strip and the active-view switcher. */

import { useState } from 'react'
import { JourneyKpiStrip, KpiStrip } from '../components/KpiStrip'
import { Chevron, Unavailable } from '../components/ui'
import { FlowChart } from '../flow/FlowChart'
import { SwimlaneChart } from '../flow/SwimlaneChart'
import { useSetting } from '../settings'
import { useStore } from '../store'
import { DETAIL_VIEW_MODES, VIEW_MODE_ICONS, type DetailViewMode } from '../types'
import { ABComparison } from './ABComparison'
import { AIDocumentationView } from './AIDocumentationView'
import { ChartView } from './ChartView'
import { ConformanceView } from './ConformanceView'
import { HappyPathView } from './HappyPathView'
import { NotesView } from './NotesView'
import { SimulationView } from './SimulationView'
import { StatisticsView } from './StatisticsView'

/** Advanced-analysis views shown only to power users (and admins) — hidden from
 *  plain users in the view-mode menu. */
const POWER_ONLY_MODES: DetailViewMode[] = [
  'Conformance Check',
  'Happy Path',
  'Simulation',
]

/** Modes that render their own header instead of the shared KPI strip. */
const SELF_MANAGED: DetailViewMode[] = [
  'A/B Comparison',
  'Statistics',
  'Notes',
  'AI supported Documentation',
  'Happy Path',
  'Conformance Check',
  'Simulation',
]

export function DetailPane({
  sidebarHidden,
  onShowSidebar,
  onShowHelp,
}: {
  sidebarHidden: boolean
  onShowSidebar: () => void
  onShowHelp: () => void
}) {
  const store = useStore()
  const [kpiExpanded, setKpiExpanded] = useSetting<boolean>('processmap.kpiExpanded')
  const [menuOpen, setMenuOpen] = useState(false)

  const mode = store.activeChartMode
  const connected = store.connection.isConnected && store.selectedProject != null

  // Power users (and admins) get the advanced-analysis views; plain users don't.
  const canSeePowerModes = store.authIsPower || store.authIsAdmin
  const visibleModes = DETAIL_VIEW_MODES.filter(
    (m) => canSeePowerModes || !POWER_ONLY_MODES.includes(m),
  )

  const showSharedKpi =
    connected &&
    !SELF_MANAGED.includes(mode) &&
    ((mode !== 'Individual Journey' && store.processGraph.transitions.length > 0) ||
      (mode === 'Individual Journey' && store.journeyDate != null))

  return (
    <main className="detail">
      {sidebarHidden && (
        <button
          className="show-sidebar-btn"
          onClick={onShowSidebar}
          title="Show sidebar"
          aria-label="Show sidebar"
        >
          ▤
        </button>
      )}

      <div className="title-capsule">
        <div className="t-name">{store.selectedProject?.title ?? 'Process Map'}</div>
        <div className="t-mode" style={{ opacity: store.selectedProject ? 1 : 0 }}>
          {mode}
        </div>
      </div>

      <div className="detail-toolbar">
        <button className="btn small" onClick={onShowHelp} title="Help">
          ？
        </button>
        {connected && (
          <div style={{ position: 'relative' }}>
            <button
              className="btn small"
              onClick={() => setMenuOpen(!menuOpen)}
              title="Switch view"
            >
              ☰ {VIEW_MODE_ICONS[mode]}
            </button>
            {menuOpen && (
              <>
                <div
                  style={{ position: 'fixed', inset: 0, zIndex: 199 }}
                  onClick={() => setMenuOpen(false)}
                />
                <div
                  className="popover"
                  style={{ right: 0, top: 32, position: 'absolute', minWidth: 250 }}
                >
                  {visibleModes.map((option) => (
                    <button
                      key={option}
                      className="p-item"
                      onClick={() => {
                        store.switchChartMode(option)
                        setMenuOpen(false)
                      }}
                    >
                      <span aria-hidden style={{ width: 20 }}>
                        {VIEW_MODE_ICONS[option]}
                      </span>
                      <span className="spacer">{option}</span>
                      {option === mode && <span className="fg-accent">✓</span>}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {showSharedKpi && (
        <>
          <button className="kpi-handle" onClick={() => setKpiExpanded(!kpiExpanded)}>
            <Chevron open={kpiExpanded} />
            {!kpiExpanded && store.journeyCount != null && (
              <span>
                {store.journeyCount.toLocaleString()}
                {store.totalJourneyCount != null &&
                  ` / ${store.totalJourneyCount.toLocaleString()}`}{' '}
                Journeys
              </span>
            )}
            <span className="spacer" />
            {store.transitionsMode && mode !== 'Individual Journey' && (
              <span
                className={`mode-pill ${store.transitionsMode}`}
                title={
                  store.transitionsMode === 'materialized'
                    ? 'Transitions are read from the pre-materialized TRANSITIONS_RAW table.'
                    : store.transitionsMode === 'fallback'
                      ? 'Pre-materialized transitions are enabled for this connection, but TRANSITIONS_RAW is not built yet — running the live query meanwhile. Rebuild it in the admin interface (Connections → Rebuild now).'
                      : 'Transitions are computed live from the event log on each load.'
                }
              >
                {store.transitionsMode === 'materialized'
                  ? '⚡ Pre-materialized'
                  : store.transitionsMode === 'fallback'
                    ? '⚠ Live (not built)'
                    : '↻ Live query'}
              </span>
            )}
          </button>
          {kpiExpanded &&
            (mode === 'Individual Journey' ? (
              <JourneyKpiStrip />
            ) : (
              <KpiStrip
                // The Active-Sample tile reads the side's data source; the B-Chart is
                // side 'b' (every other single view mirrors side 'a'). Without this the
                // B-Chart showed A's sample and only refreshed when A's sample changed.
                side={mode === 'B-Chart' ? 'b' : 'a'}
                graph={store.processGraph}
                journeyCount={store.journeyCount}
                durations={store.durations}
                goodness={store.processGoodnessScore}
                loading={store.isLoading}
              />
            ))}
        </>
      )}

      <ActiveView />
    </main>
  )
}

function ActiveView() {
  const store = useStore()

  if (!store.connection.isConnected) {
    return (
      <Unavailable
        glyph="⛁"
        title="Not Connected"
        description="Add a connection in the sidebar and tap it to connect to your Exasol database."
      />
    )
  }

  switch (store.activeChartMode) {
    case 'A-Chart':
      return <ChartView side="a" />
    case 'B-Chart':
      return <ChartView side="b" />
    case 'A/B Comparison':
      return <ABComparison />
    case 'Individual Journey':
      return <IndividualJourneyView />
    case 'AI supported Documentation':
      return <AIDocumentationView />
    case 'Statistics':
      return <StatisticsView />
    case 'Conformance Check':
      return <ConformanceView />
    case 'Happy Path':
      return <HappyPathView />
    case 'Notes':
      return <NotesView />
    case 'Simulation':
      return <SimulationView />
  }
}

function IndividualJourneyView() {
  const store = useStore()

  if (store.isLoading) {
    return (
      <div className="center-fill">
        <span className="spinner large" />
        <span>Loading journey</span>
      </div>
    )
  }
  if (store.errorMessage) {
    return (
      <Unavailable glyph="⚠️" title="Failed to Load" description={store.errorMessage} />
    )
  }
  if (!store.selectedProject) {
    return (
      <Unavailable
        glyph="🗺"
        title="No Project Selected"
        description="Select a project from the sidebar to view a journey."
      />
    )
  }
  if (!store.eventIdFilter.trim()) {
    return (
      <Unavailable
        glyph="🧍"
        title="No Journey Selected"
        description="Enter an Event ID in the sidebar and tap Load Journey."
      />
    )
  }
  if (store.processGraph.transitions.length === 0) {
    return (
      <Unavailable
        glyph="🔍"
        title="Journey Not Found"
        description={`No steps found for "${store.eventIdFilter}".\nQueried hash: ${store.lastQueriedEventId}`}
      />
    )
  }

  const swim = store.journeySwimlane
  return (
    <div className="col" style={{ flex: 1, minHeight: 0, position: 'relative' }}>
      {/* In-canvas view switch (flowchart ↔ swimlane) — not in the left panel. */}
      <div className="swim-toggle seg-toggle" role="tablist" aria-label="Journey view">
        <button
          className={`seg${swim ? '' : ' sel'}`}
          role="tab"
          aria-selected={!swim}
          onClick={() => store.setJourneySwimlane(false)}
          title="Directed-follows flowchart (loops shown)"
        >
          🕸 Flowchart
        </button>
        <button
          className={`seg${swim ? ' sel' : ''}`}
          role="tab"
          aria-selected={swim}
          onClick={() => store.setJourneySwimlane(true)}
          title="Sequential swimlane, one lane per node group (loops unrolled)"
        >
          🏊 Swimlane
        </button>
      </div>
      {swim ? (
        <SwimlaneChart
          key={`sw_${store.lastQueriedEventId}`}
          sequence={store.journeySequence}
          graph={store.processGraph}
        />
      ) : (
        <FlowChart
          key={store.lastQueriedEventId}
          graph={store.processGraph}
          projectId={store.selectedProject.projectId}
          chartMode={`ij_${store.eventIdFilter}`}
          // A single journey traverses each transition once, so Count is meaningless
          // here — always show the average transition time. The sidebar Metrics
          // selector is hidden for this mode (see Sidebar).
          metric="Avg Time"
          // A single trace is already sparse and strictly sequential, so the hover-dwell
          // spotlight (for untangling crowded aggregate maps) is not wanted here.
          hoverFocus={false}
        />
      )}
    </div>
  )
}
