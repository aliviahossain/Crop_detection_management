import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../lib/api.js'
import { useT } from '../lib/i18n.js'

const CLASS_COLOR = {
  potato_late_blight: '#b3261e',
  potato_early_blight: '#d97706',
  potato_healthy: '#3f8f5f',
}

function Stat({ value, label, hint, tone }) {
  return (
    <div className="card stat">
      <div className="value" style={tone ? { color: `var(--${tone})` } : undefined}>
        {value}
      </div>
      <div className="label">{label}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

export default function DashboardPage() {
  const t = useT()
  const [days, setDays] = useState(30)
  const [district, setDistrict] = useState('')
  const [summary, setSummary] = useState(null)
  const [trend, setTrend] = useState(null)
  const [accuracy, setAccuracy] = useState(null)
  const [followUps, setFollowUps] = useState(null)
  const [districts, setDistricts] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    api.districts().then((d) => setDistricts(d.districts)).catch(() => {})
  }, [])

  useEffect(() => {
    const params = { days }
    if (district) params.district = district
    Promise.all([
      api.dashboard(params),
      api.trend(params),
      api.accuracy(),
      api.followUpStats(),
    ])
      .then(([s, tr, acc, fu]) => {
        setSummary(s)
        setTrend(tr)
        setAccuracy(acc)
        setFollowUps(fu)
      })
      .catch((e) => setError(e.message))
  }, [days, district])

  if (error) return <main className="page"><div className="alert danger">{error}</div></main>
  if (!summary) return <main className="page">{t('common.loading')}</main>

  const c = summary.cases
  return (
    <main className="page">
      <h1>{t('nav.dashboard')}</h1>
      <p className="lede">
        Where pressure is building, whether the model still holds up, and whether advice is
        resolving cases.
      </p>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="filters">
          <div>
            <label>{t('common.window')}</label>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={7}>{t('common.days7')}</option>
              <option value={30}>{t('common.days30')}</option>
              <option value={90}>{t('common.days90')}</option>
            </select>
          </div>
          <div>
            <label>{t('field.district')}</label>
            <select value={district} onChange={(e) => setDistrict(e.target.value)}>
              <option value="">{t('common.allDistricts')}</option>
              {districts.map((d) => (
                <option key={d.district} value={d.district}>
                  {d.district} ({d.cases})
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="grid cards" style={{ marginBottom: 16 }}>
        <Stat value={c.total} label="Cases logged" hint={`${c.from_image} from photos, ${c.proactive_risk_only} proactive`} />
        <Stat
          value={c.escalated}
          label="Sent to an expert"
          hint={c.escalation_rate != null ? `${Math.round(c.escalation_rate * 100)}% of all cases` : ''}
          tone="high"
        />
        <Stat value={c.pending_review} label="Awaiting review" hint="In the expert queue" tone="medium" />
        <Stat
          value={accuracy?.field_accuracy != null ? `${Math.round(accuracy.field_accuracy * 100)}%` : '-'}
          label="Accuracy in the field"
          hint={accuracy ? `${accuracy.reviewed} reviewed, ${accuracy.corrected} corrected` : ''}
        />
        <Stat
          value={followUps?.improvement_rate != null ? `${Math.round(followUps.improvement_rate * 100)}%` : '-'}
          label="Treatments that worked"
          hint={`${summary.follow_ups_overdue} follow-ups overdue`}
          tone="low"
        />
        <Stat value={summary.active_sensor_devices} label="Active traps" hint="Reporting in this period" />
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))' }}>
        <div className="card">
          <h2>Cases per day</h2>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={trend?.series || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e6e9e6" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="total" stroke="#2f6f4e" strokeWidth={2} dot={false} name="All cases" />
              <Line type="monotone" dataKey="confirmed" stroke="#3f8f5f" strokeWidth={2} dot={false} name="Expert-confirmed" />
              <Line type="monotone" dataKey="escalated" stroke="#b3261e" strokeWidth={2} dot={false} name="Escalated" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h2>Diagnoses</h2>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={summary.by_class}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e6e9e6" />
              <XAxis dataKey="display" tick={{ fontSize: 11 }} interval={0} />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" name="Cases">
                {summary.by_class.map((row) => (
                  <Cell key={row.class_key} fill={CLASS_COLOR[row.class_key] || '#2f6f4e'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="muted small">
            Reviewed cases count by the expert label, the rest by the model prediction.
          </p>
        </div>

        <div className="card">
          <h2>Risk levels issued</h2>
          <div className="stack">
            {Object.entries(summary.by_risk_level).map(([level, count]) => (
              <div key={level} className="spread">
                <span className={`badge ${level}`}>{level.toUpperCase()}</span>
                <strong>{count}</strong>
              </div>
            ))}
          </div>
          <h3>High-risk districts</h3>
          {summary.high_risk_districts.length === 0 && <p className="muted small">None in this window.</p>}
          <table>
            <tbody>
              {summary.high_risk_districts.slice(0, 8).map((row) => (
                <tr key={row.district}>
                  <td>{row.district}</td>
                  <td style={{ textAlign: 'right' }}>
                    <strong>{row.high_risk_cases}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2>Model accuracy by class</h2>
          {!accuracy?.per_class?.length && <p className="muted small">{t('common.none')}</p>}
          <table>
            <thead>
              <tr>
                <th>Predicted</th>
                <th>Reviewed</th>
                <th>Confirmed</th>
                <th>Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {(accuracy?.per_class || []).map((row) => (
                <tr key={row.predicted_class}>
                  <td>{row.display}</td>
                  <td>{row.reviewed}</td>
                  <td>{row.confirmed}</td>
                  <td>
                    <span className={`badge ${row.accuracy >= 0.8 ? 'low' : row.accuracy >= 0.6 ? 'medium' : 'high'}`}>
                      {row.accuracy != null ? `${Math.round(row.accuracy * 100)}%` : '-'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Measured against expert decisions in the field, not a test split. This is the number
            that tells you when a retrain is due.{' '}
            {accuracy?.retraining_samples_pending_export > 0 &&
              `${accuracy.retraining_samples_pending_export} validated samples are waiting for export.`}
          </p>
        </div>
      </div>
    </main>
  )
}
