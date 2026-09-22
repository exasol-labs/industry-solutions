import { memo } from 'react'
import type { NodeProps } from '@xyflow/react'
import { END_ARROW_COLOR, START_ARROW_COLOR } from '../graph/colors'

export interface MarkerData extends Record<string, unknown> {
  kind: 'start' | 'end'
  /** Left-to-right layout: draw the arrow pointing right instead of down. */
  horizontal?: boolean
}

/** Geometry from `drawStartArrow` / `drawEndArrow`: 46 pt stem, 15 pt head,
 *  13 pt half-width, 7 pt dot. */
export const MARKER_W = 30
export const MARKER_H = 60

function MarkerNodeComponent({ data }: NodeProps) {
  const { kind, horizontal } = data as MarkerData
  const color = kind === 'start' ? START_ARROW_COLOR : END_ARROW_COLOR

  // The glyph points along the flow: downward for a top-to-bottom map, rightward for a
  // left-to-right one — dot at the tail, arrowhead at the tip. A start marker is placed
  // before the node so it points into it; an end marker after it so it points away —
  // same glyph, opposite placement (handled by the caller).
  const long = MARKER_H
  const cross = MARKER_W
  const half = cross / 2
  const dot = 7
  const tip = long
  const headBase = long - 15
  const stemFrom = dot + 9

  return (
    <svg
      width={horizontal ? long : cross}
      height={horizontal ? cross : long}
      style={{ overflow: 'visible', pointerEvents: 'none' }}
      aria-hidden
    >
      <g style={{ filter: 'drop-shadow(0 2px 5px rgba(0,0,0,0.35))' }}>
        {horizontal ? (
          <>
            <line x1={stemFrom} y1={half} x2={headBase} y2={half} stroke={color} strokeWidth={4} strokeLinecap="round" />
            <polygon points={`${tip},${half} ${headBase},${half - 13} ${headBase},${half + 13}`} fill={color} />
            <circle cx={dot} cy={half} r={7} fill={color} />
          </>
        ) : (
          <>
            <line x1={half} y1={stemFrom} x2={half} y2={headBase} stroke={color} strokeWidth={4} strokeLinecap="round" />
            <polygon points={`${half},${tip} ${half - 13},${headBase} ${half + 13},${headBase}`} fill={color} />
            <circle cx={half} cy={dot} r={7} fill={color} />
          </>
        )}
      </g>
    </svg>
  )
}

export const MarkerNode = memo(MarkerNodeComponent)
