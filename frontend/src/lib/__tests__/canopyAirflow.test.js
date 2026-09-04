import { describe, expect, it } from 'vitest'
import { CanopyAirflow } from '../canopyAirflow.js'

const SIZE = 64

/** Build an RGBA ImageData-like object from a per-pixel luma function. */
function makeFrame(fn, size = SIZE) {
  const data = new Uint8ClampedArray(size * size * 4)
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const v = fn(x, y)
      const i = (y * size + x) * 4
      data[i] = data[i + 1] = data[i + 2] = v
      data[i + 3] = 255
    }
  }
  return { data, width: size, height: size }
}

// Deterministic PRNG so the "wind" case is reproducible.
function mulberry32(seed) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// A canopy-like textured base: spatially incoherent detail, so that a whole-
// frame translation of it produces a large *raw* pixel change (the exact thing
// camera shake does) while a single global shift can still realign it.
const rng = mulberry32(12345)
const noiseField = Array.from({ length: SIZE * SIZE }, () => 20 + Math.floor(rng() * 200))
const base = (x, y) => noiseField[y * SIZE + x]

// A clamped sampler for translating the whole scene (simulated camera shake).
const shifted = (sx, sy) => (x, y) => {
  const cx = Math.min(SIZE - 1, Math.max(0, x - sx))
  const cy = Math.min(SIZE - 1, Math.max(0, y - sy))
  return base(cx, cy)
}

/** Run several frames through and return the final reading. */
function feed(air, frames) {
  let out
  for (const f of frames) out = air.push(f)
  return out
}

describe('CanopyAirflow', () => {
  it('needs a few frames before it trusts a level', () => {
    const air = new CanopyAirflow()
    expect(air.push(makeFrame(base)).ready).toBe(false)
    expect(air.push(makeFrame(base)).ready).toBe(false)
  })

  it('reads dead-still air when consecutive frames are identical', () => {
    const air = new CanopyAirflow()
    const frame = makeFrame(base)
    const out = feed(air, Array.from({ length: 6 }, () => frame))
    expect(out.ready).toBe(true)
    expect(out.level).toBe('still')
    expect(out.smoothed).toBeLessThan(1)
  })

  it('reads breezy when leaves move independently between frames', () => {
    const air = new CanopyAirflow()
    // Each frame adds spatially incoherent jitter -- the signature of wind, and
    // exactly what no single global translation can cancel.
    const wind = mulberry32(999)
    const frames = Array.from({ length: 8 }, () =>
      makeFrame((x, y) => base(x, y) + Math.floor((wind() - 0.5) * 60)),
    )
    const out = feed(air, frames)
    expect(out.ready).toBe(true)
    expect(out.level).toBe('breezy')
    expect(out.index).toBeGreaterThan(4.5)
  })

  it('THE MAKE-OR-BREAK: camera shake is not mistaken for wind', () => {
    const air = new CanopyAirflow()
    // The whole scene translates by a constant each frame -- pure camera shake,
    // no independent leaf motion at all. A naive mean-pixel-change detector
    // would light up; ours must compensate the global shift and read 'still'.
    const frames = [
      makeFrame(base),
      makeFrame(shifted(2, 1)),
      makeFrame(base),
      makeFrame(shifted(2, 1)),
      makeFrame(base),
      makeFrame(shifted(1, 2)),
    ]
    const out = feed(air, frames)

    // The uncompensated signal is large (this is the false positive we avoid)...
    expect(out.rawIndex).toBeGreaterThan(4.5)
    // ...but after removing the global translation the residual is small...
    expect(out.index).toBeLessThan(out.rawIndex / 2)
    expect(out.shakeRemoved).toBeGreaterThan(0)
    // ...so shake does NOT get reported as a breeze.
    expect(out.level).not.toBe('breezy')
  })

  it('resets cleanly between camera sessions', () => {
    const air = new CanopyAirflow()
    feed(air, Array.from({ length: 5 }, () => makeFrame(base)))
    air.reset()
    expect(air.push(makeFrame(base)).ready).toBe(false)
    expect(air.push(makeFrame(base)).samples).toBe(2)
  })
})
