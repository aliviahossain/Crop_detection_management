// The browser decoder must agree with backend/app/services/detector.py exactly.
// These cases mirror backend/tests/test_detector.py one-for-one, using the same
// numbers, so a divergence between the two implementations shows up here rather
// than as a farmer getting one answer while scanning and another after Accept.
import { describe, expect, it } from 'vitest'
import { decodeDetections, letterboxParams, nms, orient } from '../yoloDecode.js'

const CLASS_NAMES = ['potato_early_blight', 'potato_late_blight', 'potato_healthy']
const N_CLASSES = CLASS_NAMES.length

/** Build a (1, 4+nc, N) tensor, the ultralytics export layout. */
function yoloOutput(boxes, numAnchors = boxes.length) {
  const stride = 4 + N_CLASSES
  const rows = []
  for (let i = 0; i < numAnchors; i += 1) {
    const row = new Array(stride).fill(0)
    for (let c = 0; c < N_CLASSES; c += 1) row[4 + c] = 0.01
    rows.push(row)
  }
  boxes.forEach(([cx, cy, w, h, classId, conf], i) => {
    rows[i][0] = cx
    rows[i][1] = cy
    rows[i][2] = w
    rows[i][3] = h
    for (let c = 0; c < N_CLASSES; c += 1) rows[i][4 + c] = 0.01
    rows[i][4 + classId] = conf
  })
  // transpose to channels-first
  const data = new Float32Array(stride * numAnchors)
  for (let c = 0; c < stride; c += 1) {
    for (let i = 0; i < numAnchors; i += 1) data[c * numAnchors + i] = rows[i][c]
  }
  return { data, dims: [1, stride, numAnchors] }
}

const baseOpts = {
  classNames: CLASS_NAMES,
  defaultThreshold: 0.25,
  iouThreshold: 0.45,
  // 640x480 -> scale 1.0, 80px vertical padding. Same as the Python fixture.
  letterbox: letterboxParams(640, 480, 640),
  sourceWidth: 640,
  sourceHeight: 480,
}

describe('letterboxParams', () => {
  it('pads a landscape frame vertically', () => {
    const lb = letterboxParams(640, 480, 640)
    expect(lb.scale).toBe(1)
    expect(lb.padX).toBe(0)
    expect(lb.padY).toBe(80)
  })

  it('pads a portrait frame horizontally', () => {
    const lb = letterboxParams(480, 640, 640)
    expect(lb.scale).toBe(1)
    expect(lb.padX).toBe(80)
    expect(lb.padY).toBe(0)
  })

  it('scales down a frame larger than the input size', () => {
    const lb = letterboxParams(1280, 720, 640)
    expect(lb.scale).toBeCloseTo(0.5, 5)
    expect(lb.drawHeight).toBe(360)
  })
})

describe('orient', () => {
  it('transposes the channels-first export layout', () => {
    const { data, dims } = yoloOutput([[1, 2, 3, 4, 0, 0.9]])
    const rows = orient(data, dims, N_CLASSES)
    expect(rows).toHaveLength(1)
    expect(Array.from(rows[0].slice(0, 4))).toEqual([1, 2, 3, 4])
  })

  it('leaves an already channels-last layout alone', () => {
    const stride = 4 + N_CLASSES
    const data = new Float32Array([1, 2, 3, 4, 0.9, 0.01, 0.01])
    const rows = orient(data, [1, 1, stride], N_CLASSES)
    expect(Array.from(rows[0].slice(0, 4))).toEqual([1, 2, 3, 4])
  })

  it('handles a single anchor, where the shape heuristic is ambiguous', () => {
    // The Python decoder had this exact bug: a squeeze collapsed the anchor
    // axis when only one box came back.
    const { data, dims } = yoloOutput([[320, 320, 100, 100, 1, 0.8]], 1)
    expect(orient(data, dims, N_CLASSES)).toHaveLength(1)
  })
})

describe('decodeDetections', () => {
  it('decodes a box back into source-frame coordinates', () => {
    const { data, dims } = yoloOutput([[320, 320, 200, 100, 1, 0.9]])
    const [d] = decodeDetections(data, dims, baseOpts)

    expect(d.classKey).toBe('potato_late_blight')
    expect(d.confidence).toBeCloseTo(0.9, 4)
    // Identical expectation to test_detector.py.
    expect(d.bbox[0]).toBeCloseTo(220, 1)
    expect(d.bbox[1]).toBeCloseTo(190, 1)
    expect(d.bbox[2]).toBeCloseTo(420, 1)
    expect(d.bbox[3]).toBeCloseTo(290, 1)
    expect(d.bboxNorm[0]).toBeCloseTo(0.34375, 3)
    expect(d.bboxNorm[1]).toBeCloseTo(0.39583, 3)
  })

  it('maps class indices through the taxonomy order', () => {
    CLASS_NAMES.forEach((expected, idx) => {
      const { data, dims } = yoloOutput([[320, 320, 100, 100, idx, 0.8]])
      expect(decodeDetections(data, dims, baseOpts)[0].classKey).toBe(expected)
    })
  })

  it('filters out predictions below the default threshold', () => {
    const { data, dims } = yoloOutput([[320, 320, 100, 100, 0, 0.1]])
    expect(decodeDetections(data, dims, baseOpts)).toHaveLength(0)
  })

  it('applies tuned per-class thresholds', () => {
    // A faint late blight must survive its lowered cut-off; an unsure healthy
    // call must be suppressed by its raised one. Same asymmetry as the server.
    const { data, dims } = yoloOutput([
      [200, 320, 80, 80, 1, 0.14],
      [450, 320, 80, 80, 2, 0.55],
    ])
    const detections = decodeDetections(data, dims, {
      ...baseOpts,
      thresholds: { potato_late_blight: 0.12, potato_healthy: 0.8 },
    })
    expect(detections.map((d) => d.classKey)).toEqual(['potato_late_blight'])
  })

  it('suppresses overlapping boxes of the same class', () => {
    const { data, dims } = yoloOutput([
      [320, 320, 200, 200, 0, 0.9],
      [325, 322, 200, 200, 0, 0.7],
    ])
    expect(decodeDetections(data, dims, baseOpts)).toHaveLength(1)
  })

  it('keeps co-located boxes of different classes', () => {
    const { data, dims } = yoloOutput([
      [320, 320, 200, 200, 0, 0.9],
      [322, 321, 200, 200, 1, 0.85],
    ])
    const keys = decodeDetections(data, dims, baseOpts).map((d) => d.classKey)
    expect(new Set(keys)).toEqual(new Set(['potato_early_blight', 'potato_late_blight']))
  })

  it('returns the most confident detection first', () => {
    const { data, dims } = yoloOutput([
      [100, 320, 60, 60, 0, 0.55],
      [500, 320, 60, 60, 1, 0.88],
    ])
    const detections = decodeDetections(data, dims, baseOpts)
    expect(detections[0].classKey).toBe('potato_late_blight')
    expect(detections[0].confidence).toBeCloseTo(0.88, 4)
  })

  it('clips boxes running off the frame edge', () => {
    const { data, dims } = yoloOutput([[10, 320, 200, 100, 0, 0.9]])
    const [d] = decodeDetections(data, dims, baseOpts)
    expect(d.bbox[0]).toBeGreaterThanOrEqual(0)
    expect(d.bbox[2]).toBeLessThanOrEqual(640)
  })

  it('handles a realistic anchor count', () => {
    // A real 640px head emits 8400 anchors, nearly all background.
    const { data, dims } = yoloOutput([[320, 320, 200, 100, 2, 0.93]], 8400)
    const detections = decodeDetections(data, dims, baseOpts)
    expect(detections).toHaveLength(1)
    expect(detections[0].classKey).toBe('potato_healthy')
    expect(detections[0].bbox[1]).toBeCloseTo(190, 1)
  })
})

describe('nms', () => {
  it('returns nothing for an empty input', () => {
    expect(nms([], [], 0.5)).toEqual([])
  })

  it('keeps the higher-scoring of two overlapping boxes', () => {
    const boxes = [
      [0, 0, 10, 10],
      [1, 1, 11, 11],
    ]
    expect(nms(boxes, [0.6, 0.9], 0.5)).toEqual([1])
  })

  it('keeps both when they do not overlap', () => {
    const boxes = [
      [0, 0, 10, 10],
      [50, 50, 60, 60],
    ]
    expect(nms(boxes, [0.9, 0.8], 0.5).sort()).toEqual([0, 1])
  })
})
