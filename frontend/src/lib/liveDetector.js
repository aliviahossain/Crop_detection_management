// On-device inference for the live scanner.
//
// Preference order, and why:
//
//   1. **In-browser ONNX** (onnxruntime-web, WASM). No network per frame, so it
//      works on a field connection or none at all, costs nothing to run, and is
//      the offline capability the problem statement rewards. The model is
//      fetched once from /detect/model and cached by the browser.
//   2. **Server /detect/frame.** Used when WASM cannot start (old browser) or
//      the model has not been trained yet. Still stateless, no case, no
//      advisory, no database write.
//   3. **Nothing.** Reported honestly; the scanner still lets the farmer
//      capture a photo and submit it through the normal /detect flow, which
//      routes to the expert queue.
//
// Thresholds come from /detect/thresholds so the on-device decoder applies the
// same tuned per-class cut-offs as the server. Otherwise the same leaf would be
// judged one way while scanning and another way after pressing Accept.

import * as ort from 'onnxruntime-web'
import { decodeDetections, letterboxParams } from './yoloDecode.js'
import { api } from './api.js'

const INPUT_SIZE = 640

export const MODE = {
  ONDEVICE: 'on-device',
  SERVER: 'server',
  UNAVAILABLE: 'unavailable',
}

export class LiveDetector {
  constructor() {
    this.session = null
    this.inputName = null
    this.mode = MODE.UNAVAILABLE
    this.classNames = []
    this.thresholds = {}
    this.defaultThreshold = 0.25
    this.iouThreshold = 0.45
    this.lowConfidenceThreshold = 0.55
    this.note = null
    this.canvas = null
    this.ctx = null
  }

  async init() {
    // Thresholds first: needed by both paths, and it tells us the class order.
    try {
      const cfg = await api.detectThresholds()
      this.classNames = cfg.classes || []
      this.thresholds = cfg.per_class || {}
      this.defaultThreshold = cfg.default ?? 0.25
      this.iouThreshold = cfg.iou_threshold ?? 0.45
      this.lowConfidenceThreshold = cfg.low_confidence_threshold ?? 0.55
    } catch {
      this.note = 'Could not reach the API for detection settings.'
    }

    try {
      // Serve the WASM binaries from our own origin so the scanner keeps
      // working offline once cached. A CDN here would break the offline story.
      ort.env.wasm.wasmPaths = '/ort/'
      ort.env.wasm.numThreads = 1 // no cross-origin isolation headers in dev
      ort.env.logLevel = 'error'

      const response = await fetch(api.modelUrl())
      if (!response.ok) {
        this.note =
          response.status === 404
            ? 'No trained model installed yet, so scanning falls back to the server.'
            : `Model download failed (${response.status}).`
        return this._fallback()
      }
      const buffer = await response.arrayBuffer()
      this.session = await ort.InferenceSession.create(buffer, {
        executionProviders: ['wasm'],
        graphOptimizationLevel: 'all',
      })
      this.inputName = this.session.inputNames[0]
      this.mode = MODE.ONDEVICE
      this.note = null
      return this.mode
    } catch (err) {
      this.note = `On-device inference unavailable (${err.message}). Using the server.`
      return this._fallback()
    }
  }

  async _fallback() {
    // Confirm the server can actually infer before promising that path.
    try {
      const status = await api.detectStatus()
      this.mode = status.available ? MODE.SERVER : MODE.UNAVAILABLE
      if (!status.available) this.note = status.note || 'No detection model installed.'
    } catch {
      this.mode = MODE.UNAVAILABLE
    }
    return this.mode
  }

  get available() {
    return this.mode !== MODE.UNAVAILABLE
  }

  _prepareCanvas() {
    if (!this.canvas) {
      this.canvas = document.createElement('canvas')
      this.canvas.width = INPUT_SIZE
      this.canvas.height = INPUT_SIZE
      this.ctx = this.canvas.getContext('2d', { willReadFrequently: true })
    }
    return this.ctx
  }

  /**
   * Run one frame. `source` is a <video> or <canvas>.
   * Returns { detections, top, mode, inferenceMs }.
   */
  async detect(source, sourceWidth, sourceHeight) {
    if (this.mode === MODE.ONDEVICE) {
      return this._detectOnDevice(source, sourceWidth, sourceHeight)
    }
    if (this.mode === MODE.SERVER) {
      return this._detectOnServer(source)
    }
    return { detections: [], top: null, mode: this.mode, inferenceMs: 0 }
  }

  async _detectOnDevice(source, sourceWidth, sourceHeight) {
    const ctx = this._prepareCanvas()
    const lb = letterboxParams(sourceWidth, sourceHeight, INPUT_SIZE)

    // Grey padding matches the server's letterbox fill (114,114,114).
    ctx.fillStyle = 'rgb(114,114,114)'
    ctx.fillRect(0, 0, INPUT_SIZE, INPUT_SIZE)
    ctx.drawImage(source, lb.padX, lb.padY, lb.drawWidth, lb.drawHeight)

    const { data } = ctx.getImageData(0, 0, INPUT_SIZE, INPUT_SIZE)
    const pixels = INPUT_SIZE * INPUT_SIZE
    const chw = new Float32Array(pixels * 3)
    for (let i = 0, p = 0; i < data.length; i += 4, p += 1) {
      chw[p] = data[i] / 255 // R plane
      chw[pixels + p] = data[i + 1] / 255 // G plane
      chw[2 * pixels + p] = data[i + 2] / 255 // B plane
    }

    const started = performance.now()
    const tensor = new ort.Tensor('float32', chw, [1, 3, INPUT_SIZE, INPUT_SIZE])
    const output = await this.session.run({ [this.inputName]: tensor })
    const first = output[this.session.outputNames[0]]
    const inferenceMs = performance.now() - started

    const detections = decodeDetections(first.data, first.dims, {
      classNames: this.classNames,
      thresholds: this.thresholds,
      defaultThreshold: this.defaultThreshold,
      iouThreshold: this.iouThreshold,
      letterbox: lb,
      sourceWidth,
      sourceHeight,
    })
    return {
      detections,
      top: detections[0] || null,
      mode: MODE.ONDEVICE,
      inferenceMs: Math.round(inferenceMs),
    }
  }

  async _detectOnServer(source) {
    const canvas = document.createElement('canvas')
    canvas.width = source.videoWidth || source.width
    canvas.height = source.videoHeight || source.height
    canvas.getContext('2d').drawImage(source, 0, 0)
    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', 0.7),
    )
    const started = performance.now()
    const form = new FormData()
    form.append('image', blob, 'frame.jpg')
    const result = await api.detectFrame(form)
    const detections = (result.detections || []).map((d) => ({
      classKey: d.class_key,
      confidence: d.confidence,
      bboxNorm: d.bbox_norm,
    }))
    return {
      detections,
      top: detections[0] || null,
      mode: MODE.SERVER,
      inferenceMs: Math.round(performance.now() - started),
    }
  }

  dispose() {
    this.session?.release?.()
    this.session = null
  }
}
