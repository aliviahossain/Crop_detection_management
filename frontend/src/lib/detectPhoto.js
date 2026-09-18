// One entry point for "diagnose this photograph", whichever half of the
// system is actually able to do it.
//
// On the server deployment the image is uploaded and inference runs there. In
// the Android app there is no server to upload to: the on-device API has no
// ONNX runtime in its Dart process. But the WebView does have one, and it is
// already running the same weights for the live scanner, so the page does the
// inference itself and asks the local API only for the parts it cannot compute
// - the triage gate and the advisory.
//
// `/detect/status` says which applies via `inference: 'in_page'`. The server
// build has no such key, so it keeps uploading and nothing about it changes.
//
// This exists because the alternative was a farmer standing in a field being
// told to find a network connection for a diagnosis their phone could do on
// its own, with the model already downloaded.

import { api } from './api.js'
import { LiveDetector } from './liveDetector.js'

let detectorPromise = null
let statusPromise = null
let classesPromise = null

const status = () => {
  statusPromise ??= api.detectStatus().catch(() => ({}))
  return statusPromise
}

/// Re-read capability after a pack is installed or removed.
export function resetDetectionCache() {
  statusPromise = null
  classesPromise = null
  detectorPromise?.then((d) => d?.dispose?.()).catch(() => {})
  detectorPromise = null
}

async function displayName(classKey) {
  if (!classKey) return null
  classesPromise ??= api.classes().catch(() => ({ classes: [] }))
  const { classes } = await classesPromise
  return (classes || []).find((c) => c.key === classKey)?.display || classKey
}

// The session is a few tens of megabytes of weights; building it per photo
// would cost seconds and churn memory on exactly the cheap handsets this has
// to run on.
function detector() {
  detectorPromise ??= (async () => {
    const d = new LiveDetector()
    await d.init()
    return d
  })()
  return detectorPromise
}

const num = (form, key) => {
  const raw = form.get(key)
  return raw === null || raw === '' ? null : Number(raw)
}

async function bitmapFor(file) {
  if (typeof createImageBitmap === 'function') return createImageBitmap(file)
  // Safari and older WebViews: decode through an <img> instead.
  const url = URL.createObjectURL(file)
  try {
    const img = new Image()
    await new Promise((resolve, reject) => {
      img.onload = resolve
      img.onerror = () => reject(new Error('Could not read that image.'))
      img.src = url
    })
    return img
  } finally {
    URL.revokeObjectURL(url)
  }
}

/**
 * Diagnose a photograph. Takes the same FormData the upload path builds, so
 * the caller does not need to know which route it took.
 * Returns the server's DetectResponse shape either way.
 */
export async function detectPhoto(form) {
  const st = await status()
  if (st.inference !== 'in_page') return api.detect(form)

  const file = form.get('image')
  const language = form.get('language') || 'en'
  const latitude = num(form, 'latitude')
  const longitude = num(form, 'longitude')

  if (!st.model_available) {
    // Honest absence, not a network error. The case still deserves triage and
    // an escalation route; it just does not get a class.
    return withAdvice({
      classKey: null,
      confidence: null,
      detections: [],
      imageSize: null,
      language,
      latitude,
      longitude,
      modelAvailable: false,
      modelVersion: null,
      note:
        st.note ||
        'No crop model is installed on this phone, so this photo was not ' +
          'diagnosed. Install a crop from Menu > Crop models.',
    })
  }

  const d = await detector()
  if (!d.isAvailable?.() && d.mode === 'unavailable') {
    throw new Error(
      'The crop model is installed but could not be loaded on this phone.',
    )
  }

  const bitmap = await bitmapFor(file)
  const width = bitmap.width
  const height = bitmap.height
  const { detections } = await d.detect(bitmap, width, height)
  bitmap.close?.()

  const top = detections[0] || null
  return withAdvice({
    classKey: top?.classKey ?? null,
    confidence: top?.confidence ?? null,
    detections: detections.map((x) => ({
      class_key: x.classKey,
      confidence: x.confidence,
      bbox_norm: x.bboxNorm,
    })),
    imageSize: [width, height],
    language,
    latitude,
    longitude,
    modelAvailable: true,
    modelVersion: st.model_version || null,
    note: detections.length
      ? null
      : 'No symptom was recognised above the confidence threshold. That may ' +
        'mean a healthy crop, a photo taken too far from the leaf, or a ' +
        'problem outside the classes this model was trained on.',
  })
}

// The advisory, the triage gate and the risk forecast all come from the local
// API, which computes them offline. Only the pixels needed the page.
async function withAdvice(d) {
  const payload = {
    class_key: d.classKey,
    confidence: d.confidence,
    language: d.language,
    include_risk: true,
  }
  if (d.latitude != null && d.longitude != null) {
    payload.latitude = d.latitude
    payload.longitude = d.longitude
  }
  const res = await api.advisory(payload)

  return {
    // No case store on the handset yet, so nothing was persisted and saying
    // otherwise would be a lie the follow-up screen would trip over.
    case_id: null,
    model_available: d.modelAvailable,
    model_version: d.modelVersion,
    predicted_class: d.classKey,
    predicted_display: await displayName(d.classKey),
    confidence: d.confidence,
    detections: d.detections,
    image_size: d.imageSize,
    note: d.note,
    risk: res.risk ?? null,
    triage: res.triage ?? {},
    advisory: res.advisory ?? null,
    follow_up_id: null,
    language: res.language || d.language,
    on_device: true,
  }
}
