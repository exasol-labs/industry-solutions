/** The integration console's main pane: the abstraction-layer status on top, then ONE
 *  live pipeline flowchart that accumulates the ingestion behaviour over time — nodes are
 *  reused across runs, and the Source / Destination nodes carry the total imported rows.
 *  The run history (persisted per user) feeds the flowchart and is kept until the user
 *  clears it. A single poll (useIntegrationStatus) drives the status card and the graph. */

import { useState } from 'react'
import { useIntegrationStatus } from '../integration/useIntegrationStatus'
import { useRunHistory } from '../integration/runHistory'
import { useSinkMonitor } from '../integration/useSinkMonitor'
import { ConfirmDialog } from './ConfirmDialog'
import { IntegrationPipeline } from './IntegrationPipeline'
import { IntegrationStatusPanel } from './IntegrationStatusPanel'
import { SinkMonitor } from './SinkMonitor'

export function IntegrationConsole({ onShowHelp }: { onShowHelp: () => void }) {
  const { status, error } = useIntegrationStatus()
  const { runs, clear, atCap } = useRunHistory(status)
  const { data: sinkData, flowing: sinkFlowing } = useSinkMonitor()
  const [confirmClear, setConfirmClear] = useState(false)
  const sinks = sinkData?.sinks ?? []

  return (
    <div className="integration-console">
      {/* Top toolbar with the Help button, matching the main app's placement. */}
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button className="btn small" onClick={onShowHelp} title="Help">
          ？
        </button>
      </div>

      <IntegrationStatusPanel status={status} runs={runs} error={error} />

      <div className="ihist-head">
        <h2 style={{ margin: 0, fontSize: 15 }}>Ingestion pipeline</h2>
        <span className="t-caption2 fg-tertiary">
          {runs.length === 0
            ? 'no imports yet'
            : `${runs.length}${atCap ? '+' : ''} run${runs.length === 1 ? '' : 's'} · behaviour over time`}
        </span>
        <span className="spacer" />
        {runs.length > 0 && (
          <button className="btn small" onClick={() => setConfirmClear(true)} title="Clear the ingestion history">
            ↺ Clear
          </button>
        )}
      </div>

      <IntegrationPipeline runs={runs} live={status} />

      {/* The sink-side monitor: shown only once the user has defined an Event Receiver. */}
      {sinkData && sinks.length > 0 && (
        <>
          <div className="ihist-head" style={{ marginTop: 18 }}>
            <h2 style={{ margin: 0, fontSize: 15 }}>API Server - Event Receivers</h2>
            <span className="t-caption2 fg-tertiary">
              {sinks.length} sink{sinks.length === 1 ? '' : 's'} ·{' '}
              {sinkData.moduleEnabled
                ? sinkData.supervisorRunning
                  ? 'live'
                  : 'module on, supervisor not running'
                : 'module disabled'}
            </span>
          </div>
          <SinkMonitor data={sinkData} flowing={sinkFlowing} />
        </>
      )}

      {confirmClear && (
        <ConfirmDialog
          title="Clear ingestion history"
          message={`Reset the pipeline flowchart, removing all ${runs.length} recorded run${runs.length === 1 ? '' : 's'}? This only clears the console view — nothing already imported is affected.`}
          confirmLabel="Clear history"
          onConfirm={() => {
            clear()
            setConfirmClear(false)
          }}
          onCancel={() => setConfirmClear(false)}
        />
      )}
    </div>
  )
}
