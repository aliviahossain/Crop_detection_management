import { describe, expect, it } from 'vitest'
import { assessFrame, hintFor } from '../frameQuality.js'

const SIZE = 64

/** Build an RGBA ImageData-like object from a per-pixel luma function. */
function makeFrame(fn, size = SIZE) {
  const data = new Uint8ClampedArray(size * size * 4)
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const value = fn(x, y)
      const i = (y * size + x) * 4
      data[i] = value
      data[i + 1] = value
      data[i + 2] = value
      data[i + 3] = 255
    }
  }
  return { data, width: size, height: size }
}

// A sharp checkerboard has strong second derivatives everywhere.
const sharp = () => makeFrame((x, y) => ((x >> 1) + (y >> 1)) % 2 === 0 ? 40 : 210)
// A smooth gradient is the signature of a blurred frame.
const blurred = () => makeFrame((x) => 100 + (x / SIZE) * 20)

describe('assessFrame', () => {
  it('accepts a sharp, well-exposed frame', () => {
    const result = assessFrame(sharp())
    expect(result.ok).toBe(true)
    expect(result.issues).toEqual([])
    expect(result.sharpness).toBeGreaterThan(45)
  })

  it('rejects a blurred frame', () => {
    const result = assessFrame(blurred())
    expect(result.ok).toBe(false)
    expect(result.issues).toContain('too_blurry')
  })

  it('rejects a frame shot in deep shade', () => {
    const result = assessFrame(makeFrame(() => 10))
    expect(result.ok).toBe(false)
    expect(result.issues).toContain('too_dark')
  })

  it('rejects a blown-out frame', () => {
    const result = assessFrame(makeFrame(() => 250))
    expect(result.ok).toBe(false)
    expect(result.issues).toContain('too_bright')
  })

  it('reports brightness on the 0-255 luma scale', () => {
    expect(assessFrame(makeFrame(() => 128)).brightness).toBe(128)
  })

  it('can report several problems at once', () => {
    // Dark *and* flat: both must surface so the hint picks the dominant one.
    const result = assessFrame(makeFrame(() => 12))
    expect(result.issues).toContain('too_dark')
    expect(result.issues).toContain('too_blurry')
  })

  it('honours overridden thresholds', () => {
    // Field tuning must be able to loosen the gate without a code change.
    const frame = blurred()
    expect(assessFrame(frame).ok).toBe(false)
    expect(assessFrame(frame, { minSharpness: 0, minBrightness: 0 }).ok).toBe(true)
  })
})

describe('hintFor', () => {
  it('returns an actionable hint in each language', () => {
    for (const lang of ['en', 'mr', 'hi', 'bn']) {
      const hint = hintFor('too_dark', lang)
      expect(hint).toBeTruthy()
      expect(hint).not.toBe('too_dark')
    }
  })

  it('falls back to English for an unknown language', () => {
    expect(hintFor('too_blurry', 'zz')).toBe(hintFor('too_blurry', 'en'))
  })

  it('returns the raw code for an unknown issue rather than crashing', () => {
    expect(hintFor('unknown_issue', 'en')).toBe('unknown_issue')
  })
})
