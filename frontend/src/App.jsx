import { useEffect, useMemo, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { LangContext, LANGUAGES, useLang, useT } from './lib/i18n.js'
import { api } from './lib/api.js'
import FarmerPage from './pages/FarmerPage.jsx'
import ScanPage from './pages/ScanPage.jsx'
import RiskPage from './pages/RiskPage.jsx'
import MapPage from './pages/MapPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import ReviewPage from './pages/ReviewPage.jsx'

function Nav() {
  const t = useT()
  const { lang, setLang } = useLang()
  const links = [
    ['/scan', 'nav.scan'],
    ['/check', 'nav.check'],
    ['/risk', 'nav.risk'],
    ['/map', 'nav.map'],
    ['/dashboard', 'nav.dashboard'],
    ['/review', 'nav.review'],
  ]
  return (
    <header className="topbar">
      <div className="brand">
        <strong>{t('app.title')}</strong>
        <span>{t('app.subtitle')}</span>
      </div>
      <nav className="nav">
        {links.map(([to, key]) => (
          <NavLink key={to} to={to} className={({ isActive }) => (isActive ? 'active' : '')}>
            {t(key)}
          </NavLink>
        ))}
      </nav>
      <div className="lang-switch">
        {LANGUAGES.map((l) => (
          <button
            key={l.code}
            className={lang === l.code ? 'active' : ''}
            onClick={() => setLang(l.code)}
            aria-pressed={lang === l.code}
          >
            {l.label}
          </button>
        ))}
      </div>
    </header>
  )
}

/** Shows what is genuinely broken, and separately what is inactive by design.
 *
 *  Conflating the two misleads in both directions: it implies the system is
 *  faulty when it is behaving as specified, and it buries the things that
 *  actually need fixing in a list of non-problems. Only `degraded` gets the
 *  warning banner; `by_design` is collapsed behind a disclosure. */
function HealthBanner() {
  const [health, setHealth] = useState(null)
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])
  if (!health) return null

  const degraded = health.degraded_detail || []
  const byDesign = health.by_design_detail || []
  if (!degraded.length && !byDesign.length) return null

  return (
    <div className="page" style={{ paddingBottom: 0 }}>
      {degraded.length > 0 && (
        <div className="alert">
          <strong>
            {degraded.length === 1
              ? 'One capability is degraded.'
              : `${degraded.length} capabilities are degraded.`}
          </strong>
          <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
            {degraded.map((d) => (
              <li key={d.code} className="small">
                {d.summary}
                {d.remedy && <span className="muted"> {d.remedy}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {byDesign.length > 0 && (
        <details className="small muted" style={{ margin: '4px 0 0' }}>
          <summary>
            {byDesign.length} optional component{byDesign.length === 1 ? '' : 's'} inactive by
            design — the system is working as specified
          </summary>
          <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
            {byDesign.map((d) => (
              <li key={d.code}>
                {d.summary}
                {d.remedy && <span style={{ opacity: 0.8 }}> {d.remedy}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

export default function App() {
  const [lang, setLang] = useState(() => localStorage.getItem('cropguard.lang') || 'mr')
  useEffect(() => {
    localStorage.setItem('cropguard.lang', lang)
  }, [lang])
  const value = useMemo(() => ({ lang, setLang }), [lang])

  return (
    <LangContext.Provider value={value}>
      <div className="app">
        <Nav />
        <HealthBanner />
        <Routes>
          <Route path="/" element={<Navigate to="/check" replace />} />
          <Route path="/scan" element={<ScanPage />} />
          <Route path="/check" element={<FarmerPage />} />
          <Route path="/risk" element={<RiskPage />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="*" element={<Navigate to="/check" replace />} />
        </Routes>
      </div>
    </LangContext.Provider>
  )
}
