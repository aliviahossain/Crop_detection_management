import { prettify } from '../lib/i18n.js'

/**
 * Shows the risk assessment *with its evidence*. An extension officer has to be
 * able to argue with a risk level, so every model output, threshold and context
 * modifier that moved the number is on screen rather than buried in an API
 * response.
 */
export default function RiskPanel({ assessment, compact = false }) {
  if (!assessment) return null
  const { threats = [], weather, weather_warnings: warnings = [], daily = [] } = assessment

  return (
    <div className="card stack">
      <div className="spread">
        <h2 style={{ margin: 0 }}>Weather-based risk</h2>
        <span className={`badge ${assessment.overall_level}`}>
          {assessment.overall_level?.toUpperCase()} · {Math.round(assessment.overall_score * 100)}%
        </span>
      </div>

      {weather && (
        <p className="muted small">
          {weather.hours}h of weather · {weather.temp_min_c}–{weather.temp_max_c} °C · mean RH{' '}
          {weather.humidity_mean}% · rainfall {weather.rainfall_total_mm} mm ·{' '}
          <span className={`badge ${weather.synthetic ? 'medium' : 'low'}`}>
            {weather.synthetic ? 'synthetic feed' : weather.source}
          </span>
        </p>
      )}

      {warnings.map((w, i) => (
        <p key={i} className="muted small">
          ⚠ {w}
        </p>
      ))}

      {threats.map((threat) => (
        <div key={threat.key} style={{ borderTop: '1px solid var(--line)', paddingTop: 12 }}>
          <div className="spread">
            <strong>{threat.display}</strong>
            <span className={`badge ${threat.level}`}>
              {threat.level.toUpperCase()} · {Math.round(threat.score * 100)}%
            </span>
          </div>
          <p className="small" style={{ margin: '6px 0' }}>
            {threat.headline}
          </p>

          {!compact && (
            <details>
              <summary>Evidence</summary>
              <table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Fired</th>
                    <th>Explanation</th>
                  </tr>
                </thead>
                <tbody>
                  {threat.models.map((m) => (
                    <tr key={m.name}>
                      <td className="mono">{m.name}</td>
                      <td>
                        <span className={`badge ${m.triggered ? 'high' : 'neutral'}`}>
                          {m.triggered ? 'yes' : 'no'}
                        </span>
                      </td>
                      <td className="small">{m.explanation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {threat.drivers?.length > 0 && (
                <>
                  <h3>Field context that changed this score</h3>
                  <ul>
                    {threat.drivers.map((d, i) => (
                      <li key={i} className="small">
                        <strong>{prettify(d.factor)}</strong>{' '}
                        {d.multiplier != null ? `×${d.multiplier}` : `+${d.added}`} — {d.why}
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {threat.secondary_layer && (
                <p className="muted small">
                  Secondary XGBoost layer:{' '}
                  {threat.secondary_layer.active
                    ? `adjusted by ${threat.secondary_layer.adjustment}`
                    : threat.secondary_layer.reason}
                </p>
              )}
            </details>
          )}
        </div>
      ))}

      {!compact && daily.length > 0 && (
        <details>
          <summary>Daily weather behind these models</summary>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Min °C</th>
                  <th>Max °C</th>
                  <th>Mean RH</th>
                  <th>Hours RH ≥ 90%</th>
                  <th>Rain mm</th>
                </tr>
              </thead>
              <tbody>
                {daily.map((d) => (
                  <tr key={d.day}>
                    <td>{d.day}</td>
                    <td>{d.temp_min}</td>
                    <td>{d.temp_max}</td>
                    <td>{d.rh_mean}%</td>
                    <td>
                      {/* 11 hours is the Smith Period threshold -- flag the days that qualify */}
                      <strong style={{ color: d.hours_rh_above_90 >= 11 ? 'var(--high)' : 'inherit' }}>
                        {d.hours_rh_above_90}
                      </strong>
                    </td>
                    <td>{d.rainfall_mm}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  )
}
