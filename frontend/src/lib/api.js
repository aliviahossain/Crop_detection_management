// Single place that knows how to talk to the backend.
// In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.js), so
// there is no CORS story to get wrong and prod can serve both from one origin.
const BASE = import.meta.env.VITE_API_BASE || '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    let detail
    try {
      detail = (await res.json()).detail
    } catch {
      detail = await res.text()
    }
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status})`)
  }
  return res.json()
}

const json = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => request('/meta/health'),
  classes: () => request('/meta/classes'),
  languages: () => request('/meta/languages'),

  detect: (formData) => request('/detect', { method: 'POST', body: formData }),
  detectStatus: () => request('/detect/status'),
  // Live scanner: stateless per-frame inference, no case and no DB write.
  detectFrame: (formData) => request('/detect/frame', { method: 'POST', body: formData }),
  detectThresholds: () => request('/detect/thresholds'),
  modelUrl: () => `${BASE}/detect/model`,

  risk: (payload) => request('/risk', json(payload)),
  riskModels: () => request('/risk/models'),
  weather: (params) => request(`/risk/weather?${new URLSearchParams(params)}`),

  advisory: (payload) => request('/advisory', json(payload)),

  hotspots: (params) => request(`/hotspots?${new URLSearchParams(params)}`),
  hotspotPoints: (params) => request(`/hotspots/points?${new URLSearchParams(params)}`),

  reviewQueue: (params) => request(`/review/queue?${new URLSearchParams(params)}`),
  reviewCase: (id) => request(`/review/${id}`),
  decide: (id, payload) => request(`/review/${id}`, json(payload)),
  accuracy: (params = {}) => request(`/review/stats/accuracy?${new URLSearchParams(params)}`),

  dashboard: (params) => request(`/dashboard/summary?${new URLSearchParams(params)}`),
  trend: (params) => request(`/dashboard/trend?${new URLSearchParams(params)}`),
  districts: (params = {}) => request(`/dashboard/districts?${new URLSearchParams(params)}`),

  followUps: (params) => request(`/followups?${new URLSearchParams(params)}`),
  updateFollowUp: (id, payload) =>
    request(`/followups/${id}`, { ...json(payload), method: 'PATCH' }),
  followUpStats: (params = {}) => request(`/followups/stats?${new URLSearchParams(params)}`),

  sensors: (params) => request(`/sensors?${new URLSearchParams(params)}`),
  sensorSummary: (params = {}) => request(`/sensors/summary?${new URLSearchParams(params)}`),
  postSensor: (payload) => request('/sensors', json(payload)),

  // Floating assistant. The Gemini key lives on the backend; we only ever
  // send the message + recent history and get a reply back.
  chat: (payload) => request('/chat', json(payload)),
  chatStatus: () => request('/chat/status'),
}

export const mediaUrl = (imagePath) => {
  if (!imagePath) return null
  // Stored paths are repo-relative; /media is mounted at the upload dir.
  const marker = 'data/uploads/'
  const idx = imagePath.indexOf(marker)
  return idx >= 0 ? `/media/${imagePath.slice(idx + marker.length)}` : null
}
