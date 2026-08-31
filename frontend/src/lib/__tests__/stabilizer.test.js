// The stabilizer is what stops a pesticide decision resting on one lucky frame.
import { describe, expect, it } from 'vitest'
import { STATUS, VerdictStabilizer } from '../stabilizer.js'

const good = (classKey, confidence = 0.9) => ({
  classKey,
  confidence,
  qualityOk: true,
  issues: [],
})
const bad = (issue = 'too_blurry') => ({
  classKey: 'potato_late_blight',
  confidence: 0.95,
  qualityOk: false,
  issues: [issue],
})

function feed(stabilizer, frames) {
  let state
  for (const frame of frames) state = stabilizer.push(frame)
  return state
}

describe('VerdictStabilizer', () => {
  it('withholds a verdict until enough good frames arrive', () => {
    const s = new VerdictStabilizer({ minFrames: 6 })
    const state = feed(s, Array(3).fill(good('potato_late_blight')))
    expect(state.status).toBe(STATUS.SCANNING)
    expect(state.progress).toBeCloseTo(0.5, 5)
  })

  it('reaches a stable verdict once frames agree', () => {
    const s = new VerdictStabilizer()
    const state = feed(s, Array(8).fill(good('potato_late_blight', 0.88)))
    expect(state.status).toBe(STATUS.STABLE)
    expect(state.classKey).toBe('potato_late_blight')
    expect(state.confidence).toBeCloseTo(0.88, 4)
    expect(state.agreement).toBe(1)
  })

  it('never offers a verdict from a single lucky frame', () => {
    // Five frames say healthy, one says late blight. Without consensus the
    // scanner would flash a disease verdict off that one frame.
    const s = new VerdictStabilizer({ minFrames: 6, windowSize: 6 })
    const state = feed(s, [
      ...Array(5).fill(good('potato_healthy')),
      good('potato_late_blight', 0.99),
    ])
    expect(state.classKey).toBe('potato_healthy')
    expect(state.status).toBe(STATUS.STABLE)
  })

  it('stays unstable while readings disagree', () => {
    const s = new VerdictStabilizer({ minFrames: 6, windowSize: 6, agreement: 0.6 })
    const state = feed(s, [
      good('potato_late_blight'),
      good('potato_early_blight'),
      good('potato_late_blight'),
      good('potato_early_blight'),
      good('potato_healthy'),
      good('potato_early_blight'),
    ])
    expect(state.status).toBe(STATUS.UNSTABLE)
    expect(state.reason).toBe('readings_disagree')
  })

  it('stays unstable when the class agrees but confidence is too low', () => {
    const s = new VerdictStabilizer({ minFrames: 6, minConfidence: 0.55 })
    const state = feed(s, Array(8).fill(good('potato_late_blight', 0.3)))
    expect(state.status).toBe(STATUS.UNSTABLE)
    expect(state.reason).toBe('confidence_too_low')
  })

  it('never lets a poor-quality frame influence the verdict', () => {
    // The blurred frames all claim late blight at 0.95. If quality gating
    // leaked, the verdict would flip to late blight.
    const s = new VerdictStabilizer({ minFrames: 6, windowSize: 10 })
    const state = feed(s, [
      ...Array(6).fill(good('potato_healthy', 0.8)),
      ...Array(4).fill(bad()),
    ])
    expect(state.classKey).toBe('potato_healthy')
    expect(state.goodFrames).toBe(6)
  })

  it('reports the dominant quality problem when frames are unusable', () => {
    const s = new VerdictStabilizer({ minFrames: 6, windowSize: 10 })
    const state = feed(s, [...Array(6).fill(bad('too_dark')), bad('too_blurry')])
    expect(state.status).toBe(STATUS.POOR_QUALITY)
    expect(state.issue).toBe('too_dark')
  })

  it('treats a consistent no-detection as its own reportable outcome', () => {
    const s = new VerdictStabilizer()
    const state = feed(s, Array(8).fill(good(null, 0)))
    expect(state.status).toBe(STATUS.STABLE)
    expect(state.classKey).toBeNull()
  })

  it('drops frames outside the rolling window', () => {
    const s = new VerdictStabilizer({ windowSize: 6, minFrames: 6 })
    // Old healthy readings must age out as the leaf comes into view.
    const state = feed(s, [
      ...Array(6).fill(good('potato_healthy')),
      ...Array(6).fill(good('potato_late_blight', 0.9)),
    ])
    expect(state.classKey).toBe('potato_late_blight')
    expect(state.agreement).toBe(1)
  })

  it('reset clears the window so a new plant starts clean', () => {
    const s = new VerdictStabilizer()
    feed(s, Array(8).fill(good('potato_late_blight')))
    s.reset()
    expect(s.state().status).toBe(STATUS.SCANNING)
    expect(s.state().goodFrames).toBe(0)
  })
})
