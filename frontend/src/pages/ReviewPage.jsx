import { useEffect, useState } from 'react'
import { api, mediaUrl } from '../lib/api.js'
import { prettify, useT } from '../lib/i18n.js'

const CLASSES = [
  { key: 'potato_early_blight', label: 'Early blight' },
  { key: 'potato_late_blight', label: 'Late blight' },
  { key: 'potato_healthy', label: 'Healthy' },
]

export default function ReviewPage() {
  const t = useT()
  const [queue, setQueue] = useState([])
  const [selected, setSelected] = useState(null)
  const [reviewer, setReviewer] = useState(() => localStorage.getItem('cropguard.reviewer') || '')
  const [notes, setNotes] = useState('')
  const [correctedClass, setCorrectedClass] = useState('')
  const [onlyEscalated, setOnlyEscalated] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)

  const load = () => {
    const params = { limit: 60 }
    if (onlyEscalated) params.only_escalated = true
    api
      .reviewQueue(params)
      .then((rows) => {
        setQueue(rows)
        setSelected((current) => rows.find((r) => r.id === current?.id) || rows[0] || null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(load, [onlyEscalated])

  useEffect(() => {
    setCorrectedClass(selected?.predicted_class || '')
    setNotes('')
  }, [selected?.id])

  const decide = async (status) => {
    if (!selected) return
    if (!reviewer.trim()) {
      setError('Enter your name or post. A decision has to be attributable.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      localStorage.setItem('cropguard.reviewer', reviewer)
      await api.decide(selected.id, {
        status,
        confirmed_class: status === 'corrected' ? correctedClass : null,
        reviewer,
        notes: notes || null,
      })
      setMessage(`Case #${selected.id} marked ${status}.`)
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const image = mediaUrl(selected?.image_path)

  return (
    <main className="page">
      <h1>{t('nav.review')}</h1>
      <p className="lede">
        Your decision becomes the official label on the map and dashboard, and a training sample
        for the next model.
      </p>

      {message && <div className="alert info">{message}</div>}
      {error && <div className="alert danger">{error}</div>}

      <div className="grid two">
        <div className="card">
          <div className="spread" style={{ marginBottom: 10 }}>
            <h2 style={{ margin: 0 }}>Queue ({queue.length})</h2>
            <label className="check small">
              <input
                type="checkbox"
                checked={onlyEscalated}
                onChange={(e) => setOnlyEscalated(e.target.checked)}
              />
              <span>Escalated only</span>
            </label>
          </div>

          {queue.length === 0 && <p className="muted">Queue is empty.</p>}

          <div className="queue">
            {queue.map((row) => (
              <button
                key={row.id}
                className={`queue-item${selected?.id === row.id ? ' active' : ''}`}
                onClick={() => setSelected(row)}
              >
                <div className="spread">
                  <strong>#{row.id}</strong>
                  {row.escalate && <span className="badge high">escalated</span>}
                </div>
                <div className="small">
                  {row.predicted_class ? prettify(row.predicted_class.replace('potato_', '')) : 'No detection'}
                  {row.confidence != null && ` · ${Math.round(row.confidence * 100)}%`}
                </div>
                <div className="muted small">
                  {[row.village, row.district].filter(Boolean).join(', ') || 'No location'} ·{' '}
                  {new Date(row.created_at).toLocaleDateString()}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="stack">
          {!selected && <div className="card muted">Select a case from the queue.</div>}

          {selected && (
            <>
              <div className="card stack">
                <div className="spread">
                  <h2 style={{ margin: 0 }}>Case #{selected.id}</h2>
                  <span className={`badge ${selected.risk_level || 'neutral'}`}>
                    risk: {selected.risk_level || 'n/a'}
                  </span>
                </div>

                {image ? (
                  <img src={image} alt={`case ${selected.id}`} style={{ maxWidth: '100%', borderRadius: 10 }} />
                ) : (
                  <p className="muted small">
                    No image on this case{selected.source === 'risk_forecast' ? '. It was a weather alert, not a photo.' : '.'}
                  </p>
                )}

                <table>
                  <tbody>
                    <tr>
                      <th>Model says</th>
                      <td>
                        {selected.predicted_class ? prettify(selected.predicted_class) : '-'}
                        {selected.confidence != null && ` (${Math.round(selected.confidence * 100)}%)`}
                      </td>
                    </tr>
                    <tr>
                      <th>Crop</th>
                      <td>
                        {selected.crop}
                        {selected.variety && ` · ${selected.variety}`}
                        {selected.crop_stage && ` · ${prettify(selected.crop_stage)}`}
                      </td>
                    </tr>
                    <tr>
                      <th>Location</th>
                      <td>
                        {[selected.village, selected.district].filter(Boolean).join(', ') || '-'}
                        {selected.latitude != null && (
                          <span className="mono small">
                            {' '}
                            ({selected.latitude}, {selected.longitude})
                          </span>
                        )}
                      </td>
                    </tr>
                    <tr>
                      <th>Reported</th>
                      <td>{new Date(selected.created_at).toLocaleString()}</td>
                    </tr>
                  </tbody>
                </table>

                {selected.escalation_reasons?.length > 0 && (
                  <div className="alert">
                    <strong>Why this was flagged</strong>
                    <ul>
                      {selected.escalation_reasons.map((r, i) => (
                        <li key={i} className="small">
                          <strong>{prettify(r.code)}:</strong> {r.message}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              <div className="card stack">
                <h2>Your decision</h2>
                <div className="field">
                  <label>Your name or post</label>
                  <input
                    value={reviewer}
                    onChange={(e) => setReviewer(e.target.value)}
                    placeholder="TAO Ambegaon"
                  />
                </div>
                <div className="field">
                  <label>Correct diagnosis</label>
                  <select value={correctedClass} onChange={(e) => setCorrectedClass(e.target.value)}>
                    <option value="">-</option>
                    {CLASSES.map((c) => (
                      <option key={c.key} value={c.key}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label>Notes</label>
                  <textarea
                    rows={3}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="White downy growth confirmed on leaf underside during field visit."
                  />
                </div>

                <div className="inline">
                  <button className="primary auto" disabled={busy} onClick={() => decide('confirmed')}>
                    ✓ Confirm
                  </button>
                  <button className="ghost" disabled={busy || !correctedClass} onClick={() => decide('corrected')}>
                    ✎ Correct
                  </button>
                  <button className="ghost" disabled={busy} onClick={() => decide('rejected')}>
                    ✕ Reject
                  </button>
                </div>

                <p className="muted small">
                  Reject when the real diagnosis is outside the three classes this model covers.
                  Note what it actually was, so the next dataset can include it.
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  )
}
