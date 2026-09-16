import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
// Bundled, not pulled from unpkg: the Android build ships this UI inside the
// APK and must render with no network at all. A CDN <link> would leave the
// map unstyled offline.
import 'leaflet/dist/leaflet.css'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
