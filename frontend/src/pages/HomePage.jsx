import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { useLang, useT } from '../lib/i18n.js'

// The seeded demo potato pockets (mirrors scripts/seed_demo_data.py). A judge on
// any laptop can pick one and see synthetic data, since "near me" is otherwise
// tied to the viewer's real GPS, where no demo cases exist.
const DEMO_PLACES = [
  { label: 'Manchar, Pune', latitude: 19.0009, longitude: 73.9403, district: 'Pune' },
  { label: 'Ambegaon, Pune', latitude: 19.118, longitude: 73.735, district: 'Pune' },
  { label: 'Junnar, Pune', latitude: 19.205, longitude: 73.875, district: 'Pune' },
  { label: 'Dindori, Nashik', latitude: 20.203, longitude: 73.83, district: 'Nashik' },
  { label: 'Niphad, Nashik', latitude: 20.08, longitude: 74.11, district: 'Nashik' },
  { label: 'Wai, Satara', latitude: 17.95, longitude: 73.89, district: 'Satara' },
  { label: 'Khandala, Satara', latitude: 18.04, longitude: 73.96, district: 'Satara' },
  { label: 'Sangamner, Ahmednagar', latitude: 19.57, longitude: 74.21, district: 'Ahmednagar' },
  { label: 'Ashti, Beed', latitude: 18.81, longitude: 74.97, district: 'Beed' },
  { label: 'Katol, Nagpur', latitude: 21.27, longitude: 78.59, district: 'Nagpur' },
]
// Manchar, Pune -- a real potato pocket. The page opens on a meaningful place
// so the proactive engine is visibly working before the farmer sets a location.
const DEFAULT_LOC = { ...DEMO_PLACES[0] }
const STORAGE_KEY = 'cropguard.home.loc'

const STATUS_SEVERITY = { calm: 'low', watch: 'medium', act: 'high' }

function loadSavedLoc() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : DEFAULT_LOC
  } catch {
    return DEFAULT_LOC
  }
}

/** Fill {token} placeholders in a translated string. */
const fmt = (s, vars) =>
  Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, v), s)

export default function HomePage() {
  const t = useT()
  const { lang } = useLang()
  const navigate = useNavigate()
  const [loc, setLoc] = useState(loadSavedLoc)
  const [includeDemo, setIncludeDemo] = useState(true)
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [locating, setLocating] = useState(false)

  const load = useCallback(async (where, demo) => {
    setBusy(true)
    setError(null)
    try {
      const params = {
        latitude: where.latitude,
        longitude: where.longitude,
        include_demo: demo,
      }
      if (where.district) params.district = where.district
      setData(await api.homeOverview(params))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    load(loc, includeDemo)
  }, [load, loc, includeDemo])

  // Pin the alert to the farmer's own field, and remember it for next time.
  const locate = () => {
    if (!navigator.geolocation) return
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false)
        const next = {
          latitude: Number(pos.coords.latitude.toFixed(5)),
          longitude: Number(pos.coords.longitude.toFixed(5)),
        }
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
        } catch {
          /* private mode: the alert still works, it just isn't remembered */
        }
        setLoc(next)
      },
      () => setLocating(false),
      { enableHighAccuracy: true, timeout: 8000 },
    )
  }

  // Jump to a seeded demo pocket, and remember it.
  const pickPlace = (label) => {
    const place = DEMO_PLACES.find((p) => p.label === label)
    if (!place) return
    const next = { latitude: place.latitude, longitude: place.longitude, district: place.district }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      /* private mode: still works, just not remembered */
    }
    setLoc(next)
  }

  const status = data?.status || 'calm'
  const severity = STATUS_SEVERITY[status]
  const nearby = data?.nearby
  const weather = data?.weather
  const prevalent = data?.prevalent

  // Localised short disease name, falling back to the server's English display.
  const diseaseName = (key, display) =>
    key ? t(`disease.${key}`) || display || key : display

  // Which seeded pocket (if any) the current coordinates match, so the picker
  // reflects the active place and shows "My location" when it's the farmer's GPS.
  const selectedPlace =
    DEMO_PLACES.find(
      (p) =>
        Math.abs(p.latitude - loc.latitude) < 1e-3 &&
        Math.abs(p.longitude - loc.longitude) < 1e-3,
    )?.label || ''

  // The subline names the real driver: a neighbour's outbreak vs. your weather.
  const reasonKey =
    status === 'calm'
      ? 'home.reason.calm'
      : `home.reason.${data?.primary_reason === 'nearby_outbreak' ? 'nearby' : 'weather'}.${status}`

  return (
    <main className="page">
      <h1>{t('home.heading')}</h1>
      <p className="lede">{t('home.help')}</p>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="filters">
          <div>
            <label>{t('field.location')}</label>
            <select value={selectedPlace} onChange={(e) => pickPlace(e.target.value)}>
              {!selectedPlace && <option value="">{t('home.myLocation')}</option>}
              {DEMO_PLACES.map((p) => (
                <option key={p.label} value={p.label}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label>{t('home.source')}</label>
            <div className="segmented">
              <button
                type="button"
                className={includeDemo ? 'active' : ''}
                onClick={() => setIncludeDemo(true)}
              >
                {t('home.source.demo')}
              </button>
              <button
                type="button"
                className={!includeDemo ? 'active' : ''}
                onClick={() => setIncludeDemo(false)}
              >
                {t('home.source.live')}
              </button>
            </div>
          </div>
        </div>
        <p className="muted small" style={{ marginTop: 10, marginBottom: 0 }}>
          {t(includeDemo ? 'home.source.demoNote' : 'home.source.liveNote')}
        </p>
      </div>

      {busy && !data && <div className="card muted">{t('common.loading')}</div>}
      {error && <div className="alert danger">{error}</div>}

      {data && (
        <div className="stack">
          {/* The traffic light: one colour, one instruction. */}
          <section className={`home-hero ${severity}`}>
            <div className="home-dot" aria-hidden="true" />
            <div className="stack" style={{ gap: 6 }}>
              <h2 style={{ margin: 0 }}>{t(`home.status.${status}.title`)}</h2>
              <p style={{ margin: 0 }}>{t(reasonKey)}</p>
              {data.time_hint === 'this_morning' && (
                <p className="home-hint">{t('home.timeHint.morning')}</p>
              )}
              {status !== 'calm' && (
                <button
                  className="primary auto"
                  style={{ marginTop: 8 }}
                  onClick={() => navigate('/check')}
                >
                  {t(status === 'act' ? 'home.action.photo' : 'home.action.watch')}
                </button>
              )}
            </div>
          </section>

          {/* Which disease dominates the area -- confirmed weighed above reported. */}
          <section className="card home-card">
            <h3 style={{ marginTop: 0 }}>{t('home.prevalent.title')}</h3>
            {prevalent?.dominant_class ? (
              <p className="home-stat" style={{ margin: 0 }}>
                {fmt(t('home.prevalent.line'), {
                  disease: diseaseName(prevalent.dominant_class, prevalent.dominant_display),
                  n:
                    (prevalent.by_class[prevalent.dominant_class]?.confirmed || 0) +
                    (prevalent.by_class[prevalent.dominant_class]?.reported || 0),
                  km: prevalent.radius_km,
                })}
              </p>
            ) : (
              <p className="muted small" style={{ margin: 0 }}>{t('home.prevalent.none')}</p>
            )}
          </section>

          <div className="grid two">
            {/* Cross-farm outbreak pressure -- aggregated, never named. */}
            <section className={`card home-card ${nearby?.level && nearby.level !== 'none' ? 'accent' : ''}`}>
              <h3 style={{ marginTop: 0 }}>{t('home.nearby.title')}</h3>
              {nearby?.confirmed_count > 0 ? (
                <>
                  <p className="home-stat">
                    {fmt(t('home.nearby.confirmed'), {
                      n: nearby.confirmed_count,
                      km: nearby.radius_km,
                    })}
                  </p>
                  {nearby.nearest_km != null && (
                    <p className="muted small" style={{ margin: 0 }}>
                      {fmt(t('home.nearby.nearest'), { km: nearby.nearest_km })}
                    </p>
                  )}
                </>
              ) : nearby?.reported_count > 0 ? (
                <p className="small">
                  {fmt(t('home.nearby.reported'), { n: nearby.reported_count })}
                </p>
              ) : (
                <p className="muted small" style={{ margin: 0 }}>{t('home.nearby.none')}</p>
              )}
            </section>

            {/* Weather at a glance -- the input the blight models read. */}
            <section className="card home-card">
              <h3 style={{ marginTop: 0 }}>{t('home.weather.title')}</h3>
              {weather?.temp_mean_c != null ? (
                <p className="home-stat">
                  {fmt(t('home.weather.line'), {
                    temp: Math.round(weather.temp_mean_c),
                    hum: Math.round(weather.humidity_mean),
                  })}
                </p>
              ) : (
                <p className="muted small" style={{ margin: 0 }}>{t('common.none')}</p>
              )}
              {data.data_thin && (
                <p className="muted small" style={{ marginBottom: 0 }}>{t('home.dataThin')}</p>
              )}
            </section>
          </div>
          <h3 style={{ marginTop: 0 }}>Quick Actions</h3>

<div className="inline">
  <button
    className="primary auto"
    onClick={() => navigate('/scan')}
  >
    Scan Crop
  </button>

  <button
    className="ghost"
    onClick={() => navigate('/risk')}
  >
    Check Risk
  </button>

  <button
    className="ghost"
    onClick={() => navigate('/map')}
  >
    View Map
  </button>

  <button
    className="ghost"
    onClick={() => navigate('/dashboard')}
  >
    Open Dashboard
  </button>
</div>
          <p className="muted small">{t('home.disclaimer')}</p>

          <div className="inline">
            <button className="ghost small" onClick={locate} disabled={locating}>
              {locating ? t('field.locating') : t('home.locate')}
            </button>
          </div>
        </div>
      )}
    </main>
  )
}
