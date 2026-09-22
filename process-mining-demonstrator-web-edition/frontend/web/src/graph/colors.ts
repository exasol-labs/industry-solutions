/** Colour helpers ported from Models.swift (`Color.named`, `EdgeColorSchema`)
 *  and FlowChartView.swift (`groupColor`). */

import type { TransitionMetric } from '../types'

/** SwiftUI system colours, sampled in light mode so the map looks the same. */
const NAMED_COLORS: Record<string, string> = {
  red: '#FF3B30',
  green: '#34C759',
  blue: '#007AFF',
  yellow: '#FFCC00',
  orange: '#FF9500',
  purple: '#AF52DE',
  gray: '#8E8E93',
  grey: '#8E8E93',
  black: '#000000',
  white: '#FFFFFF',
  cyan: '#32ADE6',
  mint: '#00C7BE',
  teal: '#30B0C7',
  indigo: '#5856D6',
  pink: '#FF2D55',
  brown: '#A2845E',
  accentcolor: '#0A84FF',
}

export const ACCENT = '#0A84FF'

/** `Color.named` — name, 6-digit hex, or the accent colour as a fallback. */
export function namedColor(name: string): string {
  const key = (name ?? '').trim().toLowerCase()
  if (key in NAMED_COLORS) return NAMED_COLORS[key]
  const hex = key.replace(/[^0-9a-f]/g, '')
  if (hex.length === 6) return `#${hex.toUpperCase()}`
  return ACCENT
}

export interface RGB {
  r: number
  g: number
  b: number
}

export function hexToRgb(hex: string): RGB {
  const h = hex.replace('#', '')
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  }
}

export function rgbToHex({ r, g, b }: RGB): string {
  const part = (v: number) =>
    Math.max(0, Math.min(255, Math.round(v)))
      .toString(16)
      .padStart(2, '0')
      .toUpperCase()
  return `#${part(r)}${part(g)}${part(b)}`
}

/** Linear RGB interpolation, matching `Color.interpolated(to:t:)`. */
export function interpolate(low: string, high: string, t: number): string {
  const a = hexToRgb(low)
  const b = hexToRgb(high)
  const clamped = Math.max(0, Math.min(1, t))
  return rgbToHex({
    r: a.r + (b.r - a.r) * clamped,
    g: a.g + (b.g - a.g) * clamped,
    b: a.b + (b.b - a.b) * clamped,
  })
}

export function rgba(hex: string, alpha: number): string {
  const { r, g, b } = hexToRgb(hex)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// ── Edge colour schemas ──────────────────────────────────────────────────────

export const EDGE_COLOR_SCHEMAS = [
  'neutral',
  'greenHigh',
  'redHigh',
  'blueScale',
  'orangeScale',
  'purpleScale',
] as const
export type EdgeColorSchema = (typeof EDGE_COLOR_SCHEMAS)[number]

export const EDGE_SCHEMA_LABELS: Record<EdgeColorSchema, string> = {
  neutral: 'None (grey)',
  greenHigh: 'Green (high is good)',
  redHigh: 'Red (low is good)',
  blueScale: 'Blue scale',
  orangeScale: 'Orange scale',
  purpleScale: 'Purple scale',
}

/** The exact RGB triples used by `EdgeColorSchema.gradientColors`. */
export const EDGE_SCHEMA_GRADIENTS: Record<
  EdgeColorSchema,
  { low: string; high: string } | null
> = {
  neutral: null,
  greenHigh: { low: rgbToHex({ r: 217, g: 38, b: 26 }), high: rgbToHex({ r: 26, g: 191, b: 51 }) },
  redHigh: { low: rgbToHex({ r: 26, g: 191, b: 51 }), high: rgbToHex({ r: 217, g: 38, b: 26 }) },
  blueScale: { low: rgbToHex({ r: 153, g: 209, b: 255 }), high: rgbToHex({ r: 13, g: 64, b: 204 }) },
  orangeScale: { low: rgbToHex({ r: 255, g: 235, b: 153 }), high: rgbToHex({ r: 230, g: 97, b: 0 }) },
  purpleScale: { low: rgbToHex({ r: 209, g: 184, b: 255 }), high: rgbToHex({ r: 102, g: 13, b: 204 }) },
}

export function defaultSchemaFor(metric: TransitionMetric): EdgeColorSchema {
  switch (metric) {
    case 'Count':
      return 'greenHigh'
    case 'Percentage':
      return 'greenHigh'
    case 'Journey %':
      return 'greenHigh'
    case 'Avg Time':
      return 'orangeScale'
    case 'Median Time':
      return 'orangeScale'
    case 'Min Time':
      return 'blueScale'
    case 'Max Time':
      return 'redHigh'
    case 'Std Dev':
      return 'purpleScale'
  }
}

/** Deterministic per-group hue — port of `FlowChartView.groupColor(for:)`.
 *  Uses the same `hash = hash*31 + scalar` accumulation over UTF-16 code units. */
export function groupColor(name: string): string {
  let hash = 0
  for (const ch of name) {
    hash = Math.trunc(hash * 31 + (ch.codePointAt(0) ?? 0))
    // Keep the value inside a safe integer range; Swift wraps on overflow, and
    // for realistic group names neither implementation overflows at all.
    hash = hash % 2147483647
  }
  const hue = (Math.abs(hash) % 360) / 360
  return hsbToHex(hue, 0.55, 0.72)
}

/** SwiftUI's `Color(hue:saturation:brightness:)`. */
export function hsbToHex(h: number, s: number, v: number): string {
  const i = Math.floor(h * 6)
  const f = h * 6 - i
  const p = v * (1 - s)
  const q = v * (1 - f * s)
  const t = v * (1 - (1 - f) * s)
  let r = 0
  let g = 0
  let b = 0
  switch (i % 6) {
    case 0:
      ;[r, g, b] = [v, t, p]
      break
    case 1:
      ;[r, g, b] = [q, v, p]
      break
    case 2:
      ;[r, g, b] = [p, v, t]
      break
    case 3:
      ;[r, g, b] = [p, q, v]
      break
    case 4:
      ;[r, g, b] = [t, p, v]
      break
    default:
      ;[r, g, b] = [v, p, q]
  }
  return rgbToHex({ r: r * 255, g: g * 255, b: b * 255 })
}

/** Start / end process markers. */
export const START_ARROW_COLOR = rgbToHex({ r: 46, g: 204, b: 97 })
export const END_ARROW_COLOR = rgbToHex({ r: 242, g: 107, b: 31 })

/** Collapse / expand badges: signal green (+) and signal red (−). */
export const COLLAPSE_BADGE_GREEN = rgbToHex({ r: 10, g: 184, b: 56 })
export const COLLAPSE_BADGE_RED = rgbToHex({ r: 219, g: 26, b: 26 })

export const SCORE_POSITIVE = NAMED_COLORS.green
export const SCORE_NEGATIVE = NAMED_COLORS.red
export const SCORE_NEUTRAL = NAMED_COLORS.blue
export const NOTE_YELLOW = '#FFD60A'
export const END_OF_PROCESS_DOT = NAMED_COLORS.orange
