import { describe, expect, it } from 'vitest'
import { visibleProjects } from './Sidebar'

// PROJECT_ID is an integer; the aggregate kind is marked in TITLE_SHORT:
// 'Σ…' = high-level (always visible), '#…' = detail (hidden unless shown/selected).
const P = [
  { projectId: 1, titleShort: 'BOOKSTORE' }, // normal
  { projectId: 2, titleShort: 'Σ2' },        // aggregate high-level map — always visible
  { projectId: 3, titleShort: '#3' },        // aggregate detail — hidden unless shown/selected
  { projectId: 4, titleShort: '#4' },
]

describe('visibleProjects (sidebar count == list)', () => {
  it('hides aggregate detail projects when the setting is off', () => {
    const v = visibleProjects(P, false, undefined)
    expect(v.map((p) => p.projectId)).toEqual([1, 2])
  })

  it('keeps the currently-open detail project visible even when hidden', () => {
    const v = visibleProjects(P, false, 4)
    expect(v.map((p) => p.projectId)).toEqual([1, 2, 4])
  })

  it('shows everything when the setting is on', () => {
    expect(visibleProjects(P, true, undefined)).toHaveLength(4)
  })
})
