import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useT } from '../lib/i18n.js'
import { LiveDetector, MODE } from '../lib/liveDetector.js'
import { PlantTracker } from '../lib/plantTracker.js'
import { useVideoDevices } from '../lib/useVideoDevices.js'

// CropRow lab: single-class crop (lettuce) localization, the croprow model
// (croprow/models/). Two ways in -- a live camera (same camera picker as Live
// scan) or an uploaded video clip -- both feeding one <video> and the croprow
// detector via its own /croprow endpoints. This is a preview only: it draws
// boxes and a live plant count as the footage plays and saves nothing, so it
// stays fully walled off from the potato /detect case flow.
const TARGET_FPS = 8
const BOX_COLOR = '#4ade80' // one class, one colour

export default function CropRowPage() {
  const t = useT()
  const navigate = useNavigate()

  const videoRef = useRef(null)
  const overlayRef = useRef(null)
  const detectorRef = useRef(null)
  const loopRef = useRef(null)
  const busyRef = useRef(false)
  const objectUrlRef = useRef(null)
  const trackerRef = useRef(new PlantTracker())

  const [source, setSource] = useState('idle') // idle|live|upload
  const [cameraState, setCameraState] = useState('idle') // idle|starting|live|denied|error
  const [cameraError, setCameraError] = useState(null)
  const { devices, refresh: refreshDevices } = useVideoDevices()
  const [deviceId, setDeviceId] = useState('') // '' = auto (rear camera on a phone)
  const [fileName, setFileName] = useState(null)
  const [uploadUrl, setUploadUrl] = useState(null) // object URL of the chosen clip
  const [mode, setMode] = useState(null)
  const [modeNote, setModeNote] = useState(null)
  const [count, setCount] = useState(0)
  const [total, setTotal] = useState(0)
  const [peak, setPeak] = useState(0)
  const [topConf, setTopConf] = useState(null)
  const [stats, setStats] = useState({ fps: 0, inferenceMs: 0 })
  const [error, setError] = useState(null)

  // --------------------------------------------------------------- detector
  useEffect(() => {
    const detector = new LiveDetector({
      thresholds: () => api.croprowThresholds(),
      modelUrl: () => api.croprowModelUrl(),
      status: () => api.croprowStatus(),
      frame: (form) => api.croprowFrame(form),
    })
    detectorRef.current = detector
    detector.init().then((resolved) => {
      setMode(resolved)
      setModeNote(detector.note)
    })
    return () => {
      detector.dispose()
      stopEverything()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --------------------------------------------------------------- teardown
  const stopLoop = useCallback(() => {
    if (loopRef.current) {
      clearInterval(loopRef.current)
      loopRef.current = null
    }
  }, [])

  const releaseObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

  const stopEverything = useCallback(() => {
    stopLoop()
    const video = videoRef.current
    const stream = video?.srcObject
    stream?.getTracks?.().forEach((track) => track.stop())
    if (video) {
      video.srcObject = null
      video.removeAttribute('src')
      video.load?.()
    }
    releaseObjectUrl()
    const canvas = overlayRef.current
    canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height)
    trackerRef.current.reset()
    setCameraState('idle')
    setSource('idle')
    setUploadUrl(null)
    setFileName(null)
    setCount(0)
    setTotal(0)
    setPeak(0)
    setTopConf(null)
    setStats({ fps: 0, inferenceMs: 0 })
  }, [releaseObjectUrl, stopLoop])

  // --------------------------------------------------------------- live cam
  const startCamera = useCallback(async () => {
    stopEverything()
    setCameraError(null)
    setError(null)
    setCameraState('starting')
    setSource('live')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          ...(deviceId
            ? { deviceId: { exact: deviceId } }
            : { facingMode: { ideal: 'environment' } }),
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      })
      videoRef.current.srcObject = stream
      videoRef.current.muted = true
      await videoRef.current.play()
      setCameraState('live')
      refreshDevices() // labels are readable now that permission is granted
    } catch (err) {
      setCameraState(err.name === 'NotAllowedError' ? 'denied' : 'error')
      setCameraError(err.message)
      setSource('idle')
    }
  }, [deviceId, refreshDevices, stopEverything])

  // --------------------------------------------------------------- upload
  const onPickFile = useCallback(
    (e) => {
      const file = e.target.files?.[0]
      if (!file) return
      stopEverything()
      setError(null)
      // Clear any live stream, then let React set src from state. A muted
      // <video src> with autoPlay is the pattern that reliably auto-starts; the
      // onLoadedData handler below plays it explicitly as a belt-and-braces.
      if (videoRef.current) videoRef.current.srcObject = null
      const url = URL.createObjectURL(file)
      objectUrlRef.current = url
      setFileName(file.name)
      setUploadUrl(url)
      setSource('upload')
      e.target.value = '' // allow the same file to be picked again
    },
    [stopEverything],
  )

  // --------------------------------------------------------------- loop
  useEffect(() => {
    if (source === 'idle' || !detectorRef.current?.available) return undefined
    if (source === 'live' && cameraState !== 'live') return undefined

    let frames = 0
    let windowStart = performance.now()

    const tick = async () => {
      const video = videoRef.current
      const detector = detectorRef.current
      if (!video || !detector || busyRef.current) return
      if (video.readyState < 2 || video.paused || video.ended) return
      busyRef.current = true
      try {
        const width = video.videoWidth
        const height = video.videoHeight
        const result = await detector.detect(video, width, height)
        const { total: uniqueTotal } = trackerRef.current.update(result.detections)
        setCount(result.detections.length)
        setTotal(uniqueTotal)
        setPeak((p) => Math.max(p, result.detections.length))
        setTopConf(result.top ? result.top.confidence : null)
        drawOverlay(result.detections, width, height)

        frames += 1
        const elapsed = performance.now() - windowStart
        if (elapsed >= 1000) {
          setStats({ fps: Math.round((frames * 1000) / elapsed), inferenceMs: result.inferenceMs })
          frames = 0
          windowStart = performance.now()
        }
      } catch (err) {
        setError(err.message)
      } finally {
        busyRef.current = false
      }
    }

    loopRef.current = setInterval(tick, 1000 / TARGET_FPS)
    return () => clearInterval(loopRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, cameraState, mode])

  const drawOverlay = (dets, width, height) => {
    const canvas = overlayRef.current
    if (!canvas) return
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, width, height)
    ctx.lineWidth = Math.max(2, width / 320)
    ctx.strokeStyle = BOX_COLOR
    ctx.font = `${Math.max(12, width / 55)}px system-ui, sans-serif`
    for (const d of dets) {
      const [x1, y1, x2, y2] = d.bboxNorm.map((v, i) => v * (i % 2 === 0 ? width : height))
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
      const label = `${Math.round(d.confidence * 100)}%`
      const textWidth = ctx.measureText(label).width
      ctx.fillStyle = 'rgba(0,0,0,0.6)'
      ctx.fillRect(x1, Math.max(0, y1 - 20), textWidth + 10, 18)
      ctx.fillStyle = '#fff'
      ctx.fillText(label, x1 + 5, Math.max(13, y1 - 6))
      ctx.fillStyle = BOX_COLOR
    }
  }

  // --------------------------------------------------------------- render
  const live = source === 'live' && cameraState === 'live'
  const playing = live || (source === 'upload' && !!fileName)

  return (
    <main className="page">
      <div className="spread">
        <h1 style={{ margin: 0 }}>{t('nav.croprow')}</h1>
        <span className="badge medium">{t('croprow.badge')}</span>
      </div>
      <p className="lede">{t('croprow.tagline')}</p>

      {mode === MODE.UNAVAILABLE && (
        <div className="alert danger">
          <strong>{t('croprow.noModel')}</strong>
          {modeNote && <div className="small">{modeNote}</div>}
          <div className="small" style={{ marginTop: 6 }}>
            <a
              href="/check"
              onClick={(e) => {
                e.preventDefault()
                navigate('/check')
              }}
            >
              {t('croprow.noModelHelp')}
            </a>
          </div>
        </div>
      )}

      <div className="segmented" style={{ margin: '4px 0 14px' }}>
        <button
          className={source !== 'upload' ? 'active' : ''}
          onClick={() => source === 'upload' && stopEverything()}
          aria-pressed={source !== 'upload'}
        >
          {t('croprow.mode.live')}
        </button>
        <button
          className={source === 'upload' ? 'active' : ''}
          onClick={() => document.getElementById('croprow-file')?.click()}
          aria-pressed={source === 'upload'}
        >
          {t('croprow.mode.upload')}
        </button>
      </div>
      <input
        id="croprow-file"
        type="file"
        accept="video/*"
        onChange={onPickFile}
        style={{ display: 'none' }}
      />

      <div className="grid two">
        <div className="card">
          <div className="scan-frame">
            <video
              ref={videoRef}
              playsInline
              muted
              autoPlay
              loop={source === 'upload'}
              controls={source === 'upload'}
              src={source === 'upload' ? uploadUrl || undefined : undefined}
              className="scan-video"
              onLoadedData={(e) => {
                // React's `muted` prop does not reliably set the DOM property,
                // and an unmuted clip is blocked from autoplaying. Force it, then
                // start playback now that frames are available.
                const v = e.currentTarget
                v.muted = true
                setError(null) // a real frame decoded; drop any earlier warning
                v.play().catch((err) => setError(`Could not play video: ${err.message}`))
              }}
              onError={(e) => {
                // A codec the browser cannot decode (e.g. MPEG-4 Part 2 / mp4v,
                // which the LettuceMOTS clips use) loads metadata but never
                // renders. Say so plainly instead of showing a dead black frame.
                // Only fire for the clip that is *currently* loaded: swapping or
                // clearing a video briefly empties the src and emits a stray
                // error we must not mistake for a bad codec.
                const v = e.currentTarget
                if (v.currentSrc && v.currentSrc === objectUrlRef.current) {
                  setError(t('croprow.badFormat'))
                }
              }}
            />
            <canvas ref={overlayRef} className="scan-overlay" />

            {!playing && (
              <div className="scan-placeholder">
                {cameraState === 'denied' ? (
                  <>
                    <strong>{t('scan.denied')}</strong>
                    <span className="small">{t('scan.deniedHelp')}</span>
                  </>
                ) : cameraState === 'error' ? (
                  <>
                    <strong>{t('common.error')}</strong>
                    <span className="small">{cameraError}</span>
                  </>
                ) : (
                  <span className="small">{t('croprow.pickPrompt')}</span>
                )}
              </div>
            )}

            {playing && (
              <div className="scan-status low">
                {count > 0
                  ? `${count} ${t('croprow.plants')}`
                  : t('croprow.none')}
              </div>
            )}
          </div>

          {devices.length > 1 && source !== 'upload' && !live && (
            <label className="inline small" style={{ marginTop: 12, gap: 6 }}>
              <span className="muted">{t('scan.camera')}</span>
              <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
                <option value="">{t('scan.cameraAuto')}</option>
                {devices.map((d, i) => (
                  <option key={d.deviceId || i} value={d.deviceId}>
                    {d.label || `${t('scan.camera')} ${i + 1}`}
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="inline" style={{ marginTop: 12 }}>
            {source === 'upload' ? (
              <button className="ghost" onClick={stopEverything}>
                {t('croprow.clear')}
              </button>
            ) : live ? (
              <button className="ghost" onClick={stopEverything}>
                {t('scan.stop')}
              </button>
            ) : (
              <button
                className="primary auto"
                onClick={startCamera}
                disabled={cameraState === 'starting'}
              >
                {cameraState === 'starting' ? t('common.loading') : t('scan.start')}
              </button>
            )}
            <button className="ghost" onClick={() => document.getElementById('croprow-file')?.click()}>
              {t('croprow.mode.upload')}
            </button>
            {mode && mode !== MODE.UNAVAILABLE && (
              <span className={`badge ${mode === MODE.ONDEVICE ? 'low' : 'neutral'}`}>
                {mode === MODE.ONDEVICE ? t('scan.onDevice') : t('scan.serverMode')}
              </span>
            )}
            {playing && (
              <span className="muted small mono">
                {stats.fps} fps · {stats.inferenceMs} ms
              </span>
            )}
          </div>
          {fileName && (
            <p className="muted small" style={{ marginTop: 8 }}>
              {fileName}
            </p>
          )}
        </div>

        <div className="stack">
          <div className="card stack">
            <h2>{t('croprow.readout')}</h2>
            {!playing ? (
              <p className="muted">{t('croprow.idleHelp')}</p>
            ) : (
              <>
                <div className="spread">
                  <div className="headline">{total}</div>
                  <span className="badge low">{t('croprow.total')}</span>
                </div>
                <p className="muted small">
                  {t('croprow.inView')}: {count} · {t('croprow.peak')}: {peak}
                  {topConf != null && ` · ${t('result.confidence')} ${Math.round(topConf * 100)}%`}
                </p>
                <p className="muted small">{t('croprow.totalHint')}</p>
              </>
            )}
            {error && <div className="alert danger">{error}</div>}
          </div>

          <div className="card small muted">
            <strong>{t('croprow.badge')}</strong>
            <ul style={{ paddingLeft: 18, marginBottom: 0 }}>
              <li>{t('croprow.note1')}</li>
              <li>{t('croprow.note2')}</li>
              <li>{t('croprow.note3')}</li>
            </ul>
          </div>
        </div>
      </div>
    </main>
  )
}
