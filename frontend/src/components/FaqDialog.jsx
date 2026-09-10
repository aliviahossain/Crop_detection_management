import { useEffect } from 'react'
import { useT } from '../lib/i18n.js'

// The five basics a first-time user asks about, kept in one place so both the
// question and its answer stay in the same translation namespace (faq.qN/aN).
const FAQ_KEYS = ['1', '2', '3', '4', '5']

export default function FaqDialog({ open, onClose }) {
  const t = useT()

  // Escape closes, and the page behind must not scroll while the dialog is up
  // -- mirrors MenuDrawer so the two overlays behave the same way.
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
      <aside className="faq-dialog" role="dialog" aria-modal="true" aria-label={t('faq.title')}>
        <div className="drawer-head">
          <strong>{t('faq.title')}</strong>
          <button className="drawer-close" onClick={onClose} aria-label={t('menu.close')}>
            ✕
          </button>
        </div>
        <div className="drawer-body">
          <p className="muted small" style={{ margin: '4px 6px 12px' }}>
            {t('faq.intro')}
          </p>
          {FAQ_KEYS.map((n) => (
            <details key={n} className="faq-item">
              <summary>{t(`faq.q${n}`)}</summary>
              <p>{t(`faq.a${n}`)}</p>
            </details>
          ))}
        </div>
      </aside>
    </>
  )
}
