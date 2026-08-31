import { useState } from 'react'
import { api } from '../lib/api.js'
import { useLang, useT } from '../lib/i18n.js'
import RiskPanel from '../components/RiskPanel.jsx'
import AdvisoryCard from '../components/AdvisoryCard.jsx'
import FieldContextForm, { emptyContext } from '../components/FieldContextForm.jsx'

// Manchar, Pune district -- a real potato-growing pocket, so the demo opens on
// something meaningful instead of a blank form.
const DEFAULT = { ...emptyContext, latitude: '19.00090', longitude: '73.94030', district: 'Pune', village: 'Manchar' }

export default function RiskPage() {
  const t = useT()
  const { lang } = useLang()
  const [ctx, setCtx] = useState(DEFAULT)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [saveCase, setSaveCase] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    if (!ctx.latitude || !ctx.longitude) {
      setError('Latitude and longitude are required — the risk models run on your local weather.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      setResult(
        await api.risk({
          latitude: Number(ctx.latitude),
          longitude: Number(ctx.longitude),
          crop: 'potato',
          variety: ctx.variety || null,
          crop_stage: ctx.crop_stage || null,
          soil_condition: ctx.soil_condition || null,
          district: ctx.district || null,
          village: ctx.village || null,
          language: lang,
          save_case: saveCase,
          include_advisory: true,
        }),
      )
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <h1>{t('risk.heading')}</h1>
      <p className="lede">{t('risk.explain')}</p>

      <div className="grid two">
        <form className="card" onSubmit={submit}>
          <FieldContextForm value={ctx} onChange={setCtx} />

          <div className="field">
            <label className="inline" style={{ cursor: 'pointer' }}>
              <input
                type="checkbox"
                style={{ width: 'auto' }}
                checked={saveCase}
                onChange={(e) => setSaveCase(e.target.checked)}
              />
              <span>Record this as a case for the officer dashboard</span>
            </label>
          </div>

          <button className="primary" type="submit" disabled={busy}>
            {busy ? t('common.loading') : t('risk.check')}
          </button>

          {error && <div className="alert danger">{error}</div>}

          <div className="alert info" style={{ marginTop: 14 }}>
            <strong>How this works.</strong> Risk comes from published agronomic models — the Smith
            and Beaumont Periods for late blight, TOMCAST severity values for early blight, and
            degree-day accumulation for pest emergence — adjusted for your crop stage, variety,
            soil and confirmed cases nearby. No image is needed, which is the point: it warns you
            before symptoms appear.
          </div>
        </form>

        <div className="stack">
          {!result && <div className="card muted">{t('common.none')}</div>}
          {result && (
            <>
              <RiskPanel assessment={result.assessment} />
              {result.advisory && (
                <AdvisoryCard advisory={result.advisory} triage={result.triage} />
              )}
              {result.case_id && (
                <p className="muted small">Recorded as case #{result.case_id}.</p>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  )
}
