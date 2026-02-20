<#
.SYNOPSIS
    Boot script for ForgeTrade.

.DESCRIPTION
    Activates the Python virtual environment and launches ForgeTrade
    in the requested mode (paper, live, backtest, or api-only).
    Automatically builds the React dashboard if the production build
    is missing. Use -Dev to start the Vite dev server with HMR alongside
    the trading engine.

.PARAMETER Mode
    Trading mode: paper (default), live, backtest, or api.
    - paper   : Connect to OANDA practice API and trade.
    - live    : Connect to OANDA live API (real money).
    - backtest: Replay historical data through the strategy engine.
    - api     : Start only the internal FastAPI server (health/status/trades).

.PARAMETER Start
    Backtest start date (YYYY-MM-DD). Only used with -Mode backtest.

.PARAMETER End
    Backtest end date (YYYY-MM-DD). Only used with -Mode backtest.

.PARAMETER Port
    Port for the internal API server (default: 8080). Only used with -Mode api.

.PARAMETER Dev
    Start the Vite dev server alongside the backend for hot module replacement.
    Dashboard will be at http://localhost:5173 (proxies API to the backend).

.EXAMPLE
    .\scripts\boot.ps1                        # Paper trading (default)
    .\scripts\boot.ps1 -Mode live             # Live trading
    .\scripts\boot.ps1 -Dev                   # Paper + Vite HMR dev server
    .\scripts\boot.ps1 -Mode backtest -Start 2024-01-01 -End 2025-01-01
    .\scripts\boot.ps1 -Mode api              # API server only
    .\scripts\boot.ps1 -Mode api -Port 9090   # API server on custom port
#>

[CmdletBinding()]
param(
    [ValidateSet("paper", "live", "backtest", "api")]
    [string]$Mode = "paper",

    [switch]$Dev,

    [string]$Start,
    [string]$End,

    [int]$Port = 8080
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# -- Resolve paths ----------------------------------------------------------------

$projectRoot = Split-Path $PSScriptRoot -Parent
$forgeJson   = Join-Path $projectRoot "forge.json"

if (-not (Test-Path $forgeJson)) {
    Write-Host "[boot] ERROR: forge.json not found at $forgeJson" -ForegroundColor Red
    exit 1
}

$forge   = Get-Content $forgeJson -Raw | ConvertFrom-Json
$venvRel = $forge.backend.venv_path
$venvDir = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $venvRel))
$python  = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "[boot] ERROR: Python not found at $python" -ForegroundColor Red
    Write-Host "[boot] Run:  python -m venv $venvDir" -ForegroundColor Yellow
    Write-Host "[boot] Then: $python -m pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# -- Check .env --------------------------------------------------------------------

$envFile = Join-Path $projectRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "[boot] WARNING: No .env file found. Copy .env.example and fill in your credentials." -ForegroundColor Yellow
}

# -- Banner --------------------------------------------------------------------

Write-Host ""
Write-Host "  +-------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |          ForgeTrade  v0.1.0               |" -ForegroundColor Cyan
Write-Host "  |  Automated Forex & Commodities Bot        |" -ForegroundColor Cyan
Write-Host "  +-------------------------------------------+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Python:  $python" -ForegroundColor DarkGray
Write-Host "  Mode:    $Mode" -ForegroundColor DarkGray
Write-Host "  API:     http://localhost:$Port" -ForegroundColor DarkGray
if ($Dev) {
    Write-Host "  Dashboard (dev): http://localhost:5173" -ForegroundColor DarkGray
} else {
    Write-Host "  Dashboard: http://localhost:$Port" -ForegroundColor DarkGray
}
Write-Host ""

# -- Dashboard build -----------------------------------------------------------

$dashboardDir = Join-Path $projectRoot "dashboard"
$distIndex    = Join-Path $projectRoot "app\static\dist\index.html"
$npm          = Get-Command npm -ErrorAction SilentlyContinue

if (-not $Dev) {
    if (-not (Test-Path $distIndex)) {
        if ($npm) {
            Write-Host "[boot] Dashboard build not found -- building..." -ForegroundColor Yellow
            Push-Location $dashboardDir
            try {
                if (-not (Test-Path (Join-Path $dashboardDir "node_modules"))) {
                    Write-Host "[boot] Installing npm dependencies..." -ForegroundColor DarkGray
                    & npm install 2>&1 | Out-Null
                }
                & npm run build 2>&1 | Out-Null
                if (Test-Path $distIndex) {
                    Write-Host "[boot] Dashboard built successfully." -ForegroundColor Green
                } else {
                    Write-Host "[boot] WARNING: Dashboard build failed. API will still work." -ForegroundColor Yellow
                }
            } finally {
                Pop-Location
            }
        } else {
            Write-Host "[boot] WARNING: npm not found -- dashboard build skipped. Install Node.js to enable." -ForegroundColor Yellow
        }
    }
}

# -- Launch --------------------------------------------------------------------

$viteJob   = $null
$uvicornJob = $null
$engineJob  = $null
Push-Location $projectRoot
try {
    # Start Vite dev server in background if -Dev flag is set
    if ($Dev -and ($Mode -eq "paper" -or $Mode -eq "live" -or $Mode -eq "api")) {
        if ($npm) {
            Write-Host "[boot] Starting Vite dev server (HMR) on http://localhost:5173 ..." -ForegroundColor Magenta
            $viteJob = Start-Job -ScriptBlock {
                param($dir)
                Set-Location $dir
                & npm run dev 2>&1
            } -ArgumentList $dashboardDir
        } else {
            Write-Host "[boot] WARNING: npm not found -- Vite dev server skipped." -ForegroundColor Yellow
        }
    }

    switch ($Mode) {
        "paper" {
            Write-Host "[boot] Starting in PAPER mode (practice API)..." -ForegroundColor Green
            if ($Dev) {
                Write-Host "[boot] Dashboard (HMR): http://localhost:5173" -ForegroundColor Cyan
                Write-Host "[boot] Uvicorn --reload: .py changes auto-restart the API" -ForegroundColor Magenta
                Start-Process "http://localhost:5173"
                # Split architecture: uvicorn --reload (API) + engine-only (trading)
                $uvicornJob = Start-Job -ScriptBlock {
                    param($py, $dir, $p)
                    Set-Location $dir
                    & $py -m uvicorn app.main:app --host 0.0.0.0 --port $p --reload 2>&1
                } -ArgumentList $python, $projectRoot, $Port
                Write-Host "[boot] API server (auto-reload) on http://localhost:$Port" -ForegroundColor Blue
                # Engine runs in foreground so Ctrl+C stops everything
                & $python -m app.main --mode paper --engine-only
            } else {
                Write-Host "[boot] Dashboard: http://localhost:$Port" -ForegroundColor Cyan
                Start-Process "http://localhost:$Port"
                & $python -m app.main --mode paper
            }
        }
        "live" {
            Write-Host "[boot] Starting in LIVE mode -- real money at risk!" -ForegroundColor Red
            if ($Dev) {
                Write-Host "[boot] Dashboard (HMR): http://localhost:5173" -ForegroundColor Cyan
                Write-Host "[boot] Uvicorn --reload: .py changes auto-restart the API" -ForegroundColor Magenta
                Start-Process "http://localhost:5173"
                $uvicornJob = Start-Job -ScriptBlock {
                    param($py, $dir, $p)
                    Set-Location $dir
                    & $py -m uvicorn app.main:app --host 0.0.0.0 --port $p --reload 2>&1
                } -ArgumentList $python, $projectRoot, $Port
                Write-Host "[boot] API server (auto-reload) on http://localhost:$Port" -ForegroundColor Blue
                & $python -m app.main --mode live --engine-only
            } else {
                Write-Host "[boot] Dashboard: http://localhost:$Port" -ForegroundColor Cyan
                Start-Process "http://localhost:$Port"
                & $python -m app.main --mode live
            }
        }
        "backtest" {
            $btArgs = @("--mode", "backtest")
            if ($Start) { $btArgs += "--start"; $btArgs += $Start }
            if ($End)   { $btArgs += "--end";   $btArgs += $End }
            Write-Host "[boot] Starting BACKTEST..." -ForegroundColor Magenta
            & $python -m app.main @btArgs
        }
        "api" {
            if ($Dev) {
                Write-Host "[boot] Starting API server (auto-reload) on http://localhost:$Port ..." -ForegroundColor Blue
                Write-Host "[boot] Uvicorn --reload: .py changes auto-restart the API" -ForegroundColor Magenta
                Write-Host "[boot] Dashboard (HMR): http://localhost:5173" -ForegroundColor Cyan
                Start-Process "http://localhost:5173"
                & $python -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
            } else {
                Write-Host "[boot] Starting API server on http://localhost:$Port ..." -ForegroundColor Blue
                & $python -m uvicorn app.main:app --host 0.0.0.0 --port $Port
            }
        }
    }

    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and $null -ne $exitCode) {
        Write-Host "[boot] Process exited with code $exitCode" -ForegroundColor Red
    } else {
        Write-Host "[boot] ForgeTrade stopped." -ForegroundColor Gray
    }
} finally {
    if ($uvicornJob) {
        Write-Host "[boot] Stopping uvicorn (reload) server..." -ForegroundColor DarkGray
        Stop-Job $uvicornJob -ErrorAction SilentlyContinue
        Remove-Job $uvicornJob -ErrorAction SilentlyContinue
    }
    if ($viteJob) {
        Write-Host "[boot] Stopping Vite dev server..." -ForegroundColor DarkGray
        Stop-Job $viteJob -ErrorAction SilentlyContinue
        Remove-Job $viteJob -ErrorAction SilentlyContinue
    }
    Pop-Location
}
