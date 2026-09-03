import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { useLang, useT } from '../lib/i18n.js'
import RiskPanel from '../components/RiskPanel.jsx'
import AdvisoryCard from '../components/AdvisoryCard.jsx'
import FieldContextForm, { emptyContext } from '../components/FieldContextForm.jsx'

// Manchar, Pune district: a real potato pocket, so the page opens on something
// meaningful instead of a blank form.
const DEFAULT = {
  ...emptyContext,
  latitude: '19.00090',
  longitude: '73.94030',
  district: 'Pune',
  village: 'Manchar',
}

export default function RiskPage() {
  const t = useT()
  const { lang } = useLang()
  const [ctx, setCtx] = useState(DEFAULT)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [saveCase, setSaveCase] = useState(false)

  const assess = async (context, { save = false } = {}) => {
    if (!context.latitude || !context.longitude) {
      setError(t('risk.needCoords'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      setResult(
        await api.risk({
          latitude: Number(context.latitude),
          longitude: Number(context.longitude),
          crop: 'potato',
          variety: context.variety || null,
          crop_stage: context.crop_stage || null,
          soil_condition: context.soil_condition || null,
          district: context.district || null,
          village: context.village || null,
          language: lang,
          save_case: save,
          include_advisory: true,
        }),
      )
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // Land on a populated forecast, so the first screen shows the prediction
  // engine working rather than an empty form.
  useEffect(() => {
    assess(DEFAULT)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submit = (event) => {
    event.preventDefault()
    assess(ctx, { save: saveCase })
  }

  return (
    <main className="page">
      <h1>{t('risk.heading')}</h1>
      <p className="lede">{t('risk.explain')}</p>

      <div className="grid two">
        <form className="card stack" onSubmit={submit}>
          <FieldContextForm value={ctx} onChange={setCtx} />

          <label className="check">
            <input
              type="checkbox"
              checked={saveCase}
              onChange={(e) => setSaveCase(e.target.checked)}
            />
            <span>{t('risk.saveCase')}</span>
          </label>

          <button className="primary" type="submit" disabled={busy}>
            {busy ? t('common.loading') : t('risk.check')}
          </button>

          {error && <div className="alert danger">{error}</div>}

          <details>
            <summary>{t('risk.how')}</summary>
            <p className="small muted" style={{ marginTop: 6 }}>
              {t('risk.howText')}
            </p>
          </details>
        </form>

        <div className="stack">
          {!result && (
            <div className="card muted">{busy ? t('common.loading') : t('common.none')}</div>
          )}
          {result && (
            <>
              <RiskPanel assessment={result.assessment} />
              {result.advisory && (
                <AdvisoryCard advisory={result.advisory} triage={result.triage} />
              )}
              {result.case_id && (
                <p className="muted small">Case #{result.case_id}</p>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  )
}
