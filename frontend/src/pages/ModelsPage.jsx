import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { resetDetectionCache } from '../lib/detectPhoto.js'
import { useT } from '../lib/i18n.js'

// A crop is a downloadable pack, not an app release: weights, the thresholds
// tuned for those weights, the class list and the knowledge-base pages the
// advisory is built from, versioned and installed together.
//
// These endpoints exist only on the on-device server inside the Android app.
// The web deployment has no such routes, so a 404 here means "not supported on
// this platform", which is a different thing from a failure and is said
// differently.

const mb = (bytes) => (bytes / (1024 * 1024)).toFixed(1)

// A detector pack localises plants and advises nothing; a crop pack drives the
// farmer's diagnosis and treatment path. Showing them in one undifferentiated
// list would invite installing a lab scanner and expecting a diagnosis.
const isDetector = (x) => x.kind === 'detector'
const nameOf = (x) => x.title || x.crop.charAt(0).toUpperCase() + x.crop.slice(1)

function Bar({ value }) {
  return (
    <div className="pack-bar" role="progressbar" aria-valuenow={Math.round(value * 100)}>
      <div className="pack-bar-fill" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  )
}

export default function ModelsPage() {
  const t = useT()
  const [installed, setInstalled] = useState(null)
  const [catalog, setCatalog] = useState(null)
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState(null)
  const [catalogError, setCatalogError] = useState(null)
  const [unsupported, setUnsupported] = useState(false)
  const [source, setSource] = useState(null)
  const [sourceDraft, setSourceDraft] = useState('')
  const [editingSource, setEditingSource] = useState(false)
  const [loading, setLoading] = useState(true)
  const poll = useRef(null)

  const loadInstalled = useCallback(
    () =>
      api
        .packsInstalled()
        .then((d) => {
          setInstalled(d)
          setUnsupported(false)
        })
        .catch((e) => {
          // The web build has no /api/packs routes at all.
          if (/404|not found/i.test(e.message)) setUnsupported(true)
          else setError(e.message)
        }),
    [],
  )

  const loadSource = useCallback(
    () =>
      api
        .packsSource()
        .then((d) => {
          setSource(d)
          setSourceDraft(d.url || '')
        })
        .catch(() => {}),
    [],
  )

  const saveSource = async () => {
    try {
      await api.setPacksSource({ url: sourceDraft })
      setEditingSource(false)
      await loadSource()
      await loadCatalog()
    } catch (e) {
      setError(e.message)
    }
  }

  const loadCatalog = useCallback(
    () =>
      api
        .packsCatalog()
        .then((d) => {
          setCatalog(d.crops || [])
          setCatalogError(null)
        })
        // The catalogue is the one thing here that needs a connection, so
        // failing to reach it is expected offline rather than broken.
        .catch((e) => setCatalogError(e.message)),
    [],
  )

  useEffect(() => {
    let alive = true
    loadInstalled()
      .then(() => (alive ? loadSource() : null))
      .then(() => (alive ? loadCatalog() : null))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [loadInstalled, loadSource, loadCatalog])

  // Poll only while an install is running. A 45 MB download takes a minute or
  // more on a rural connection and the server runs it in the background, so
  // this is the only way the page knows how far it has got.
  const startPolling = useCallback(() => {
    if (poll.current) return
    poll.current = setInterval(async () => {
      try {
        const p = await api.packsProgress()
        setProgress(p)
        if (!p.active) {
          clearInterval(poll.current)
          poll.current = null
          if (p.error) setError(p.error)
          // The scan pages cache /detect/status; without this they keep
          // believing there is no model until the app is restarted.
          resetDetectionCache()
          await loadInstalled()
        }
      } catch {
        clearInterval(poll.current)
        poll.current = null
      }
    }, 600)
  }, [loadInstalled])

  useEffect(() => () => poll.current && clearInterval(poll.current), [])

  // An install started from the Flutter first-launch screen, or left running
  // when the page was closed, should still show up here.
  useEffect(() => {
    if (unsupported) return
    api
      .packsProgress()
      .then((p) => {
        if (p.active) {
          setProgress(p)
          startPolling()
        }
      })
      .catch(() => {})
  }, [unsupported, startPolling])

  // Refresh means both halves. Reloading only the catalogue left the "on this
  // phone" card showing whatever was installed when the page mounted, so a
  // pack installed since - or from the first-launch screen - was reported as
  // still being in use after it had been replaced.
  const refresh = useCallback(async () => {
    setError(null)
    await loadInstalled()
    await loadCatalog()
  }, [loadInstalled, loadCatalog])

  const install = async (crop, version) => {
    setError(null)
    setProgress({ active: true, phase: 'catalog', received_bytes: 0, total_bytes: 0, crop })
    try {
      await api.installPack({ crop, version })
      startPolling()
    } catch (e) {
      setError(e.message)
      setProgress(null)
    }
  }

  if (loading) return <main className="page">{t('common.loading')}</main>

  if (unsupported) {
    return (
      <main className="page">
        <h1>{t('nav.models')}</h1>
        <div className="card">
          <p className="muted">{t('models.webOnly')}</p>
        </div>
      </main>
    )
  }

  const installedList = installed?.installed || []
  const byCrop = new Map(installedList.map((p) => [p.crop, p]))
  const busy = progress?.active

  return (
    <main className="page">
      <h1>{t('nav.models')}</h1>
      <p className="lede">{t('models.lede')}</p>

      {error && <div className="alert danger">{error}</div>}

      {busy && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2>{t('models.installing')}</h2>
          <Bar
            value={
              progress.total_bytes > 0 ? progress.received_bytes / progress.total_bytes : 0
            }
          />
          <p className="muted small" style={{ marginTop: 10, marginBottom: 0 }}>
            {progress.phase === 'verify'
              ? t('models.verifying')
              : progress.phase === 'install'
                ? t('models.finalising')
                : t('models.downloading')}
            {progress.total_bytes > 0 &&
              ` · ${mb(progress.received_bytes)} / ${mb(progress.total_bytes)} MB`}
          </p>
          <p className="muted small" style={{ marginBottom: 0 }}>{t('models.keepOpen')}</p>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>{t('models.onThisPhone')}</h2>
        {installedList.length === 0 && <p className="muted">{t('models.noneInstalled')}</p>}
        {installedList.map((p) => (
          <div key={p.crop} className="spread pack-row">
            <div>
              <strong>{nameOf(p)}</strong> <span className="mono small">v{p.version}</span>
              <div className="muted small">
                {isDetector(p) ? t('models.labTool') : `${p.classes.length} ${t('models.conditions')}`}
                {' · '}
                {mb(p.total_bytes)} MB
              </div>
            </div>
            {p.active && <span className="badge low">{t('models.inUse')}</span>}
          </div>
        ))}
      </div>

      <div className="card">
        <div className="spread" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>{t('models.available')}</h2>
          <button className="ghost" onClick={refresh} disabled={busy}>
            {t('common.refresh')}
          </button>
        </div>

        {catalogError && (
          <div className="alert">
            <strong>{t('models.catalogUnreachable')}</strong>
            <p className="small" style={{ marginBottom: 0 }}>{t('models.catalogWhy')}</p>
            <p className="muted small mono" style={{ marginBottom: 0 }}>{catalogError}</p>
          </div>
        )}

        {!catalogError && (catalog || []).length === 0 && (
          <p className="muted small">{t('models.catalogEmpty')}</p>
        )}

        {(catalog || []).map((c) => {
          const latest = (c.versions || []).find((v) => v.version === c.latest) || c.versions?.[0]
          const have = byCrop.get(c.crop)
          const upToDate = have && have.version === c.latest
          return (
            <div key={c.crop} className="spread pack-row">
              <div>
                <strong>{nameOf(c)}</strong> <span className="mono small">v{c.latest}</span>
                <div className="muted small">
                  {isDetector(c)
                    ? t('models.labTool')
                    : latest
                      ? `${latest.classes.length} ${t('models.conditions')}`
                      : ''}
                  {latest ? ` · ${mb(latest.total_bytes)} MB ${t('models.download')}` : ''}
                </div>
              </div>
              <button
                className={upToDate ? 'ghost' : 'primary auto'}
                disabled={busy || upToDate || !latest}
                onClick={() => install(c.crop, c.latest)}
              >
                {upToDate
                  ? t('models.upToDate')
                  : have
                    ? t('models.update')
                    : t('models.install')}
              </button>
            </div>
          )
        })}

        <p className="muted small" style={{ marginTop: 12, marginBottom: 0 }}>
          {t('models.verifyNote')}
        </p>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2>{t('models.source')}</h2>
        {!editingSource && (
          <div className="spread">
            <span className="mono small" style={{ wordBreak: 'break-all' }}>
              {source?.url || '-'}
            </span>
            <button className="ghost" onClick={() => setEditingSource(true)} disabled={busy}>
              {t('models.change')}
            </button>
          </div>
        )}
        {editingSource && (
          <div className="stack">
            <input
              value={sourceDraft}
              onChange={(e) => setSourceDraft(e.target.value)}
              placeholder="https://example.com/packs"
              spellCheck={false}
            />
            <div className="inline">
              <button className="primary auto" onClick={saveSource}>
                {t('models.save')}
              </button>
              <button
                className="ghost"
                onClick={() => {
                  setSourceDraft(source?.url || '')
                  setEditingSource(false)
                }}
              >
                {t('models.cancel')}
              </button>
            </div>
          </div>
        )}
        <p className="muted small" style={{ marginBottom: 0 }}>{t('models.sourceWhy')}</p>
      </div>
    </main>
  )
}
