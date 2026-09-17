import { afterEach, beforeEach, expect, test, vi } from 'vitest'

// The decision this file makes is whether a farmer's photograph needs a
// network connection. Getting it wrong sends someone standing in a field off
// to look for signal for a diagnosis their phone could already do, so the
// routing is pinned rather than eyeballed.

const detectMock = vi.fn()
const initMock = vi.fn()

vi.mock('../api.js', () => ({
  api: {
    detect: vi.fn(),
    detectStatus: vi.fn(),
    advisory: vi.fn(),
    classes: vi.fn(),
  },
}))

vi.mock('../liveDetector.js', () => ({
  MODE: { ONDEVICE: 'ondevice', SERVER: 'server', UNAVAILABLE: 'unavailable' },
  LiveDetector: class {
    constructor() {
      this.mode = 'ondevice'
    }
    init(...args) {
      return initMock(...args)
    }
    isAvailable() {
      return true
    }
    detect(...args) {
      return detectMock(...args)
    }
    dispose() {}
  },
}))

import { api } from '../api.js'
import { detectPhoto, resetDetectionCache } from '../detectPhoto.js'

beforeEach(() => {
  // Static imports plus an explicit cache reset: resetModules would re-run the
  // mock factory and hand the test a different set of spies than the module
  // under test is holding.
  vi.clearAllMocks()
  resetDetectionCache()

  globalThis.createImageBitmap = vi.fn(async () => ({
    width: 640,
    height: 480,
    close: () => {},
  }))
  api.classes.mockResolvedValue({
    classes: [{ key: 'potato_late_blight', display: 'Potato - Late Blight' }],
  })
  api.advisory.mockResolvedValue({
    advisory: { summary: 'x' },
    triage: { escalate: true },
    risk: { overall_level: 'high' },
    language: 'mr',
  })
})

afterEach(() => {
  delete globalThis.createImageBitmap
})

const form = () => {
  const f = new FormData()
  f.append('image', new Blob(['x'], { type: 'image/jpeg' }), 'leaf.jpg')
  f.append('language', 'mr')
  f.append('latitude', '18.52')
  f.append('longitude', '73.86')
  return f
}

test('uploads to the server when the build has no in-page inference', async () => {
  // The web deployment. /detect/status carries no `inference` key at all.
  api.detectStatus.mockResolvedValue({ model_available: true })
  api.detect.mockResolvedValue({ case_id: 7 })

  const out = await detectPhoto(form())

  expect(api.detect).toHaveBeenCalledOnce()
  expect(out.case_id).toBe(7)
  expect(detectMock).not.toHaveBeenCalled()
})

test('runs in the page when the on-device API says so, and never uploads', async () => {
  api.detectStatus.mockResolvedValue({
    model_available: true,
    model_version: 'potato@1.0.1',
    inference: 'in_page',
  })
  detectMock.mockResolvedValue({
    detections: [
      { classKey: 'potato_late_blight', confidence: 0.91, bboxNorm: [0, 0, 1, 1] },
    ],
  })

  const out = await detectPhoto(form())

  // The whole point: no upload, so no connection needed.
  expect(api.detect).not.toHaveBeenCalled()
  expect(out.predicted_class).toBe('potato_late_blight')
  expect(out.predicted_display).toBe('Potato - Late Blight')
  expect(out.confidence).toBe(0.91)
  expect(out.image_size).toEqual([640, 480])
  expect(out.on_device).toBe(true)
  // Nothing was persisted on the handset, and claiming an id would break the
  // follow-up screen that tries to use it.
  expect(out.case_id).toBeNull()
  // Triage and advice still come from the local API.
  expect(out.triage).toEqual({ escalate: true })
  expect(out.advisory).toEqual({ summary: 'x' })
})

test('passes the location through so the risk half of the advisory is real', async () => {
  api.detectStatus.mockResolvedValue({ model_available: true, inference: 'in_page' })
  detectMock.mockResolvedValue({ detections: [] })

  await detectPhoto(form())

  expect(api.advisory).toHaveBeenCalledWith(
    expect.objectContaining({ latitude: 18.52, longitude: 73.86, include_risk: true }),
  )
})

test('an empty detection is reported as no symptom found, not as a failure', async () => {
  api.detectStatus.mockResolvedValue({ model_available: true, inference: 'in_page' })
  detectMock.mockResolvedValue({ detections: [] })

  const out = await detectPhoto(form())

  expect(out.predicted_class).toBeNull()
  expect(out.note).toMatch(/No symptom was recognised/)
  // Still triaged: a photo the model cannot read is exactly the case that
  // needs an escalation route.
  expect(out.triage).toEqual({ escalate: true })
})

test('with no pack installed it says so, and does not blame the network', async () => {
  api.detectStatus.mockResolvedValue({
    model_available: false,
    inference: 'in_page',
    note: 'No crop pack is installed, so photographs are routed to the expert queue.',
  })

  const out = await detectPhoto(form())

  expect(detectMock).not.toHaveBeenCalled()
  expect(api.detect).not.toHaveBeenCalled()
  expect(out.model_available).toBe(false)
  expect(out.note).toMatch(/No crop pack is installed/)
  expect(out.note).not.toMatch(/network|connection/i)
  expect(out.triage).toEqual({ escalate: true })
})

test('the ONNX session is built once and reused across photos', async () => {
  api.detectStatus.mockResolvedValue({ model_available: true, inference: 'in_page' })
  detectMock.mockResolvedValue({ detections: [] })

  await detectPhoto(form())
  await detectPhoto(form())

  // Tens of megabytes of weights: rebuilding per photo would cost seconds on
  // the cheap handsets this has to run on.
  expect(initMock).toHaveBeenCalledOnce()
  expect(detectMock).toHaveBeenCalledTimes(2)
})

test('resetDetectionCache re-reads capability after a pack is installed', async () => {
  api.detectStatus.mockResolvedValueOnce({ model_available: false, inference: 'in_page' })
  await detectPhoto(form())
  expect(detectMock).not.toHaveBeenCalled()

  // A pack lands; without the reset the page would keep believing there is no
  // model until the app restarts.
  resetDetectionCache()
  api.detectStatus.mockResolvedValueOnce({ model_available: true, inference: 'in_page' })
  detectMock.mockResolvedValue({ detections: [] })
  await detectPhoto(form())

  expect(detectMock).toHaveBeenCalledOnce()
})
