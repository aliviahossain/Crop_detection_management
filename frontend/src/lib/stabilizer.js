// Temporal consensus for the live scanner.
//
// A per-frame prediction flickers. Pointed at one diseased leaf, a detector will
// happily emit late blight, then early blight, then nothing, across three
// consecutive frames, and a UI that renders each frame directly shows a
// farmer a slot machine.
//
// Worse, it invites acting on a single lucky frame. A pesticide decision should
// not rest on 33 milliseconds of video.
//
// So no verdict is offered until the model has *agreed with itself* across a
// window of good-quality frames. The farmer holds the phone steady, the reading
// settles, and only then does Accept/Discard appear.

export const STABILIZER_DEFAULTS = {
  windowSize: 10, // frames considered, ~2.5s at 4 fps
  minFrames: 6, // good-quality frames required before any verdict
  agreement: 0.6, // share of the window that must name the same class
  minConfidence: 0.55, // mean confidence for the winning class
}

export const STATUS = {
  SCANNING: 'scanning', // not enough good frames yet
  POOR_QUALITY: 'poor_quality', // frames arriving, but unusable
  UNSTABLE: 'unstable', // readings disagree, keep holding
  STABLE: 'stable', // verdict ready
}

export class VerdictStabilizer {
  constructor(options = {}) {
    this.cfg = { ...STABILIZER_DEFAULTS, ...options }
    this.reset()
  }

  reset() {
    this.frames = [] // good-quality frames only
    this.recentQuality = []
  }

  /**
   * @param {object} frame
   * @param {string|null} frame.classKey    top class, or null if nothing detected
   * @param {number} frame.confidence
   * @param {boolean} frame.qualityOk
   * @param {string[]} frame.issues
   */
  push({ classKey = null, confidence = 0, qualityOk = true, issues = [] }) {
    this.recentQuality.push({ qualityOk, issues })
    if (this.recentQuality.length > this.cfg.windowSize) this.recentQuality.shift()

    // Bad frames are recorded for the hint, but must never dilute or corrupt the
    // consensus, a blurred frame's prediction is not evidence of anything.
    if (qualityOk) {
      this.frames.push({ classKey, confidence })
      if (this.frames.length > this.cfg.windowSize) this.frames.shift()
    }
    return this.state()
  }

  state() {
    const { windowSize, minFrames, agreement, minConfidence } = this.cfg
    const goodCount = this.frames.length
    const badCount = this.recentQuality.filter((q) => !q.qualityOk).length

    // Persistent bad quality is its own state: tell the farmer what to fix.
    if (badCount >= Math.ceil(windowSize / 2) && goodCount < minFrames) {
      const tally = new Map()
      for (const q of this.recentQuality) {
        for (const issue of q.issues) tally.set(issue, (tally.get(issue) || 0) + 1)
      }
      const dominant = [...tally.entries()].sort((a, b) => b[1] - a[1])[0]
      return {
        status: STATUS.POOR_QUALITY,
        issue: dominant ? dominant[0] : null,
        progress: goodCount / minFrames,
        goodFrames: goodCount,
      }
    }

    if (goodCount < minFrames) {
      return {
        status: STATUS.SCANNING,
        progress: goodCount / minFrames,
        goodFrames: goodCount,
      }
    }

    const tally = new Map()
    for (const f of this.frames) {
      const key = f.classKey ?? '__none__'
      if (!tally.has(key)) tally.set(key, { count: 0, confidenceSum: 0 })
      const entry = tally.get(key)
      entry.count += 1
      entry.confidenceSum += f.confidence
    }

    const [topKey, top] = [...tally.entries()].sort((a, b) => b[1].count - a[1].count)[0]
    const share = top.count / this.frames.length
    const meanConfidence = top.confidenceSum / top.count

    if (topKey === '__none__') {
      // The model consistently sees nothing. That is a real, reportable outcome
      // (bad framing, or a subject outside the three trained classes), not a
      // verdict about the crop.
      return {
        status: share >= agreement ? STATUS.STABLE : STATUS.UNSTABLE,
        classKey: null,
        confidence: 0,
        agreement: share,
        goodFrames: goodCount,
        progress: 1,
      }
    }

    const stable = share >= agreement && meanConfidence >= minConfidence
    return {
      status: stable ? STATUS.STABLE : STATUS.UNSTABLE,
      classKey: topKey,
      confidence: meanConfidence,
      agreement: share,
      goodFrames: goodCount,
      progress: 1,
      // Surfaced so the UI can explain *why* it is still unstable.
      reason: stable
        ? null
        : share < agreement
          ? 'readings_disagree'
          : 'confidence_too_low',
    }
  }
}
