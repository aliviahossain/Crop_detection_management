import { SOIL_OPTIONS, STAGE_OPTIONS, VARIETY_OPTIONS, prettify, useT } from '../lib/i18n.js'

/**
 * Crop stage, variety and soil are not decoration -- the risk engine multiplies
 * the agronomic score by each of them. Collecting them here is what turns a
 * generic weather forecast into a farm-level one.
 */
export default function FieldContextForm({ value, onChange, showPersonal = false }) {
  const t = useT()
  const set = (key) => (event) => onChange({ ...value, [key]: event.target.value })

  const locate = () => {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        onChange({
          ...value,
          latitude: pos.coords.latitude.toFixed(5),
          longitude: pos.coords.longitude.toFixed(5),
        }),
      () => {},
      { enableHighAccuracy: true, timeout: 8000 },
    )
  }

  return (
    <>
      <div className="field">
        <label>{t('field.location')}</label>
        <div className="row">
          <input placeholder="latitude" value={value.latitude} onChange={set('latitude')} />
          <input placeholder="longitude" value={value.longitude} onChange={set('longitude')} />
        </div>
        <button type="button" className="ghost small" style={{ marginTop: 6 }} onClick={locate}>
          📍 {t('field.locate')}
        </button>
      </div>

      <div className="row">
        <div className="field">
          <label>{t('field.district')}</label>
          <input value={value.district} onChange={set('district')} placeholder="Pune" />
        </div>
        <div className="field">
          <label>{t('field.village')}</label>
          <input value={value.village} onChange={set('village')} placeholder="Manchar" />
        </div>
      </div>

      <div className="field">
        <label>{t('field.variety')}</label>
        <select value={value.variety} onChange={set('variety')}>
          <option value="">—</option>
          {VARIETY_OPTIONS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </div>

      <div className="row">
        <div className="field">
          <label>{t('field.stage')}</label>
          <select value={value.crop_stage} onChange={set('crop_stage')}>
            <option value="">—</option>
            {STAGE_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {prettify(s)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>{t('field.soil')}</label>
          <select value={value.soil_condition} onChange={set('soil_condition')}>
            <option value="">—</option>
            {SOIL_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {prettify(s)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {showPersonal && (
        <>
          <div className="row">
            <div className="field">
              <label>
                {t('field.name')} <span className="muted">({t('common.optional')})</span>
              </label>
              <input value={value.farmer_name} onChange={set('farmer_name')} />
            </div>
            <div className="field">
              <label>
                {t('field.phone')} <span className="muted">({t('common.optional')})</span>
              </label>
              <input value={value.phone} onChange={set('phone')} />
            </div>
          </div>
          <div className="field">
            <label>
              {t('field.severity')}: {Math.round((value.severity_fraction || 0) * 100)}%
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={value.severity_fraction || 0}
              onChange={(e) => onChange({ ...value, severity_fraction: Number(e.target.value) })}
            />
          </div>
        </>
      )}
    </>
  )
}

export const emptyContext = {
  latitude: '',
  longitude: '',
  district: '',
  village: '',
  variety: '',
  crop_stage: '',
  soil_condition: '',
  farmer_name: '',
  phone: '',
  severity_fraction: 0,
}
