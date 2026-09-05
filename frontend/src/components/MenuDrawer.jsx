import { useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import { LANGUAGES, useLang, useT } from '../lib/i18n.js'

// Grouped by who uses them. A farmer opening the menu should meet their own
// three tools first and not have to read past officer tooling to find them.
export const MENU_GROUPS = [
  {
    labelKey: 'menu.farmer',
    items: [
      { to: '/check', key: 'nav.check' },
      { to: '/scan', key: 'nav.scan' },
      { to: '/risk', key: 'nav.risk' },
    ],
  },
  {
    labelKey: 'menu.officer',
    items: [
      { to: '/map', key: 'nav.map' },
      { to: '/dashboard', key: 'nav.dashboard' },
      { to: '/review', key: 'nav.review' },
    ],
  },
]

export default function MenuDrawer({ open, onClose }) {
  const t = useT()
  const { lang, setLang } = useLang()

  // Escape closes, and the page behind must not scroll while the drawer is up.
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={t('menu.open')}>
        <div className="drawer-head">
          <strong>{t('app.title')}</strong>
          <button className="drawer-close" onClick={onClose} aria-label={t('menu.close')}>
            ✕
          </button>
        </div>

        <div className="drawer-body">
          {MENU_GROUPS.map((group) => (
            <div key={group.labelKey}>
              <div className="drawer-label">{t(group.labelKey)}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={onClose}
                  className={({ isActive }) => `menu-item${isActive ? ' active' : ''}`}
                >
                  <span className="txt">
                    <b>{t(item.key)}</b>
                    <small>{t(`${item.key}.desc`)}</small>
                  </span>
                </NavLink>
              ))}
            </div>
          ))}

          <div className="drawer-label">{t('menu.language')}</div>
          <div className="lang-grid">
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                className={lang === l.code ? 'active' : ''}
                onClick={() => setLang(l.code)}
                aria-pressed={lang === l.code}
              >
                <b>{l.label}</b>
                <small>{l.sub}</small>
              </button>
            ))}
          </div>
        </div>
      </aside>
    </>
  )
}
