# Starts the API and the frontend dev server in two PowerShell windows.
#   powershell -ExecutionPolicy Bypass -File scripts/run_dev.ps1

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No virtualenv found. Create one first:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\python.exe -m pip install -r backend\requirements.txt"
    exit 1
}

Write-Host "Starting API on http://localhost:8000 ..." -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$repo'; `$env:PYTHONPATH='backend'; & '$python' -m uvicorn app.main:app --reload --port 8000"
)

if (Test-Path (Join-Path $repo "frontend\node_modules")) {
    Write-Host "Starting frontend on http://localhost:5173 ..." -ForegroundColor Green
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "Set-Location '$repo\frontend'; npm run dev"
    )
} else {
    Write-Host "frontend\node_modules is missing - run 'npm install' in frontend\ first." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "API docs : http://localhost:8000/docs"
Write-Host "Health   : http://localhost:8000/meta/health"
Write-Host "App      : http://localhost:5173"
Write-Host ""
Write-Host "No data on the map or dashboard? Run:" -ForegroundColor Cyan
Write-Host "  .venv\Scripts\python.exe scripts\seed_demo_data.py --cases 120"
