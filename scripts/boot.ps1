<#
.SYNOPSIS
    Boot script for ForgeTrade.

.DESCRIPTION
    Activates the Python virtual environment and launches ForgeTrade
    in the requested mode (paper, live, backtest, or api-only).

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

.EXAMPLE
    .\scripts\boot.ps1                        # Paper trading (default)
    .\scripts\boot.ps1 -Mode live             # Live trading
    .\scripts\boot.ps1 -Mode backtest -Start 2024-01-01 -End 2025-01-01
    .\scripts\boot.ps1 -Mode api              # API server only
    .\scripts\boot.ps1 -Mode api -Port 9090   # API server on custom port
#>

[CmdletBinding()]
param(
    [ValidateSet("paper", "live", "backtest", "api")]
    [string]$Mode = "paper",

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
Write-Host "  |  Automated EUR/USD Forex Trading Bot      |" -ForegroundColor Cyan
Write-Host "  +-------------------------------------------+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Python:  $python" -ForegroundColor DarkGray
Write-Host "  Mode:    $Mode" -ForegroundColor DarkGray
Write-Host "  API:     http://localhost:$Port" -ForegroundColor DarkGray
Write-Host ""

# -- Launch --------------------------------------------------------------------

Push-Location $projectRoot
try {
    switch ($Mode) {
        "paper" {
            Write-Host "[boot] Starting in PAPER mode (practice API)..." -ForegroundColor Green
            Write-Host "[boot] Dashboard: http://localhost:$Port" -ForegroundColor Cyan
            Start-Process "http://localhost:$Port"
            & $python -m app.main --mode paper
        }
        "live" {
            Write-Host "[boot] Starting in LIVE mode -- real money at risk!" -ForegroundColor Red
            Write-Host "[boot] Dashboard: http://localhost:$Port" -ForegroundColor Cyan
            Start-Process "http://localhost:$Port"
            & $python -m app.main --mode live
        }
        "backtest" {
            $btArgs = @("--mode", "backtest")
            if ($Start) { $btArgs += "--start"; $btArgs += $Start }
            if ($End)   { $btArgs += "--end";   $btArgs += $End }
            Write-Host "[boot] Starting BACKTEST..." -ForegroundColor Magenta
            & $python -m app.main @btArgs
        }
        "api" {
            Write-Host "[boot] Starting API server on http://localhost:$Port ..." -ForegroundColor Blue
            & $python -m uvicorn app.main:app --host 0.0.0.0 --port $Port
        }
    }

    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and $null -ne $exitCode) {
        Write-Host "[boot] Process exited with code $exitCode" -ForegroundColor Red
    } else {
        Write-Host "[boot] ForgeTrade stopped." -ForegroundColor Gray
    }
} finally {
    Pop-Location
}
