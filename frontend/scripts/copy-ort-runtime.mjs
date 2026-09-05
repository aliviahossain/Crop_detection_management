// Copies the ONNX Runtime WASM binaries into public/ort/ so the live scanner
// serves them from our own origin.
//
// Why not a CDN: the whole point of on-device inference here is that scanning
// keeps working on a bad field connection or none at all. A CDN dependency
// would quietly undo that.
//
// Why not commit them: 14 MB of binaries do not belong in git, and they must
// stay in lockstep with the installed onnxruntime-web version. This runs
// automatically before dev and build.
import { copyFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const SRC = 'node_modules/onnxruntime-web/dist'
const DST = 'public/ort'
// Only the plain SIMD build: liveDetector requests the 'wasm' provider with
// numThreads=1, so the jsep (WebGPU), jspi and asyncify variants are unused.
const FILES = ['ort-wasm-simd-threaded.wasm', 'ort-wasm-simd-threaded.mjs']

if (!existsSync(SRC)) {
  console.error(`[ort] ${SRC} not found - run npm install first.`)
  process.exit(1)
}

mkdirSync(DST, { recursive: true })
let bytes = 0
for (const file of FILES) {
  const from = join(SRC, file)
  if (!existsSync(from)) {
    console.error(`[ort] missing ${file}. onnxruntime-web layout may have changed.`)
    process.exit(1)
  }
  copyFileSync(from, join(DST, file))
  bytes += statSync(from).size
}
console.log(`[ort] runtime ready in ${DST} (${(bytes / 1e6).toFixed(1)} MB)`)
