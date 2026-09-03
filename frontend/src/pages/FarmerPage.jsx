import { useState } from 'react'
import { api } from '../lib/api.js'
import { useLang, useT } from '../lib/i18n.js'
import AdvisoryCard from '../components/AdvisoryCard.jsx'
import RiskPanel from '../components/RiskPanel.jsx'
import FieldContextForm, { emptyContext } from '../components/FieldContextForm.jsx'

/** Draws the model's boxes over the farmer's own photo, so the diagnosis points
 *  at the lesion it actually saw instead of being a label taken on trust. */
function DetectionPreview({ src, detections }) {
  return (
    <div className="preview">
      <img src={src} alt="crop" />
      {detections.map((d, i) => {
        const [x1, y1, x2, y2] = d.bbox_norm
        return (
          <div
            key={i}
            className="bbox"
            style={{
              left: `${x1 * 100}%`,
              top: `${y1 * 100}%`,
              width: `${(x2 - x1) * 100}%`,
              height: `${(y2 - y1) * 100}%`,
            }}
          >
            <span>
              {d.class_display} {Math.round(d.confidence * 100)}%
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default function FarmerPage() {
  const t = useT()
  const { lang } = useLang()
  const [file, setFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [ctx, setCtx] = useState(emptyContext)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const pick = (event) => {
    const chosen = event.target.files?.[0]
    if (!chosen) return
    setFile(chosen)
    setPreviewUrl(URL.createObjectURL(chosen))
    setResult(null)
    setError(null)
  }

  const submit = async (event) => {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('image', file)
      form.append('crop', 'potato')
      form.append('language', lang)
      Object.entries(ctx).forEach(([key, value]) => {
        if (value !== '' && value !== null && value !== undefined && value !== 0) {
          form.append(key, value)
        }
      })
      setResult(await api.detect(form))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const reset = () => {
    setFile(null)
    setPreviewUrl(null)
    setResult(null)
    setError(null)
  }

  return (
    <main className="page">
      <h1>{t('farmer.heading')}</h1>
      <p className="lede">{t('farmer.help')}</p>

      <div className="grid two">
        <form className="card stack" onSubmit={submit}>
          <label className="file-drop">
            <span className="ico" aria-hidden="true">
              📷
            </span>
            <b>{file ? file.name : t('farmer.choose')}</b>
            <small>{t('farmer.tapPhoto')}</small>
            <input type="file" accept="image/*" capture="environment" onChange={pick} />
          </label>

          {previewUrl && !result && (
            <img src={previewUrl} alt="" style={{ maxWidth: '100%', borderRadius: 10 }} />
          )}

          <details>
            <summary>{t('farmer.details')}</summary>
            <p className="muted small" style={{ marginTop: 6 }}>
              {t('farmer.detailsHelp')}
            </p>
            <FieldContextForm value={ctx} onChange={setCtx} showPersonal />
          </details>

          <button className="primary" type="submit" disabled={!file || busy}>
            {busy ? t('farmer.analysing') : t('farmer.submit')}
          </button>

          {result && (
            <button type="button" className="ghost" onClick={reset}>
              {t('result.newCheck')}
            </button>
          )}

          {error && <div className="alert danger">{error}</div>}
        </form>

        <div className="stack">
          {!result && <div className="card muted">{t('farmer.waiting')}</div>}

          {result && (
            <>
              <div className="card stack">
                <div className="spread">
                  <h2 style={{ margin: 0 }}>{t('result.diagnosis')}</h2>
                  {result.escalate || result.triage?.escalate ? (
                    <span className="badge high">{t('result.escalated')}</span>
                  ) : (
                    <span className="badge low">{t('result.confident')}</span>
                  )}
                </div>

                {result.model_available ? (
                  <>
                    <div className="headline">
                      {result.predicted_display || t('result.nothing')}
                    </div>
                    {result.confidence != null && (
                      <div className="muted">
                        {t('result.confidence')}: {Math.round(result.confidence * 100)}%
                        {result.model_version && (
                          <span className="mono small"> {result.model_version}</span>
                        )}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="alert danger">{t('farmer.noModel')}</div>
                )}

                {result.note && <p className="muted small">{result.note}</p>}

                {previewUrl && result.detections?.length > 0 && (
                  <DetectionPreview src={previewUrl} detections={result.detections} />
                )}
              </div>

              <AdvisoryCard advisory={result.advisory} triage={result.triage} />
              {result.risk && <RiskPanel assessment={result.risk} />}

              <p className="muted small">
                {t('farmer.saved').replace('{id}', result.case_id)}
              </p>
            </>
          )}
        </div>
      </div>
    </main>
  )
}
