import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useLang, useT } from '../lib/i18n.js'
import { LiveDetector, MODE } from '../lib/liveDetector.js'
import { STATUS, VerdictStabilizer } from '../lib/stabilizer.js'
import { assessFrame, hintFor } from '../lib/frameQuality.js'
import AdvisoryCard from '../components/AdvisoryCard.jsx'

// 4 fps. Fast enough to feel live, slow enough that a mid-range phone is not
// pinned at 100% CPU, which drains the battery and heats the device in a field.
const TARGET_FPS = 4
const QUALITY_CANVAS = 96

const VERDICT_TONE = {
  potato_healthy: 'low',
  potato_early_blight: 'medium',
  potato_late_blight: 'high',
}

export default function ScanPage() {
  const t = useT()
  const { lang } = useLang()
  const navigate = useNavigate()

  const videoRef = useRef(null)
  const overlayRef = useRef(null)
  const qualityCanvasRef = useRef(null)
  const detectorRef = useRef(null)
  const stabilizerRef = useRef(new VerdictStabilizer())
  const loopRef = useRef(null)
  const busyRef = useRef(false)

  const [cameraState, setCameraState] = useState('idle') // idle|starting|live|denied|error
  const [cameraError, setCameraError] = useState(null)
  const [mode, setMode] = useState(null)
  const [modeNote, setModeNote] = useState(null)
  const [verdict, setVerdict] = useState({ status: STATUS.SCANNING, progress: 0 })
  const [stats, setStats] = useState({ fps: 0, inferenceMs: 0 })
  const [accepted, setAccepted] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [classNames, setClassNames] = useState({})

  useEffect(() => {
    api
      .classes()
      .then((d) =>
        setClassNames(Object.fromEntries(d.classes.map((c) => [c.key, c.names?.[lang] || c.display]))),
      )
      .catch(() => {})
  }, [lang])

  // ---------------------------------------------------------------- camera
  const stopCamera = useCallback(() => {
    if (loopRef.current) {
      clearInterval(loopRef.current)
      loopRef.current = null
    }
    const stream = videoRef.current?.srcObject
    stream?.getTracks?.().forEach((track) => track.stop())
    if (videoRef.current) videoRef.current.srcObject = null
    setCameraState('idle')
  }, [])

  const startCamera = useCallback(async () => {
    setCameraError(null)
    setAccepted(null)
    setCameraState('starting')
    stabilizerRef.current.reset()
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          // Rear camera on a phone; ignored on a laptop.
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      })
      videoRef.current.srcObject = stream
      await videoRef.current.play()
      setCameraState('live')
    } catch (err) {
      setCameraState(err.name === 'NotAllowedError' ? 'denied' : 'error')
      setCameraError(err.message)
    }
  }, [])

  // ---------------------------------------------------------------- detector
  useEffect(() => {
    const detector = new LiveDetector()
    detectorRef.current = detector
    detector.init().then((resolved) => {
      setMode(resolved)
      setModeNote(detector.note)
    })
    return () => {
      detector.dispose()
      stopCamera()
    }
  }, [stopCamera])

  // ---------------------------------------------------------------- loop
  useEffect(() => {
    if (cameraState !== 'live' || !detectorRef.current?.available) return undefined

    let frames = 0
    let windowStart = performance.now()

    const tick = async () => {
      const video = videoRef.current
      const detector = detectorRef.current
      if (!video || !detector || busyRef.current) return
      if (video.readyState < 2) return
      busyRef.current = true
      try {
        const width = video.videoWidth
        const height = video.videoHeight

        // Quality gate on a small copy, cheap, and it runs every frame.
        if (!qualityCanvasRef.current) {
          qualityCanvasRef.current = document.createElement('canvas')
          qualityCanvasRef.current.width = QUALITY_CANVAS
          qualityCanvasRef.current.height = QUALITY_CANVAS
        }
        const qCtx = qualityCanvasRef.current.getContext('2d', { willReadFrequently: true })
        qCtx.drawImage(video, 0, 0, QUALITY_CANVAS, QUALITY_CANVAS)
        const quality = assessFrame(
          qCtx.getImageData(0, 0, QUALITY_CANVAS, QUALITY_CANVAS),
        )

        let result = { detections: [], top: null, inferenceMs: 0 }
        if (quality.ok) {
          // Only spend inference on frames worth judging.
          result = await detector.detect(video, width, height)
        }

        const next = stabilizerRef.current.push({
          classKey: result.top?.classKey ?? null,
          confidence: result.top?.confidence ?? 0,
          qualityOk: quality.ok,
          issues: quality.issues,
        })
        setVerdict({ ...next, quality })
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
  }, [cameraState, mode])

  const drawOverlay = (detections, width, height) => {
    const canvas = overlayRef.current
    if (!canvas) return
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, width, height)
    ctx.lineWidth = Math.max(2, width / 250)
    ctx.font = `${Math.max(14, width / 45)}px system-ui, sans-serif`
    for (const d of detections) {
      const [x1, y1, x2, y2] = d.bboxNorm.map((v, i) => v * (i % 2 === 0 ? width : height))
      const tone = VERDICT_TONE[d.classKey] === 'low' ? '#4ade80' : '#fbbf24'
      ctx.strokeStyle = d.classKey === 'potato_late_blight' ? '#f87171' : tone
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
      const label = `${classNames[d.classKey] || d.classKey} ${Math.round(d.confidence * 100)}%`
      const textWidth = ctx.measureText(label).width
      ctx.fillStyle = 'rgba(0,0,0,0.65)'
      ctx.fillRect(x1, Math.max(0, y1 - 26), textWidth + 12, 24)
      ctx.fillStyle = '#fff'
      ctx.fillText(label, x1 + 6, Math.max(16, y1 - 8))
    }
  }

  // ---------------------------------------------------------------- accept
  const accept = async () => {
    const video = videoRef.current
    if (!video) return
    setSubmitting(true)
    setError(null)
    try {
      // Freeze the exact frame the verdict was formed on and send it through
      // the full /detect pipeline -- so an accepted scan becomes a real case
      // with an advisory, triage and follow-up, identical to a photo upload.
      const canvas = document.createElement('canvas')
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      canvas.getContext('2d').drawImage(video, 0, 0)
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.9))

      const form = new FormData()
      form.append('image', blob, 'scan.jpg')
      form.append('crop', 'potato')
      form.append('language', lang)
      const position = await new Promise((resolve) =>
        navigator.geolocation
          ? navigator.geolocation.getCurrentPosition(resolve, () => resolve(null), {
              timeout: 5000,
            })
          : resolve(null),
      )
      if (position) {
        form.append('latitude', position.coords.latitude.toFixed(5))
        form.append('longitude', position.coords.longitude.toFixed(5))
      }

      const result = await api.detect(form)
      setAccepted(result)
      stopCamera()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const discard = () => {
    stabilizerRef.current.reset()
    setVerdict({ status: STATUS.SCANNING, progress: 0 })
    setError(null)
  }

  // ---------------------------------------------------------------- render
  const stable = verdict.status === STATUS.STABLE
  const verdictLabel = verdict.classKey ? classNames[verdict.classKey] || verdict.classKey : null
  const tone = VERDICT_TONE[verdict.classKey] || 'neutral'

  return (
    <main className="page">
      <h1>{t('nav.scan')}</h1>
      <p className="lede">{t('scan.help')}</p>

      {mode === MODE.UNAVAILABLE && (
        <div className="alert danger">
          <strong>{t('scan.noModel')}</strong>
          {modeNote && <div className="small">{modeNote}</div>}
          <div className="small" style={{ marginTop: 6 }}>
            <a href="/check" onClick={(e) => { e.preventDefault(); navigate('/check') }}>
              {t('scan.noModelHelp')}
            </a>
          </div>
        </div>
      )}

      {accepted ? (
        <div className="stack">
          <div className="card stack">
            <div className="spread">
              <h2 style={{ margin: 0 }}>{t('scan.accepted')}</h2>
              <span className="badge brand">#{accepted.case_id}</span>
            </div>
            <div className="headline">{accepted.predicted_display || t('scan.noDetection')}</div>
            {accepted.confidence != null && (
              <div className="muted">
                {t('result.confidence')}: {Math.round(accepted.confidence * 100)}%
              </div>
            )}
            <div className="inline">
              <button
                className="primary auto"
                onClick={() => {
                  setAccepted(null)
                  startCamera()
                }}
              >
                {t('scan.scanAgain')}
              </button>
            </div>
          </div>
          <AdvisoryCard advisory={accepted.advisory} triage={accepted.triage} />
        </div>
      ) : (
        <div className="grid two">
          <div className="card">
            <div className="scan-frame">
              <video ref={videoRef} playsInline muted className="scan-video" />
              <canvas ref={overlayRef} className="scan-overlay" />

              {cameraState !== 'live' && (
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
                    <span className="small">{t('scan.pressStart')}</span>
                  )}
                </div>
              )}

              {cameraState === 'live' && (
                <div className={`scan-status ${stable ? tone : ''}`}>
                  {verdict.status === STATUS.POOR_QUALITY && verdict.issue
                    ? hintFor(verdict.issue, lang)
                    : verdict.status === STATUS.SCANNING
                      ? `${t('scan.holdSteady')} ${Math.round((verdict.progress || 0) * 100)}%`
                      : verdict.status === STATUS.UNSTABLE
                        ? t('scan.settling')
                        : verdictLabel
                          ? `${verdictLabel} · ${Math.round(verdict.confidence * 100)}%`
                          : t('scan.noDetection')}
                </div>
              )}
            </div>

            <div className="inline" style={{ marginTop: 12 }}>
              {cameraState === 'live' ? (
                <button className="ghost" onClick={stopCamera}>
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
              {mode && (
                <span className={`badge ${mode === MODE.ONDEVICE ? 'low' : 'neutral'}`}>
                  {mode === MODE.ONDEVICE ? t('scan.onDevice') : t('scan.serverMode')}
                </span>
              )}
              {cameraState === 'live' && (
                <span className="muted small mono">
                  {stats.fps} fps · {stats.inferenceMs} ms
                </span>
              )}
            </div>
            {modeNote && mode !== MODE.UNAVAILABLE && (
              <p className="muted small" style={{ marginTop: 8 }}>
                {modeNote}
              </p>
            )}
          </div>

          <div className="stack">
            <div className="card stack">
              <h2>{t('scan.verdict')}</h2>

              {!stable && (
                <p className="muted">
                  {verdict.status === STATUS.POOR_QUALITY
                    ? t('scan.qualityWait')
                    : verdict.status === STATUS.UNSTABLE
                      ? t('scan.unstableHelp')
                      : t('scan.scanningHelp')}
                </p>
              )}

              {stable && (
                <>
                  <div className="spread">
                    <div className="headline">{verdictLabel || t('scan.noDetection')}</div>
                    <span className={`badge ${tone}`}>
                      {Math.round((verdict.confidence || 0) * 100)}%
                    </span>
                  </div>
                  <p className="muted small">
                    {t('scan.agreement')}: {Math.round(verdict.agreement * 100)}% ·{' '}
                    {verdict.goodFrames} {t('scan.frames')}
                  </p>
                  {!verdict.classKey && <p className="alert">{t('scan.noDetectionHelp')}</p>}

                  <div className="inline">
                    <button
                      className="primary auto"
                      onClick={accept}
                      disabled={submitting}
                    >
                      {submitting ? t('common.loading') : `✓ ${t('scan.accept')}`}
                    </button>
                    <button className="ghost" onClick={discard} disabled={submitting}>
                      ✕ {t('scan.discard')}
                    </button>
                  </div>
                  <p className="muted small">{t('scan.acceptExplain')}</p>
                </>
              )}

              {error && <div className="alert danger">{error}</div>}
            </div>

            <div className="card small muted">
              <strong>{t('scan.howItWorks')}</strong>
              <ul style={{ paddingLeft: 18, marginBottom: 0 }}>
                <li>{t('scan.how1')}</li>
                <li>{t('scan.how2')}</li>
                <li>{t('scan.how3')}</li>
              </ul>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
