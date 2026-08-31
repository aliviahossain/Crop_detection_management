// Pure YOLO post-processing for in-browser inference.
//
// This is a deliberate mirror of backend/app/services/detector.py. The two
// decoders MUST agree: the same frame judged on-device and on the server has to
// produce the same class and the same box, or the farmer sees one answer while
// scanning and a different one after pressing Accept.
//
// Kept free of onnxruntime and DOM APIs so it can be unit-tested directly --
// the equivalent Python code has had two real bugs (a squeeze that collapsed the
// anchor axis, and an ambiguous output orientation), so this half gets tests too.

/**
 * Letterbox geometry: resize preserving aspect ratio, pad to square with grey.
 * Returns everything needed to draw the frame and to undo the transform later.
 */
export function letterboxParams(srcWidth, srcHeight, size = 640) {
  const scale = Math.min(size / srcWidth, size / srcHeight)
  const drawWidth = Math.round(srcWidth * scale)
  const drawHeight = Math.round(srcHeight * scale)
  return {
    scale,
    drawWidth,
    drawHeight,
    padX: Math.floor((size - drawWidth) / 2),
    padY: Math.floor((size - drawHeight) / 2),
    size,
  }
}

/**
 * Orient raw output to [numAnchors][4 + numClasses].
 *
 * Ultralytics emits (1, 4+nc, N); some export toolchains emit (1, N, 4+nc).
 * Match on the known class count first — guessing from which dimension is
 * larger silently mislabels everything if a model returns few anchors.
 */
export function orient(data, dims, numClasses) {
  const expected = 4 + numClasses
  const shape = dims.length === 3 ? [dims[1], dims[2]] : dims
  const [a, b] = shape

  let channelsFirst
  if (a === expected && b !== expected) channelsFirst = true
  else if (b === expected) channelsFirst = false
  else channelsFirst = a < b // fallback: a detect head has far more anchors than channels

  const numAnchors = channelsFirst ? b : a
  const rows = new Array(numAnchors)
  for (let i = 0; i < numAnchors; i += 1) {
    const row = new Float32Array(expected)
    for (let c = 0; c < expected; c += 1) {
      row[c] = channelsFirst ? data[c * numAnchors + i] : data[i * expected + c]
    }
    rows[i] = row
  }
  return rows
}

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

/** Greedy non-max suppression over one class. */
export function nms(boxes, scores, iouThreshold) {
  const order = scores.map((s, i) => i).sort((p, q) => scores[q] - scores[p])
  const keep = []
  const removed = new Set()
  for (const i of order) {
    if (removed.has(i)) continue
    keep.push(i)
    for (const j of order) {
      if (j === i || removed.has(j)) continue
      if (iou(boxes[i], boxes[j]) > iouThreshold) removed.add(j)
    }
  }
  return keep
}

/**
 * Decode a raw model output into detections in *source frame* pixel space.
 *
 * @param {Float32Array} data      flat output tensor
 * @param {number[]}     dims      tensor dims, e.g. [1, 7, 8400]
 * @param {object}       opts
 * @param {string[]}     opts.classNames      index -> class key
 * @param {object}       opts.thresholds      per-class confidence cut-offs
 * @param {number}       opts.defaultThreshold
 * @param {number}       opts.iouThreshold
 * @param {object}       opts.letterbox       from letterboxParams()
 * @param {number}       opts.sourceWidth
 * @param {number}       opts.sourceHeight
 */
export function decodeDetections(data, dims, opts) {
  const {
    classNames,
    thresholds = {},
    defaultThreshold = 0.25,
    iouThreshold = 0.45,
    letterbox,
    sourceWidth,
    sourceHeight,
  } = opts

  const numClasses = classNames.length
  const rows = orient(data, dims, numClasses)
  if (!rows.length) return []

  const perClass = new Map()
  for (const row of rows) {
    let bestId = 0
    let bestScore = -Infinity
    for (let c = 0; c < numClasses; c += 1) {
      const score = row[4 + c]
      if (score > bestScore) {
        bestScore = score
        bestId = c
      }
    }
    const name = classNames[bestId]
    const cut = thresholds[name] ?? defaultThreshold
    if (bestScore < cut) continue

    const [cx, cy, w, h] = row
    // Undo the letterbox back into original-frame pixels.
    let x1 = (cx - w / 2 - letterbox.padX) / letterbox.scale
    let y1 = (cy - h / 2 - letterbox.padY) / letterbox.scale
    let x2 = (cx + w / 2 - letterbox.padX) / letterbox.scale
    let y2 = (cy + h / 2 - letterbox.padY) / letterbox.scale
    x1 = Math.min(Math.max(x1, 0), sourceWidth)
    y1 = Math.min(Math.max(y1, 0), sourceHeight)
    x2 = Math.min(Math.max(x2, 0), sourceWidth)
    y2 = Math.min(Math.max(y2, 0), sourceHeight)

    if (!perClass.has(bestId)) perClass.set(bestId, { boxes: [], scores: [] })
    const bucket = perClass.get(bestId)
    bucket.boxes.push([x1, y1, x2, y2])
    bucket.scores.push(bestScore)
  }

  const detections = []
  for (const [classId, { boxes, scores }] of perClass) {
    for (const idx of nms(boxes, scores, iouThreshold)) {
      const [x1, y1, x2, y2] = boxes[idx]
      detections.push({
        classKey: classNames[classId],
        confidence: scores[idx],
        bbox: [x1, y1, x2, y2],
        bboxNorm: [x1 / sourceWidth, y1 / sourceHeight, x2 / sourceWidth, y2 / sourceHeight],
      })
    }
  }
  detections.sort((a, b) => b.confidence - a.confidence)
  return detections
}
