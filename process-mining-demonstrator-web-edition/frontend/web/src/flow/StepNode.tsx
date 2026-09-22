import { Handle, Position, type NodeProps } from '@xyflow/react'
import { memo, useContext } from 'react'
import {
  NOTE_YELLOW,
  SCORE_NEGATIVE,
  SCORE_NEUTRAL,
  SCORE_POSITIVE,
  namedColor,
} from '../graph/colors'
import { formatTimeOnly } from '../graph/format'
import { AggregatePickContext } from './aggregatePickContext'
import { FlowFocusContext } from './focusContext'
import type { StepInfo } from '../types'

export interface StepNodeData extends Record<string, unknown> {
  name: string
  step: StepInfo
  nodeW: number
  nodeH: number
  scale: number
  showDescription: boolean
  /** Set when this node stands in for a collapsed BELONGS_TO group. */
  groupProxy: { group: string; memberCount: number; color: string } | null
  hasNote: boolean
  /** Left-to-right layout: put the flow handles on the sides, not top/bottom. */
  horizontal?: boolean
}

/** Node outline — ports `FlowChartView.nodePath(shape:rect:)` to CSS. */
function shapeStyle(shape: string, w: number, h: number): React.CSSProperties {
  switch (shape) {
    case 'circle':
      return { borderRadius: '50%' }
    case 'hex':
      // Flat-top hexagon: the Swift path starts at −30° and steps by 60°.
      return {
        clipPath:
          'polygon(75% 0%, 100% 50%, 75% 100%, 25% 100%, 0% 50%, 25% 0%)',
        borderRadius: 0,
      }
    case 'round':
      return { borderRadius: 12 }
    case 'stadium':
    default:
      return { borderRadius: h / 2, paddingLeft: Math.min(28, w * 0.12), paddingRight: Math.min(28, w * 0.12) }
  }
}

function StepNodeComponent({ id, data, dragging }: NodeProps) {
  const { name, step, nodeW, nodeH, scale, showDescription, groupProxy, hasNote, horizontal } =
    data as StepNodeData

  // Hover-dwell focus: the spotlit node and its neighbours stay bright; everything else dims.
  const focus = useContext(FlowFocusContext)
  const isFocused = focus?.node === id
  const dimmed = focus != null && !focus.nodes.has(id)

  // Aggregate "pick steps" mode — ring the chosen steps (bright) and banked ones (calm).
  const pick = useContext(AggregatePickContext)
  const isPicked = pick.active && pick.picked.has(id)
  const isBanked = pick.active && pick.banked.has(id)

  const background = groupProxy ? groupProxy.color : namedColor(step.bgColor)
  const foreground = groupProxy ? '#FFFFFF' : namedColor(step.fgColor)

  const description = step.description ?? ''
  const hasDescription =
    showDescription && description.length > 0 && description !== name
  const truncated =
    description.length > 20 ? `${description.slice(0, 20)}…` : description

  const scoreColor =
    step.score == null
      ? SCORE_NEUTRAL
      : step.score > 0
        ? SCORE_POSITIVE
        : step.score < 0
          ? SCORE_NEGATIVE
          : SCORE_NEUTRAL

  return (
    <div
      className={`step-node${dragging ? ' lifted' : ''}${
        hasDescription || step.eventTime ? ' split' : ''
      }${dimmed ? ' dimmed' : ''}${isFocused ? ' focused' : ''}${isPicked ? ' agg-picked' : ''}${
        isBanked ? ' agg-banked' : ''
      }`}
      style={{
        width: nodeW,
        height: nodeH,
        background,
        color: foreground,
        // Scales the node text (see .step-node font-size calc()s) in step with the
        // box, so the label always fits — it can never spill outside the node.
        ['--node-scale' as string]: scale,
        ...shapeStyle(step.shape, nodeW, nodeH),
      }}
      title={description && description !== name ? description : name}
    >
      <Handle
        type="target"
        position={horizontal ? Position.Left : Position.Top}
        isConnectable={false}
      />
      <Handle
        type="source"
        position={horizontal ? Position.Right : Position.Bottom}
        isConnectable={false}
      />

      {groupProxy ? (
        <div style={{ display: 'grid', justifyItems: 'center', gap: 2 }}>
          <span className="n-count">{groupProxy.memberCount}</span>
          <span className="n-count-label">
            {groupProxy.memberCount === 1 ? 'node' : 'nodes'}
          </span>
        </div>
      ) : step.eventTime ? (
        <div style={{ display: 'grid', justifyItems: 'center', gap: 2 }}>
          <span className="n-name">{name}</span>
          <span className="n-time">{formatTimeOnly(step.eventTime)}</span>
        </div>
      ) : hasDescription ? (
        <div style={{ display: 'grid', justifyItems: 'center', gap: 1, maxWidth: '100%' }}>
          <span className="n-name">{name}</span>
          <span className="n-sub">{truncated}</span>
        </div>
      ) : (
        <span className="n-name">{name}</span>
      )}

      {step.endOfProcess && <span className="node-badge eop" />}

      {step.score != null && (
        <span className="node-badge score" style={{ background: scoreColor }}>
          {step.score}
        </span>
      )}

      {hasNote && (
        <span
          className="node-badge note"
          style={{ background: NOTE_YELLOW }}
          title="This node has notes"
        >
          ✎
        </span>
      )}
    </div>
  )
}

export const StepNode = memo(StepNodeComponent)
