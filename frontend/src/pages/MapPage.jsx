import { useEffect, useState } from 'react'
import { CircleMarker, MapContainer, Popup, Rectangle, TileLayer, useMap } from 'react-leaflet'
import { api } from '../lib/api.js'
import { prettify, useT } from '../lib/i18n.js'

const CENTER = [19.4, 74.2] // roughly the centre of Maharashtra's potato belt
const INTENSITY_COLOR = {
  low: '#3f8f5f',
  moderate: '#c9a227',
  high: '#d97706',
  severe: '#b3261e',
}

function FitToCells({ cells }) {
  const map = useMap()
  useEffect(() => {
    if (!cells.length) return
    const bounds = cells.map((c) => [c.latitude, c.longitude])
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 10 })
  }, [cells, map])
  return null
}

export default function MapPage() {
  const t = useT()
  const [data, setData] = useState(null)
  const [traps, setTraps] = useState([])
  const [error, setError] = useState(null)
  const [days, setDays] = useState(30)
  const [classKey, setClassKey] = useState('')
  const [showTraps, setShowTraps] = useState(true)

  useEffect(() => {
    const params = { days, cell_size_deg: 0.05 }
    if (classKey) params.class_key = classKey
    api.hotspots(params).then(setData).catch((e) => setError(e.message))
    api
      .sensorSummary()
      .then((s) => setTraps(s.cells || []))
      .catch(() => setTraps([]))
  }, [days, classKey])

  const cells = data?.cells || []

  return (
    <main className="page">
      <h1>{t('nav.map')}</h1>
      <p className="lede">
        Cases grouped on a 5 km grid. A confirmed case counts fully, an unreviewed one counts at{' '}
        {data ? data.unverified_weight : 0.4}, so a spike still shows without sending staff out on
        unchecked AI output.
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
            <label>Disease</label>
            <select value={classKey} onChange={(e) => setClassKey(e.target.value)}>
              <option value="">All</option>
              <option value="potato_late_blight">Late blight</option>
              <option value="potato_early_blight">Early blight</option>
            </select>
          </div>
          <label className="check">
            <input
              type="checkbox"
              checked={showTraps}
              onChange={(e) => setShowTraps(e.target.checked)}
            />
            <span>Show pest traps</span>
          </label>
        </div>

        <div className="legend" style={{ marginTop: 12 }}>
          {Object.entries(INTENSITY_COLOR).map(([label, color]) => (
            <span key={label}>
              <span className="dot" style={{ background: color }} />
              {prettify(label)}
            </span>
          ))}
          <span className="muted small">
            {data ? `${data.total_confirmed} confirmed · ${data.total_unverified} pending` : ''}
          </span>
        </div>
      </div>

      {error && <div className="alert danger">{error}</div>}

      <div className="map">
        <MapContainer center={CENTER} zoom={8} style={{ height: '100%', width: '100%' }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <FitToCells cells={cells} />

          {cells.map((cell) => {
            const half = cell.cell_size_deg / 2
            const bounds = [
              [cell.latitude - half, cell.longitude - half],
              [cell.latitude + half, cell.longitude + half],
            ]
            const color = INTENSITY_COLOR[cell.intensity] || INTENSITY_COLOR.low
            return (
              <Rectangle
                key={cell.geo_cell}
                bounds={bounds}
                pathOptions={{ color, weight: 1, fillOpacity: 0.35 }}
              >
                <Popup>
                  <strong>{cell.dominant_display}</strong>
                  <br />
                  {cell.districts.join(', ') || 'Unknown district'}
                  {cell.villages.length > 0 && (
                    <>
                      <br />
                      <span style={{ color: '#666' }}>{cell.villages.join(', ')}</span>
                    </>
                  )}
                  <br />
                  Confirmed: <strong>{cell.confirmed_cases}</strong>
                  <br />
                  Pending review: {cell.unverified_cases}
                  <br />
                  Weighted: {cell.weighted_count} ({cell.intensity})
                  {cell.latest_case_at && (
                    <>
                      <br />
                      <span style={{ color: '#666' }}>
                        Latest: {new Date(cell.latest_case_at).toLocaleDateString()}
                      </span>
                    </>
                  )}
                </Popup>
              </Rectangle>
            )
          })}

          {showTraps &&
            traps.map((trap) => (
              <CircleMarker
                key={trap.geo_cell}
                center={[trap.latitude, trap.longitude]}
                radius={6}
                pathOptions={{
                  // 20 moths/trap/week is the tuber moth action threshold
                  color: trap.mean_value >= 20 ? '#b3261e' : '#2f6f4e',
                  fillOpacity: 0.85,
                }}
              >
                <Popup>
                  <strong>Pest traps: {trap.district || 'unknown'}</strong>
                  <br />
                  {trap.devices} device(s), {trap.readings} readings
                  <br />
                  Mean catch: <strong>{trap.mean_value}</strong> (max {trap.max_value})
                  <br />
                  {trap.mean_value >= 20 ? 'Above the action threshold of 20 per trap per week.' : 'Below the action threshold.'}
                </Popup>
              </CircleMarker>
            ))}
        </MapContainer>
      </div>

      {cells.length === 0 && !error && (
        <p className="muted" style={{ marginTop: 12 }}>
          No cases with coordinates in this period. Run{' '}
          <span className="mono">python scripts/seed_demo_data.py</span> for demo data.
        </p>
      )}
    </main>
  )
}
