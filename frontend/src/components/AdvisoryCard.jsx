import { prettify } from '../lib/i18n.js'

const URGENCY_CLASS = { routine: 'low', soon: 'medium', urgent: 'high' }

/**
 * Renders the server-composed advisory. Everything shown here is already in the
 * farmer's language and already gated by the backend's triage rules -- the UI
 * deliberately does not decide what is safe to show. Its one job is to make the
 * referral notice impossible to miss when the backend says the case must go to
 * an expert.
 */
export default function AdvisoryCard({ advisory, triage }) {
  if (!advisory) return null
  const { chemical, safety, referral, follow_up: followUp, sections = [], references = [] } = advisory
  const chemicalWithheld = chemical?.status === 'withheld_pending_expert_confirmation'

  return (
    <div className="card advisory stack">
      <div className="spread">
        <h2 style={{ margin: 0 }}>{advisory.language === 'en' ? 'Advisory' : 'सल्ला / Advisory'}</h2>
        {triage?.urgency && (
          <span className={`badge ${URGENCY_CLASS[triage.urgency] || 'neutral'}`}>
            {referral?.urgency || prettify(triage.urgency)}
          </span>
        )}
      </div>

      <p className="summary">{advisory.summary}</p>

      {referral?.required && (
        <div className="alert danger">
          <strong>{referral.heading}</strong>
          <ul>
            {referral.items.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
          {referral.reasons?.length > 0 && (
            <details>
              <summary>Why this case needs an expert</summary>
              <ul>
                {referral.reasons.map((r, i) => (
                  <li key={i}>
                    <strong>{prettify(r.code)}:</strong> {r.message}
                    <br />
                    <span className="muted small">{r.action}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {sections
        .filter((s) => s.items?.length)
        .map((section) => (
          <div key={section.key}>
            <h3>{section.heading}</h3>
            <ul>
              {section.items.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>
        ))}

      {chemical && (
        <div>
          <h3>{chemical.heading}</h3>
          {/* The backend supplies this note already translated, so the UI never
              re-states a safety decision in a different language to the API. */}
          {chemical.status_note && (
            <div className={`alert ${chemicalWithheld ? '' : 'info'}`}>{chemical.status_note}</div>
          )}
          {chemical.options?.length > 0 && (
            <>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Dose</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chemical.options.map((opt, i) => (
                      <tr key={i}>
                        <td>{opt.product}</td>
                        <td className="mono">{opt.dose}</td>
                        <td className="muted small">{opt.notes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="alert">{chemical.rotation_note}</p>
              <p className="muted small">{chemical.disclaimer}</p>
            </>
          )}
        </div>
      )}

      {safety?.items?.length > 0 && (
        <div>
          <h3>{safety.heading}</h3>
          <ul>
            {safety.items.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {followUp && (
        <div className="alert info">
          <strong>{followUp.heading}:</strong> {followUp.text}
          <br />
          <span className="small">{followUp.why}</span>
        </div>
      )}

      {references.length > 0 && (
        <details>
          <summary>Sources ({references.length} knowledge-base sections)</summary>
          <ul>
            {references.map((ref, i) => (
              <li key={i}>
                <strong>
                  {ref.title} — {ref.section}
                </strong>
                <div className="muted small">{ref.excerpt_translated || ref.excerpt}</div>
                {ref.sources?.length > 0 && (
                  <div className="muted small">Source: {ref.sources.join('; ')}</div>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
