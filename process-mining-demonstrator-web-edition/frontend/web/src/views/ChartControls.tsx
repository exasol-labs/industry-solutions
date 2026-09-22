/** "Date & Metrics" card shared by the A-Chart, B-Chart and A/B panels —
 *  ports the controls card from ProcessMapView.swift. */

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { JourneyTimeSlider } from '../components/JourneyTimeSlider'
import { Chevron, Divider, Segmented } from '../components/ui'
import { useSetting } from '../settings'
import { useStore } from '../store'
import { TRANSITION_METRICS, type FilterGroup, type SliderMode, type TransitionMetric } from '../types'

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

export function ChartControls({
  expanded,
  onToggleExpanded,
  sliderMode,
  rangeMin,
  rangeMax,
  fromDate,
  toDate,
  onSliderChange,
  onSliderCommit,
  metric,
  onMetricChange,
  metricsDisabled,
  selectedPresetId,
  onApplyPreset,
}: {
  expanded: boolean
  onToggleExpanded: () => void
  sliderMode: SliderMode
  rangeMin: string
  rangeMax: string
  fromDate: string
  toDate: string
  onSliderChange: (from: string, to: string) => void
  onSliderCommit: (from: string, to: string) => void
  metric: TransitionMetric
  onMetricChange: (metric: TransitionMetric) => void
  metricsDisabled: boolean
  selectedPresetId: string | null
  onApplyPreset: (group: FilterGroup) => void
}) {
  // The date-slider mode (Range / Day) lives here, right under the slider it
  // controls, instead of in the sidebar. It writes the shared `slider.mode`
  // setting the parent reads back as the `sliderMode` prop.
  const [, setSliderMode] = useSetting<SliderMode>('slider.mode')
  return (
    <div className="controls-card">
      <div className="controls-head">
        <button className="expander" onClick={onToggleExpanded}>
          <Chevron open={expanded} />
          Date &amp; Metrics
        </button>
        <PresetMenu selectedPresetId={selectedPresetId} onApply={onApplyPreset} />
      </div>

      {expanded && (
        <>
          <Divider />
          <JourneyTimeSlider
            rangeMin={rangeMin}
            rangeMax={rangeMax}
            mode={sliderMode}
            fromDate={fromDate}
            toDate={toDate}
            onChange={onSliderChange}
            onCommit={onSliderCommit}
          />
          <Divider />
          <div className="metric-bar">
            {TRANSITION_METRICS.map((m) => (
              <button
                key={m}
                className={`chip${metric === m ? ' active' : ''}`}
                disabled={metricsDisabled}
                onClick={() => onMetricChange(m)}
              >
                <span aria-hidden>{METRIC_ICONS[m]}</span> {m}
              </button>
            ))}
            <div className="metric-bar-slider" title="Date slider mode">
              <span aria-hidden className="fg-secondary">
                ⇥
              </span>
              <Segmented
                options={[
                  { value: 'Range', label: 'Range' },
                  { value: 'Day', label: 'Day' },
                ]}
                value={sliderMode}
                onChange={setSliderMode}
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

/** Filter-preset picker with an inline manage menu: apply a preset, or delete one
 *  via the 🗑 button on its row. Replaces the plain <select> so presets can be
 *  removed without leaving the chart. */
function PresetMenu({
  selectedPresetId,
  onApply,
}: {
  selectedPresetId: string | null
  onApply: (group: FilterGroup) => void
}) {
  const store = useStore()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null)
  // Alphabetical, ascending (A→Z).
  const groups = [...store.filterGroups].sort((a, b) => a.name.localeCompare(b.name))
  const current = groups.find((g) => g.id === selectedPresetId)

  // Anchor the (portalled) menu to the button. Kept in a layout effect so the
  // position is measured before paint, and refreshed on scroll/resize since a
  // fixed-position element does not follow the anchor on its own.
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const r = wrapRef.current?.getBoundingClientRect()
      if (r) setPos({ top: r.bottom + 4, right: window.innerWidth - r.right })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node
      if (wrapRef.current?.contains(t) || menuRef.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (groups.length === 0) return null

  return (
    <div ref={wrapRef} className="preset-menu-wrap">
      <button
        className="preset-menu-btn"
        onClick={() => setOpen((v) => !v)}
        title="Filter presets"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="truncate">{current ? current.name : 'Presets'}</span>
        <span aria-hidden>▾</span>
      </button>
      {/* Portalled to the body so the card's overflow:hidden (rounded corners)
          never clips the list; it scrolls once it exceeds its max-height. */}
      {open &&
        pos &&
        createPortal(
          <div
            ref={menuRef}
            className="preset-menu"
            role="menu"
            style={{ position: 'fixed', top: pos.top, right: pos.right }}
          >
            {groups.map((group) => (
              <div key={group.id} className="preset-menu-row">
                <button
                  className="preset-menu-apply"
                  role="menuitem"
                  onClick={() => {
                    onApply(group)
                    setOpen(false)
                  }}
                >
                  <span className="preset-menu-check" aria-hidden>
                    {group.id === selectedPresetId ? '✓' : ''}
                  </span>
                  <span className="truncate">{group.name}</span>
                </button>
                <button
                  className="preset-menu-del"
                  title={`Delete “${group.name}”`}
                  aria-label={`Delete preset ${group.name}`}
                  onClick={() => store.deleteFilterGroup(group.id)}
                >
                  🗑
                </button>
              </div>
            ))}
          </div>,
          document.body,
        )}
    </div>
  )
}
