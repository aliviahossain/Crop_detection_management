# Builds the CropGuard web UI and stages it into the Flutter app's assets, so
# the APK can serve it from 127.0.0.1 with no network.
#
#   pwsh mobileapp/tools/stage_web.ps1
#
# Run this after ANY frontend change. The staged copy is gitignored build
# output; forgetting to re-run it means the APK ships a stale UI and the
# mismatch is invisible until someone notices a fix missing on the phone.

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$frontend = Join-Path $repo 'frontend'
$dist = Join-Path $frontend 'dist'
$dest = Join-Path $repo 'mobileapp\app\assets\web'

Write-Host "Building frontend..." -ForegroundColor Cyan
Push-Location $frontend
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed ($LASTEXITCODE)" }
}
finally { Pop-Location }

if (-not (Test-Path $dist)) { throw "No dist/ produced at $dist" }

Write-Host "Staging into $dest ..." -ForegroundColor Cyan
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item "$dist\*" $dest -Recurse -Force

# Drop any jsep (WebGPU) ONNX runtime that still turns up in the build.
#
# This used to be load-bearing and WRONG. The comment here claimed the binary
# was "bundled by Vite but never fetched" because liveDetector requests the
# wasm provider with numThreads=1. It is fetched: the default `onnxruntime-web`
# entry dynamically imports ort-wasm-simd-threaded.jsep.mjs at session
# creation regardless of the provider you ask for. Deleting it meant every
# on-device session failed with "no available backend found", and because the
# local server answered the missing file with index.html, the browser reported
# a MIME type error instead of a 404.
#
# liveDetector now imports `onnxruntime-web/wasm`, which never asks for jsep,
# so the build no longer emits it and this loop is a belt-and-braces no-op.
# It stays because a future dependency bump could reintroduce the file.
$dropped = 0
Get-ChildItem (Join-Path $dest 'assets') -Filter '*jsep*' -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host ("  dropping unused {0} ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB)) -ForegroundColor Yellow
    Remove-Item $_.FullName -Force
    $dropped += 1
}

$total = (Get-ChildItem $dest -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("Staged {0:N1} MB ({1} unused runtime(s) dropped)" -f ($total / 1MB), $dropped) -ForegroundColor Green
Write-Host "Now rebuild the APK: flutter build apk --release"
