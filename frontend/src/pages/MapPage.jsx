import { useEffect, useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Popup, Rectangle, TileLayer, useMap } from 'react-leaflet'
import HeatmapLayer from '../components/HeatmapLayer.jsx'
import { api } from '../lib/api.js'
import { prettify, useT } from '../lib/i18n.js'

const CENTER = [19.4, 74.2] // roughly the centre of Maharashtra's potato belt
const INTENSITY_COLOR = {
  low: '#3f8f5f',
  moderate: '#c9a227',
  high: '#d97706',
  severe: '#b3261e',
}
// Smooth green→amber→orange→red ramp for the heat surface, matching the grid legend.
const HEAT_GRADIENT = { 0.25: '#3f8f5f', 0.5: '#c9a227', 0.75: '#d97706', 1.0: '#b3261e' }
// A finer grid than the default 5 km, so the heatmap localises to village clusters.
const HEAT_CELL_DEG = 0.02

function FitToCells({ cells }) {
  const map = useMap()
  useEffect(() => {
    if (!cells.length) return
    const bounds = cells.map((c) => [c.latitude, c.longitude])
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 11 })
  }, [cells, map])
  return null
}

export default function MapPage() {
  const t = useT()
  const [data, setData] = useState(null)
  const [points, setPoints] = useState(null)
  const [traps, setTraps] = useState([])
  const [error, setError] = useState(null)
  const [days, setDays] = useState(30)
  const [classKey, setClassKey] = useState('')
  const [showTraps, setShowTraps] = useState(true)
  const [view, setView] = useState('heatmap') // 'heatmap' | 'grid'
  const [includeDemo, setIncludeDemo] = useState(true)

  useEffect(() => {
    const params = { days, cell_size_deg: HEAT_CELL_DEG, include_demo: includeDemo }
    if (classKey) params.class_key = classKey
    api.hotspots(params).then(setData).catch((e) => setError(e.message))
    api
      .hotspotPoints({ days, include_demo: includeDemo, ...(classKey ? { class_key: classKey } : {}) })
      .then(setPoints)
      .catch((e) => setError(e.message))
    api
      .sensorSummary({ include_demo: includeDemo })
      .then((s) => setTraps(s.cells || []))
      .catch(() => setTraps([]))
  }, [days, classKey, includeDemo])

  const cells = data?.cells || []

  // Leaflet-heat wants [lat, lng, weight]; top-of-scale is aligned to the
  // "severe" band so red on the heat surface means what red means on the grid.
  const heatPoints = useMemo(
    () => (points?.points || []).map((p) => [p.latitude, p.longitude, p.weight]),
    [points],
  )
  const heatOptions = useMemo(
    () => ({
      radius: 22,
      blur: 18,
      max: points?.severe_threshold || 8,
      minOpacity: 0.25,
      gradient: HEAT_GRADIENT,
    }),
    [points],
  )

  const totalConfirmed = data ? data.total_confirmed : 0
  const totalPending = data ? data.total_unverified : 0

  return (
    <main className="page">
      <h1>{t('nav.map')}</h1>
      <p className="lede">
        Cases as a live density surface. A confirmed case counts fully, an unreviewed one counts at{' '}
        {data ? data.unverified_weight : 0.4}, so a spike still shows without sending staff out on
        unchecked AI output.
      </p>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="filters">
          <div>
            <label>View</label>
            <div className="segmented">
              <button
                type="button"
                className={view === 'heatmap' ? 'active' : ''}
                onClick={() => setView('heatmap')}
              >
                Heatmap
              </button>
              <button
                type="button"
                className={view === 'grid' ? 'active' : ''}
                onClick={() => setView('grid')}
              >
                Grid
              </button>
            </div>
          </div>
          <div>
            <label>Data source</label>
            <div className="segmented">
              <button
                type="button"
                className={includeDemo ? 'active' : ''}
                onClick={() => setIncludeDemo(true)}
              >
                Demo + live
              </button>
              <button
                type="button"
                className={!includeDemo ? 'active' : ''}
                onClick={() => setIncludeDemo(false)}
              >
                Live only
              </button>
            </div>
          </div>
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
            {data ? `${totalConfirmed} confirmed · ${totalPending} pending` : ''}
            {!includeDemo && data && totalConfirmed + totalPending === 0
              ? ' (no live cases yet; switch to Demo + live to preview the map)'
              : ''}
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

          {view === 'heatmap' && heatPoints.length > 0 && (
            <HeatmapLayer points={heatPoints} options={heatOptions} />
          )}

          {view === 'grid' &&
            cells.map((cell) => {
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
          No cases with coordinates in this period.{' '}
          {includeDemo ? (
            <>
              Run <span className="mono">python scripts/seed_demo_data.py</span> for demo data.
            </>
          ) : (
            'No live field reports yet. Switch Data source to Demo + live to preview.'
          )}
        </p>
      )}
    </main>
  )
}
