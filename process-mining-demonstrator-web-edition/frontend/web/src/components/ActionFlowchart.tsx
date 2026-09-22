/** Renders a flowchart action's process map. FlowChart fits the view one frame after
 *  mount, which only works if its container already has its final size — inside a modal
 *  the container is often still 0×0 on that first frame. So we wait (via ResizeObserver)
 *  until the container is actually measured, then mount FlowChart into a sized box. */

import { useEffect, useRef, useState } from 'react'
import { FlowChart } from '../flow/FlowChart'
import type { ActionRunResult } from '../actions/types'
import type { TransitionMetric } from '../types'

// Same glyphs the main chart's metric bar uses, so the panel's picker matches it.
const METRIC_ICONS: Record<TransitionMetric, string> = {
  Count: '#',
  Percentage: '%',
  'Journey %': '%',
  'Avg Time': '⏱',
  'Median Time': '½',
  'Min Time': '⌄',
  'Max Time': '⌃',
  'Std Dev': '〰',
}

export function ActionFlowchart({
  result,
  height,
  fitOnResize = false,
}: {
  result: ActionRunResult
  height: number | string
  /** Re-fit the flowchart to the container when it is resized (e.g. a resizable panel). */
  fitOnResize?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(false)

  // The edge metrics the action offers (SHOW FLOWCHART … FOR …). One or none ⇒ no picker.
  const metricChoices = result.metrics && result.metrics.length ? result.metrics : []
  const [metric, setMetric] = useState<TransitionMetric>(
    result.metric ?? metricChoices[0] ?? 'Count',
  )

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const check = () => {
      if (el.clientWidth > 0 && el.clientHeight > 0) setReady(true)
    }
    check()
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    // FlowChart's root (.flow-wrap) is `flex: 1`, so it only takes height inside a
    // flex COLUMN with a definite height — a plain block would collapse it to 0.
    <div ref={ref} style={{ height, width: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {metricChoices.length > 1 && (
        <div className="metric-bar" style={{ padding: '2px 2px 8px' }}>
          {metricChoices.map((m) => (
            <button
              key={m}
              className={`chip${metric === m ? ' active' : ''}`}
              onClick={() => setMetric(m)}
            >
              <span aria-hidden>{METRIC_ICONS[m]}</span> {m}
            </button>
          ))}
        </div>
      )}
      {ready && result.graph && (
        <FlowChart
          graph={result.graph}
          projectId={`action:${result.title ?? 'flowchart'}`}
          chartMode="Action-Flowchart"
          metric={metric}
          journeyTotal={result.journeyCount ?? 0}
          readOnly
          allowTransitionTable={false}
          fitOnResize={fitOnResize}
        />
      )}
    </div>
  )
}
