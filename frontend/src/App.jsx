import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { LANGUAGES, LangContext, useLang, useT } from './lib/i18n.js'
import { api } from './lib/api.js'
import MenuDrawer from './components/MenuDrawer.jsx'
import FarmerPage from './pages/FarmerPage.jsx'
import ScanPage from './pages/ScanPage.jsx'
import RiskPage from './pages/RiskPage.jsx'
import MapPage from './pages/MapPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import ReviewPage from './pages/ReviewPage.jsx'

function TopBar({ onMenu }) {
  const t = useT()
  const { lang } = useLang()
  const current = LANGUAGES.find((l) => l.code === lang)
  return (
    <header className="topbar">
      <button className="menu-btn" onClick={onMenu} aria-label={t('menu.open')}>
        <span className="bars" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        {t('menu.open')}
      </button>
      <div className="brand">
        <strong>{t('app.title')}</strong>
        <span>{t('app.subtitle')}</span>
      </div>
      <button className="lang-pill" onClick={onMenu} aria-label={t('menu.language')}>
        {current?.label || lang}
      </button>
    </header>
  )
}

/** Separates what is genuinely broken from what is off by design.
 *
 *  Conflating the two misleads both ways: it implies a fault when the system is
 *  behaving as specified, and it buries real problems in a list of non-problems.
 *  Only `degraded` gets a banner; `by_design` hides behind a disclosure. */
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
              ? 'One feature is not working.'
              : `${degraded.length} features are not working.`}
          </strong>
          <ul>
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
        <details className="small muted">
          <summary>
            {byDesign.length} optional part{byDesign.length === 1 ? '' : 's'} switched off by design
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
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => {
    localStorage.setItem('cropguard.lang', lang)
  }, [lang])
  const value = useMemo(() => ({ lang, setLang }), [lang])
  const closeMenu = useCallback(() => setMenuOpen(false), [])

  return (
    <LangContext.Provider value={value}>
      <div className="app">
        <TopBar onMenu={() => setMenuOpen(true)} />
        <MenuDrawer open={menuOpen} onClose={closeMenu} />
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
