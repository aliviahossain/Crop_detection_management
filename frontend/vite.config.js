import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy in dev so the browser never deals with CORS and the app can be
    // served from the same origin as the API in production.
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
      '/media': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
