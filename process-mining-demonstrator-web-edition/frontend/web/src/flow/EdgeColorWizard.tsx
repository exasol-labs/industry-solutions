/** Edge colour-schema wizard.
 *
 * Opened by clicking the connections colour legend on the process map. Lets the
 * user choose an `EdgeColorSchema` per transition metric, with a live gradient
 * preview, plus the global "colorise by weight" toggle. Selections persist to
 * the same `graph.edge.colorSchema.<metric>` keys the Swift app used, so they
 * survive reloads and round-trip through backups. */

import {
  EDGE_COLOR_SCHEMAS,
  EDGE_SCHEMA_GRADIENTS,
  EDGE_SCHEMA_LABELS,
  defaultSchemaFor,
  interpolate,
  type EdgeColorSchema,
} from '../graph/colors'
import { Sheet, Switch } from '../components/ui'
import { edgeSchemaKey, useSetting, writeSetting } from '../settings'
import { TRANSITION_METRICS, type TransitionMetric } from '../types'

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

/** Preview swatch for a schema — the three-stop gradient, or a flat grey bar. */
function GradientBar({ schema }: { schema: EdgeColorSchema }) {
  const gradient = EDGE_SCHEMA_GRADIENTS[schema]
  return (
    <div className="col" style={{ gap: 3, minWidth: 120 }}>
      <div
        style={{
          height: 10,
          borderRadius: 5,
          background: gradient
            ? `linear-gradient(90deg, ${gradient.low}, ${interpolate(
                gradient.low,
                gradient.high,
                0.5,
              )}, ${gradient.high})`
            : 'rgba(120,120,128,0.25)',
        }}
      />
      <div className="row" style={{ justifyContent: 'space-between' }}>
        {gradient ? (
          <>
            <span className="t-caption2 fg-tertiary">Low</span>
            <span className="t-caption2 fg-tertiary">High</span>
          </>
        ) : (
          <span className="t-caption2 fg-tertiary">No colour scale</span>
        )}
      </div>
    </div>
  )
}

function MetricRow({ metric }: { metric: TransitionMetric }) {
  const [schema, setSchema] = useSetting<EdgeColorSchema>(edgeSchemaKey(metric))

  return (
    <div
      className="row"
      style={{
        gap: 14,
        padding: '10px 0',
        borderBottom: '1px solid var(--separator-soft)',
        alignItems: 'center',
      }}
    >
      <div className="row" style={{ gap: 6, width: 110 }}>
        <span aria-hidden className="fg-secondary">
          {METRIC_ICONS[metric]}
        </span>
        <span className="t-callout" style={{ fontWeight: 500 }}>
          {metric}
        </span>
      </div>

      <select
        className="select-input"
        style={{ flex: 1, minWidth: 150 }}
        value={schema}
        onChange={(e) => setSchema(e.target.value as EdgeColorSchema)}
      >
        {EDGE_COLOR_SCHEMAS.map((option) => (
          <option key={option} value={option}>
            {EDGE_SCHEMA_LABELS[option]}
          </option>
        ))}
      </select>

      <GradientBar schema={schema} />
    </div>
  )
}

export function EdgeColorWizard({ onClose }: { onClose: () => void }) {
  const [colorize, setColorize] = useSetting<boolean>('graph.edge.colorizeByWeight')

  return (
    <Sheet
      title="Edge Colour Schema"
      icon="🎨"
      onClose={onClose}
      footer={
        <>
          <button
            className="btn"
            onClick={() => {
              // Restore every metric to its Swift default schema.
              for (const metric of TRANSITION_METRICS) {
                writeSetting(edgeSchemaKey(metric), defaultSchemaFor(metric))
              }
            }}
          >
            Reset to defaults
          </button>
          <span className="spacer" />
          <button className="btn prominent" onClick={onClose}>
            Done
          </button>
        </>
      }
    >
      <div className="t-footnote fg-secondary">
        Edge thickness always encodes the selected metric. When colouring is on,
        each transition is tinted along the chosen gradient from the lowest to the
        highest value. Settings are saved per metric.
      </div>

      <div
        className="row"
        style={{
          gap: 10,
          padding: '10px 12px',
          borderRadius: 8,
          background: 'var(--bg-fill)',
        }}
      >
        <span aria-hidden>🎨</span>
        <span className="t-callout spacer">Colorise edges by weight</span>
        <Switch checked={colorize} onChange={setColorize} />
      </div>

      <div className="col" style={{ gap: 0, opacity: colorize ? 1 : 0.5 }}>
        <div className="row" style={{ gap: 14, paddingBottom: 4 }}>
          <span className="field-label" style={{ width: 110 }}>
            Metric
          </span>
          <span className="field-label" style={{ flex: 1 }}>
            Colour schema
          </span>
          <span className="field-label" style={{ minWidth: 120 }}>
            Preview
          </span>
        </div>
        {TRANSITION_METRICS.map((metric) => (
          <MetricRow key={metric} metric={metric} />
        ))}
      </div>
    </Sheet>
  )
}
