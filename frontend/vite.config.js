import { createReadStream, existsSync, statSync } from 'node:fs'
import { join, normalize } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// onnxruntime-web loads its runtime with `import('/ort/ort-wasm-simd-threaded.mjs')`.
// In dev, Vite sees a JS request for a /public file and rejects it ("should not
// be imported from source code"), so the on-device session never starts. Serve
// public/ort/ raw, ahead of Vite's transform middleware. Builds are unaffected:
// public/ is copied as-is.
function serveOrtRuntime() {
  const root = join(process.cwd(), 'public', 'ort')
  const types = { '.mjs': 'text/javascript', '.wasm': 'application/wasm' }
  return {
    name: 'serve-ort-runtime',
    configureServer(server) {
      server.middlewares.use('/ort', (req, res, next) => {
        const name = normalize(decodeURIComponent(req.url.split('?')[0])).replace(/^[\\/]+/, '')
        const file = join(root, name)
        if (!file.startsWith(root) || !existsSync(file) || !statSync(file).isFile()) return next()
        const ext = name.slice(name.lastIndexOf('.'))
        res.setHeader('Content-Type', types[ext] || 'application/octet-stream')
        res.setHeader('Content-Length', statSync(file).size)
        createReadStream(file).pipe(res)
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), serveOrtRuntime()],
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
