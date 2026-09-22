import { memo, useContext } from 'react'
import { EdgeLabelRenderer, type EdgeProps } from '@xyflow/react'
import { FlowFocusContext } from './focusContext'
import {
  EDGE_SCHEMA_GRADIENTS,
  NOTE_YELLOW,
  interpolate,
  rgba,
  type EdgeColorSchema,
} from '../graph/colors'
import { formatCount, formatDuration, formatPercent } from '../graph/format'
import {
  isTimeBased,
  journeyPercentage,
  metricValue,
  outgoingPercentage,
  type ProcessTransition,
  type TransitionMetric,
} from '../types'

export interface MetricEdgeData extends Record<string, unknown> {
  transition: ProcessTransition
  metric: TransitionMetric
  maxValue: number
  colorize: boolean
  schema: EdgeColorSchema
  /** Target-process / conformance overlay. */
  normValue: number | null
  normMetric: TransitionMetric
  showNorms: boolean
  showCompliance: boolean
  normIsMinimum: boolean
  /** Total occurrences leaving the source node — count norms are percentages. */
  outgoingTotal: number
  /** Total filtered journeys — the denominator for the 'Journey %' metric. */
  journeyTotal: number
  hasNote: boolean
  nodeH: number
  /** Left-to-right layout: curve the edge horizontally (handles are on the sides). */
  horizontal?: boolean
  edgeScale: number
  onEdgeClick?: (transition: ProcessTransition, screen: { x: number; y: number }) => void
}

const SECONDARY = '#8E8E93'

/**
 * SMIL keyframes for a single dot that traverses `total` edges one after
 * another over a shared loop. Each edge's dot moves along its own path only
 * during its 1/total time slot (rest of the loop it is hidden). Returns the
 * motion keyPoints/keyTimes (progress 0→1 along the path) and the opacity
 * on/off schedule (discrete). All edges share the same `dur`, so they stay in
 * lock-step and the dot appears to hop from edge to edge in order.
 *
 * Retained only for the integration console's live import-run playback
 * (IntegrationPipeline); the main app's Individual Journey no longer animates.
 */
export function flowKeyframes(index: number, total: number) {
  const a = index / total
  const b = (index + 1) / total
  const f = (n: number) => n.toFixed(4)

  // Motion: hold at start until a, move a→b, hold at end. Collapse equal times.
  const motion: Array<[number, number]> = [
    [0, 0],
    [a, 0],
    [b, 1],
    [1, 1],
  ]
  const mTimes: string[] = []
  const mPoints: string[] = []
  for (const [t, p] of motion) {
    if (mTimes.length && f(t) === mTimes[mTimes.length - 1]) {
      mPoints[mPoints.length - 1] = f(p) // equal time → keep the later point
    } else {
      mTimes.push(f(t))
      mPoints.push(f(p))
    }
  }

  // Opacity (discrete): visible only during [a, b].
  const oTimes: string[] = ['0']
  const oValues: string[] = [a === 0 ? '1' : '0']
  if (a > 0) {
    oTimes.push(f(a))
    oValues.push('1')
  }
  if (b < 1) {
    oTimes.push(f(b))
    oValues.push('0')
  }

  return {
    keyPoints: mPoints.join(';'),
    keyTimes: mTimes.join(';'),
    opacityTimes: oTimes.join(';'),
    opacityValues: oValues.join(';'),
  }
}

/** Cubic path matching the Swift `addCurve` control points. */
function edgePath(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
  horizontal = false,
): { path: string; midX: number; midY: number } {
  // A cubic Bézier whose control points leave the source and enter the target along the
  // flow axis — down/up for a top-to-bottom map, right/left for a left-to-right one — so the
  // curve emerges cleanly from the node's handle in either orientation.
  const path = horizontal
    ? (() => {
        const cpDist = Math.max(Math.abs(tx - sx) * 0.45, 40)
        return `M ${sx},${sy} C ${sx + cpDist},${sy} ${tx - cpDist},${ty} ${tx},${ty}`
      })()
    : (() => {
        const cpDist = Math.max(Math.abs(ty - sy) * 0.45, 40)
        return `M ${sx},${sy} C ${sx},${sy + cpDist} ${tx},${ty - cpDist} ${tx},${ty}`
      })()
  return { path, midX: (sx + tx) / 2, midY: (sy + ty) / 2 }
}

function MetricEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
}: EdgeProps) {
  const d = data as MetricEdgeData
  const {
    transition,
    metric,
    maxValue,
    colorize,
    schema,
    normValue,
    normMetric,
    showNorms,
    showCompliance,
    normIsMinimum,
    outgoingTotal,
    journeyTotal,
    hasNote,
    nodeH,
    horizontal,
    edgeScale,
    onEdgeClick,
  } = d
  const eScale = edgeScale || 1

  // Hover-dwell focus: fade edges that don't touch the spotlit node so the focused node's
  // incoming/outgoing connections stand out in a crowded map.
  const focus = useContext(FlowFocusContext)
  const dimmed = focus != null && !focus.edges.has(id)
  const emphasisStyle = { opacity: dimmed ? 0.1 : 1, transition: 'opacity 0.2s ease' }

  const isSelfLoop = transition.fromStep === transition.toStep
  // Both the legacy Count norm and the new Percentage metric are outgoing-share percentages.
  const isCountPct = normMetric === 'Count' || normMetric === 'Percentage'

  let lineWidth: number
  let lineAlpha: number
  let lineColor: string
  let labelText: string
  let useBadge = false

  if (showNorms) {
    useBadge = true
    const actual = isCountPct
      ? outgoingTotal > 0
        ? (transition.occurrences / outgoingTotal) * 100
        : 0
      : (metricValue(transition, normMetric) ?? transition.occurrences)

    if (showCompliance) {
      // Compliance: width by actual metric ratio, colour by actual-vs-norm.
      const ratio = Math.max(0, Math.min(1, actual / Math.max(maxValue, 1)))
      lineWidth = 3 + ratio * 19
      lineAlpha = 0.45 + ratio * 0.35
      lineColor =
        normValue == null
          ? SECONDARY
          : (normIsMinimum ? actual >= normValue : actual <= normValue)
            ? '#34C759'
            : '#FF3B30'
      labelText = isCountPct
        ? `${Math.round(actual)}%`
        : isTimeBased(normMetric)
          ? (() => {
              const v = metricValue(transition, normMetric)
              return v == null ? '—' : formatDuration(v)
            })()
          : formatCount(transition.occurrences)
    } else {
      // Target process: uniform appearance, show the stored norm.
      lineWidth = 6
      lineAlpha = 0.4
      lineColor = SECONDARY
      labelText =
        normValue == null
          ? '—'
          : isCountPct
            ? `${Math.round(normValue)}%`
            : isTimeBased(normMetric)
              ? formatDuration(normValue)
              : formatCount(Math.round(normValue))
    }
  } else {
    // Two share metrics: 'Percentage' = outgoing branching share (each node's edges sum to
    // 100 %); 'Journey %' = share of all filtered journeys. Every other metric reads off
    // the transition.
    const isPct = metric === 'Percentage' || metric === 'Journey %'
    const value =
      metric === 'Percentage'
        ? outgoingPercentage(transition, outgoingTotal)
        : metric === 'Journey %'
          ? journeyPercentage(transition, journeyTotal)
          : (metricValue(transition, metric) ?? transition.occurrences)
    const ratio = Math.max(0, Math.min(1, value / Math.max(maxValue, 1)))
    lineWidth = 3 + ratio * 19
    lineAlpha = 0.3 + ratio * 0.5
    const gradient = EDGE_SCHEMA_GRADIENTS[schema]
    lineColor =
      colorize && gradient ? interpolate(gradient.low, gradient.high, ratio) : SECONDARY
    labelText = isPct
      ? formatPercent(value)
      : isTimeBased(metric)
        ? (() => {
            const v = metricValue(transition, metric)
            return v == null ? '—' : formatDuration(v)
          })()
        : formatCount(transition.occurrences)
  }

  const stroke = rgba(lineColor, lineAlpha)
  const arrowSize = Math.max(5, lineWidth * 0.75)

  let path: string
  let midX: number
  let midY: number

  if (isSelfLoop) {
    // Circle above the node, radius 18, offset 2.2·r above the top edge.
    const r = 18
    const cx = sourceX
    const cy = sourceY - nodeH - r * 2.2 + r
    path = `M ${cx - r},${cy} a ${r},${r} 0 1,0 ${r * 2},0 a ${r},${r} 0 1,0 ${-r * 2},0`
    midX = cx
    midY = cy
  } else {
    const geometry = edgePath(sourceX, sourceY, targetX, targetY, horizontal)
    path = geometry.path
    midX = geometry.midX
    midY = geometry.midY
  }

  const markerId = `arrow-${id.replace(/[^a-zA-Z0-9_-]/g, '_')}`

  const badgeWidth = Math.round(Math.max(44, labelText.length * 9 + 18) * eScale)
  const hasNorm = normValue != null
  const badgeColor = showCompliance
    ? lineColor
    : hasNorm
      ? 'var(--accent)'
      : SECONDARY
  const badgeOpacity = hasNorm || showCompliance ? 0.88 : 0.3

  return (
    <>
      <g style={emphasisStyle}>
      {!isSelfLoop && (
        <defs>
          <marker
            id={markerId}
            markerWidth={arrowSize * 2}
            markerHeight={arrowSize * 1.6}
            refX={arrowSize}
            refY={arrowSize * 1.6}
            orient="auto-start-reverse"
            markerUnits="userSpaceOnUse"
          >
            <polygon
              points={`${arrowSize},${arrowSize * 1.6} 0,0 ${arrowSize * 2},0`}
              fill={rgba(lineColor, Math.min(1, lineAlpha + 0.1))}
            />
          </marker>
        </defs>
      )}

      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={lineWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        markerEnd={isSelfLoop ? undefined : `url(#${markerId})`}
      />
      {/* Wide invisible hit area so thin edges stay clickable. */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={Math.max(lineWidth, 24)}
        style={{ cursor: onEdgeClick ? 'pointer' : 'default' }}
        onClick={(event) =>
          onEdgeClick?.(transition, { x: event.clientX, y: event.clientY })
        }
      />
      </g>

      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${midX}px, ${midY}px)`,
            pointerEvents: dimmed ? 'none' : 'all',
            opacity: dimmed ? 0.1 : 1,
            transition: 'opacity 0.2s ease',
            display: 'flex',
            alignItems: 'center',
            gap: Math.round(6 * eScale),
          }}
          onClick={(event) =>
            onEdgeClick?.(transition, { x: event.clientX, y: event.clientY })
          }
        >
          {useBadge ? (
            <span
              className="edge-badge-text"
              style={{
                minWidth: badgeWidth,
                height: Math.round(22 * eScale),
                fontSize: `${13 * eScale}px`,
                display: 'grid',
                placeItems: 'center',
                borderRadius: Math.round(11 * eScale),
                background:
                  badgeColor === 'var(--accent)'
                    ? `rgba(10, 132, 255, ${badgeOpacity})`
                    : rgba(badgeColor, badgeOpacity),
                color: hasNorm || showCompliance ? '#fff' : 'var(--secondary)',
                cursor: onEdgeClick ? 'pointer' : 'default',
              }}
              title={`${transition.fromStep} → ${transition.toStep}`}
            >
              {labelText}
            </span>
          ) : (
            <span
              className="edge-badge-text"
              style={{
                padding: '1px 6px',
                borderRadius: 6,
                fontSize: `${13 * eScale}px`,
                background: 'var(--bg-grouped)',
                color: 'var(--primary)',
                cursor: onEdgeClick ? 'pointer' : 'default',
              }}
              title={`${transition.fromStep} → ${transition.toStep} · ${transition.occurrences.toLocaleString()}`}
            >
              {labelText}
            </span>
          )}

          {hasNote && (
            <span
              style={{
                // Scale the note bubble with the edge label, plus the same 1.35×
                // boost the node badges use so it stays clearly visible.
                width: Math.round(14 * eScale * 1.35),
                height: Math.round(14 * eScale * 1.35),
                borderRadius: Math.round(7 * eScale * 1.35),
                display: 'grid',
                placeItems: 'center',
                background: NOTE_YELLOW,
                color: 'rgba(0,0,0,0.75)',
                fontSize: Math.round(9 * eScale * 1.35),
                boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
              }}
              title="This transition has notes"
            >
              ✎
            </span>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

export const MetricEdge = memo(MetricEdgeComponent)
