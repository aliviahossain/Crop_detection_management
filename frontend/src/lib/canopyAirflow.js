// Canopy airflow -- an EXPERIMENTAL, hyperlocal proxy for how much air is moving
// at leaf level, estimated passively from the live scanner's frames.
//
// The physical hunch: still air lets dew linger (longer leaf wetness) and lets
// spores settle locally -- both raise potato blight pressure. A far-off weather
// station cannot see that; the canopy in front of the camera can.
//
// This is NOT a calibrated anemometer. It is a RELATIVE indicator with three
// coarse levels. It never reports m/s and must always be shown as experimental.
//
// How it works (all classical pixel math -- no model, no training):
//   1. Reduce each frame to luma on the small 96x96 grid the scanner already
//      produces for its quality gate (so we add no extra draw or capture).
//   2. Subtract the global brightness change between frames -- kills camera
//      auto-exposure flicker that would otherwise read as "motion".
//   3. THE MAKE-OR-BREAK STEP: camera shake moves the whole frame together,
//      so it is well approximated by a single global translation. Wind moves
//      leaves independently, which no single translation can cancel. We search
//      a small set of integer pixel shifts for the one that best aligns this
//      frame to the previous one (that shift IS the shake) and take the
//      residual difference AFTER compensating it. Shake is absorbed into the
//      shift and removed; independent leaf motion survives.
//   4. Smooth the residual over a short window (EMA) and map it to a level.

const GRID = 96 // must match QUALITY_CANVAS in ScanPage; we read that same buffer

// Global-shift search radius, in pixels on the 96px grid. Camera shake between
// two frames ~4fps apart is small; +/-3 covers it while staying cheap.
const MAX_SHIFT = 3
// Subsample stride inside the shift search -- every other pixel is plenty at
// this resolution and keeps the whole thing well under a millisecond.
const STRIDE = 2

// EMA smoothing. Higher = steadier readout, slower to react. At ~4fps this
// gives a roughly 1.5s effective window -- long enough to ignore a single
// twitchy frame, short enough to tell still from breezy in a few seconds.
const EMA_ALPHA = 0.35

// Frames to observe before we trust a level at all (need a baseline first).
const WARMUP_FRAMES = 4

// Level thresholds on the smoothed residual, in mean luma-delta units (0-255
// scale). These are RELATIVE and uncalibrated -- tuned to broad potato canopy,
// deliberately coarse, and intended only to separate dead-still air from an
// obvious breeze. Do not read physical wind speed into them.
const STILL_MAX = 1.6 // below this: essentially no independent leaf motion
const LIGHT_MAX = 4.5 // below this: gentle stirring; above: an obvious breeze

export const AIRFLOW_LEVELS = ['still', 'light', 'breezy']

function levelFor(smoothed) {
  if (smoothed < STILL_MAX) return 'still'
  if (smoothed < LIGHT_MAX) return 'light'
  return 'breezy'
}

export class CanopyAirflow {
  constructor() {
    this.reset()
  }

  reset() {
    this._prev = null // Float32Array luma of the previous frame
    this._prevMean = 0
    this._smoothed = 0
    this._samples = 0
  }

  // Convert an RGBA ImageData (expected GRID x GRID) to a luma buffer + mean.
  _toLuma(imageData) {
    const { data, width, height } = imageData
    const n = width * height
    const luma = new Float32Array(n)
    let sum = 0
    for (let i = 0, p = 0; i < n; i++, p += 4) {
      // Rec. 601 luma; the exact weights do not matter for a difference signal.
      const y = 0.299 * data[p] + 0.587 * data[p + 1] + 0.114 * data[p + 2]
      luma[i] = y
      sum += y
    }
    return { luma, mean: sum / n, width, height }
  }

  // Mean absolute difference between cur and prev under an integer shift
  // (dx, dy) applied to the current frame, with a global brightness offset
  // removed. Only the overlapping region is compared. Subsampled by STRIDE.
  _shiftedMad(cur, prev, w, h, dx, dy, brightnessDelta) {
    let acc = 0
    let count = 0
    const x0 = Math.max(0, -dx)
    const x1 = Math.min(w, w - dx)
    const y0 = Math.max(0, -dy)
    const y1 = Math.min(h, h - dy)
    for (let y = y0; y < y1; y += STRIDE) {
      const curRow = y * w
      const prevRow = (y + dy) * w
      for (let x = x0; x < x1; x += STRIDE) {
        // Compare cur(x,y) against prev(x+dx, y+dy); removing brightnessDelta
        // (mean cur - mean prev) so an exposure change is not counted as motion.
        const d = cur[curRow + x] - brightnessDelta - prev[prevRow + x + dx]
        acc += d < 0 ? -d : d
        count++
      }
    }
    return count ? acc / count : 0
  }

  /**
   * Feed one frame. `imageData` is the RGBA buffer the scanner already grabs
   * for its quality gate, so this costs one extra pass over 96x96 pixels.
   *
   * Returns a plain object:
   *   ready         - false during warm-up; the level is not trustworthy yet
   *   level         - 'still' | 'light' | 'breezy' | null
   *   index         - this frame's residual (independent) motion, raw
   *   smoothed      - EMA-smoothed residual that `level` is derived from
   *   rawIndex      - motion BEFORE shake compensation (for comparison/telemetry)
   *   shakeRemoved  - rawIndex - index; how much motion was global (camera shake)
   *   samples       - frames observed so far
   */
  push(imageData) {
    const { luma, mean, width: w, height: h } = this._toLuma(imageData)

    if (!this._prev) {
      this._prev = luma
      this._prevMean = mean
      this._samples = 1
      return this._result(false, 0, 0)
    }

    const brightnessDelta = mean - this._prevMean

    // rawIndex: motion with NO shake compensation (dx=dy=0). This is what a
    // naive "mean pixel change" detector would report -- and what would light
    // up on camera shake. We keep it only to show the compensation is working.
    const rawIndex = this._shiftedMad(luma, this._prev, w, h, 0, 0, brightnessDelta)

    // Find the global shift that best aligns the two frames. Its residual is
    // the motion that shake cannot explain -- our wind signal.
    let best = rawIndex
    for (let dy = -MAX_SHIFT; dy <= MAX_SHIFT; dy++) {
      for (let dx = -MAX_SHIFT; dx <= MAX_SHIFT; dx++) {
        if (dx === 0 && dy === 0) continue
        const mad = this._shiftedMad(luma, this._prev, w, h, dx, dy, brightnessDelta)
        if (mad < best) best = mad
      }
    }
    const index = best // residual after removing the best global translation
    const shakeRemoved = Math.max(0, rawIndex - index)

    this._prev = luma
    this._prevMean = mean
    this._samples++

    // EMA. Seed on the first real measurement so we do not crawl up from zero.
    this._smoothed =
      this._samples <= 2 ? index : EMA_ALPHA * index + (1 - EMA_ALPHA) * this._smoothed

    const ready = this._samples >= WARMUP_FRAMES
    return this._result(ready, index, rawIndex, shakeRemoved)
  }

  _result(ready, index, rawIndex, shakeRemoved = 0) {
    return {
      ready,
      level: ready ? levelFor(this._smoothed) : null,
      index: round(index),
      smoothed: round(this._smoothed),
      rawIndex: round(rawIndex),
      shakeRemoved: round(shakeRemoved),
      samples: this._samples,
    }
  }
}

const round = (v) => Math.round(v * 100) / 100
