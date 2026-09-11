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

describe('per-class totals for the two-class health model', () => {
  const labelled = (b, classKey) => ({ ...b, classKey })

  test('a single-class model leaves the per-class breakdown empty', () => {
    const t = new PlantTracker()
    const { byClass } = t.update([box(0.1, 0.1, 0.2, 0.2)])
    expect(byClass).toEqual({})
  })

  test('each plant lands in exactly one class bucket', () => {
    const t = new PlantTracker()
    t.update([
      labelled(box(0.1, 0.1, 0.2, 0.2), 'healthy'),
      labelled(box(0.6, 0.6, 0.7, 0.7), 'unhealthy'),
    ])
    const { total, byClass } = t.update([
      labelled(box(0.1, 0.1, 0.2, 0.2), 'healthy'),
      labelled(box(0.6, 0.6, 0.7, 0.7), 'unhealthy'),
    ])
    expect(total).toBe(2)
    expect(byClass).toEqual({ healthy: 1, unhealthy: 1 })
  })

  test('a flickering label resolves to the majority, not the latest frame', () => {
    // The same plant reads unhealthy on one blurred frame. Taking the last
    // label would flip the readout; the plant is still counted once either way.
    const t = new PlantTracker()
    const b = box(0.3, 0.3, 0.4, 0.4)
    t.update([labelled(b, 'healthy')])
    t.update([labelled(b, 'healthy')])
    t.update([labelled(b, 'unhealthy')])
    const { total, byClass } = t.update([labelled(b, 'healthy')])
    expect(total).toBe(1)
    expect(byClass).toEqual({ healthy: 1 })
  })

  test('a plant that leaves view still counts in its class', () => {
    const t = new PlantTracker({ maxAge: 1 })
    t.update([labelled(box(0.1, 0.1, 0.2, 0.2), 'unhealthy')])
    t.update([]) // gone
    const { byClass } = t.update([]) // pruned
    expect(t.tracks).toHaveLength(0)
    expect(byClass).toEqual({ unhealthy: 1 })
  })

  test('reset clears the per-class totals too', () => {
    const t = new PlantTracker()
    t.update([labelled(box(0.1, 0.1, 0.2, 0.2), 'healthy')])
    t.reset()
    expect(t.update([]).byClass).toEqual({})
  })
})
