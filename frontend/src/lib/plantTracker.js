// Counts unique plants across video frames without double-counting one that
// stays in view. Per-frame detections have no identity, so summing them would
// count a plant once per frame; instead we match each frame's boxes to the
// previous frame's tracks by overlap (IoU) and only tick the total up when a
// box appears that matches no existing track.
//
// Geometry only, no appearance model -- which suits a cultivator camera moving
// steadily along a row. The one honest caveat: a plant that leaves the frame
// and later comes back is a new track, so on footage that pans back and forth
// over the same plants the total is an estimate, not a census.

function iou(a, b) {
  const x1 = Math.max(a[0], b[0])
  const y1 = Math.max(a[1], b[1])
  const x2 = Math.min(a[2], b[2])
  const y2 = Math.min(a[3], b[3])
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1)
  if (inter <= 0) return 0
  const areaA = Math.max(0, a[2] - a[0]) * Math.max(0, a[3] - a[1])
  const areaB = Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1])
  return inter / (areaA + areaB - inter + 1e-9)
}

export class PlantTracker {
  /**
   * @param {object}  opts
   * @param {number}  opts.iouThreshold  min overlap to call it the same plant
   * @param {number}  opts.maxAge        frames a track survives unmatched before
   *                                     it is dropped (rides out a missed detection)
   */
  constructor({ iouThreshold = 0.3, maxAge = 8 } = {}) {
    this.iouThreshold = iouThreshold
    this.maxAge = maxAge
    this.reset()
  }

  reset() {
    this.tracks = [] // { id, bbox:[x1,y1,x2,y2], missed }
    this.nextId = 1
    this.total = 0
  }

  /**
   * Advance one frame.
   * @param {Array<{bboxNorm:number[]}>} detections  normalised [x1,y1,x2,y2]
   * @returns {{ total:number, active:number }}
   */
  update(detections) {
    const boxes = (detections || []).map((d) => d.bboxNorm).filter(Boolean)
    const usedTracks = new Set()
    const usedDets = new Set()

    // Greedy match on descending overlap: the most confident pairing wins first,
    // and neither that track nor that detection can be reused.
    const pairs = []
    this.tracks.forEach((t, ti) => {
      boxes.forEach((b, di) => {
        const v = iou(t.bbox, b)
        if (v >= this.iouThreshold) pairs.push([v, ti, di])
      })
    })
    pairs.sort((p, q) => q[0] - p[0])
    for (const [, ti, di] of pairs) {
      if (usedTracks.has(ti) || usedDets.has(di)) continue
      usedTracks.add(ti)
      usedDets.add(di)
      this.tracks[ti].bbox = boxes[di]
      this.tracks[ti].missed = 0
    }

    // Age and prune existing tracks that went unmatched this frame.
    this.tracks = this.tracks.filter((t, ti) => {
      if (usedTracks.has(ti)) return true
      t.missed += 1
      return t.missed <= this.maxAge
    })

    // A detection matching no track is a plant we have not seen -> count it once.
    boxes.forEach((b, di) => {
      if (usedDets.has(di)) return
      this.tracks.push({ id: this.nextId++, bbox: b, missed: 0 })
      this.total += 1
    })

    return { total: this.total, active: this.tracks.filter((t) => t.missed === 0).length }
  }
}
