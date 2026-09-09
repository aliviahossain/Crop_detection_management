import { describe, expect, test } from 'vitest'
import { PlantTracker } from '../plantTracker.js'

const box = (x1, y1, x2, y2) => ({ bboxNorm: [x1, y1, x2, y2] })

describe('PlantTracker counts unique plants, not frames', () => {
  test('a plant held in view across frames counts once', () => {
    const t = new PlantTracker()
    const plant = box(0.1, 0.1, 0.2, 0.2)
    t.update([plant])
    t.update([box(0.11, 0.1, 0.21, 0.2)]) // drifted slightly, same plant
    t.update([box(0.12, 0.1, 0.22, 0.2)])
    expect(t.total).toBe(1)
  })

  test('a genuinely new box adds to the total', () => {
    const t = new PlantTracker()
    t.update([box(0.1, 0.1, 0.2, 0.2)])
    t.update([box(0.1, 0.1, 0.2, 0.2), box(0.6, 0.6, 0.7, 0.7)]) // second plant enters
    expect(t.total).toBe(2)
    expect(t.update([]).active).toBe(0)
  })

  test('a one-frame miss does not split a plant into two', () => {
    const t = new PlantTracker({ maxAge: 3 })
    t.update([box(0.4, 0.4, 0.5, 0.5)])
    t.update([]) // detector blinked
    t.update([box(0.41, 0.4, 0.51, 0.5)]) // same plant reacquired within maxAge
    expect(t.total).toBe(1)
  })

  test('reset clears the running total', () => {
    const t = new PlantTracker()
    t.update([box(0.1, 0.1, 0.2, 0.2)])
    t.reset()
    expect(t.total).toBe(0)
    expect(t.tracks).toHaveLength(0)
  })
})
