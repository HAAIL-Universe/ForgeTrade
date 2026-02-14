# scripts/run_tests.ps1
# Stack-aware test runner for Forge-managed projects.
# Reads forge.json for stack configuration.
# Runs static checks, backend tests, and frontend tests (if enabled).
# Appends results to evidence/test_runs.md and overwrites evidence/test_runs_latest.md.
#
# Usage:
#   pwsh -File .\scripts\run_tests.ps1
#   pwsh -File .\scripts\run_tests.ps1 -Scope backend
#   pwsh -File .\scripts\run_tests.ps1 -Scope frontend
#   pwsh -File .\scripts\run_tests.ps1 -NoVenv
#
# Exit codes:
#   0 — All test phases PASS.
#   1 — One or more test phases FAIL.

param(
  [switch]$NoVenv,
  [ValidateSet("all", "backend", "frontend")]
  [string]$Scope = "all"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Load-DotEnv {
  param([string]$Path = ".env")
  if (-not (Test-Path $Path)) { return }
  Get-Content -Path $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line) { return }
    if ($line.StartsWith("#")) { return }
    $parts = $line.Split("=", 2)
    if ($parts.Count -lt 2) { return }
    $key = $parts[0].Trim()
    $val = $parts[1].Trim()
    if ($val.StartsWith('"') -and $val.EndsWith('"')) { $val = $val.Trim('"') }
    elseif ($val.StartsWith("'") -and $val.EndsWith("'")) { $val = $val.Trim("'") }
    if (-not $key) { return }
    if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($key))) {
      [Environment]::SetEnvironmentVariable($key, $val)
    }
  }
}

function Info($msg) { Write-Host "[run_tests] $msg" -ForegroundColor Cyan }
function Err($msg)  { Write-Host "[run_tests] $msg" -ForegroundColor Red }

function Tail-Lines([string[]]$lines, [int]$n) {
  if (-not $lines) { return @() }
  if ($lines.Count -le $n) { return $lines }
  return $lines[($lines.Count - $n)..($lines.Count - 1)]
}

function Resolve-Python {
  param([string]$root, [string]$venvPath)
  if (-not $NoVenv -and $venvPath) {
    # Try local venv
    $localVenv = Join-Path $root "$venvPath/Scripts/python.exe"
    $localVenvUnix = Join-Path $root "$venvPath/bin/python"
    foreach ($path in @($localVenv, $localVenvUnix)) {
      if (Test-Path $path) { return $path }
    }
  }
  return "python"
}

function Resolve-Node {
  return "node"
}

function Append-TestRunLog(
  [string]$root,
  [string]$statusText,
  [string]$runtimePath,
  [string]$startUtc,
  [string]$endUtc,
  [hashtable]$exitCodes,
  [hashtable]$summaries,
  [string]$gitBranch,
  [string]$gitHead,
  [string]$gitStatus,
  [string]$gitDiffStat,
  [string]$failurePayload = ""
) {
  $logPath = Join-Path $root "evidence\test_runs.md"
  $logDir = Split-Path -Parent $logPath
  if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }

  $lines = @()
  $lines += "## Test Run $startUtc"
  $lines += "- Status: $statusText"
  $lines += "- Start: $startUtc"
  $lines += "- End: $endUtc"
  $lines += "- Runtime: $runtimePath"
  $lines += "- Branch: $gitBranch"
  $lines += "- HEAD: $gitHead"

  foreach ($key in $exitCodes.Keys) {
    $lines += "- $key exit: $($exitCodes[$key])"
  }
  foreach ($key in $summaries.Keys) {
    $lines += "- $key summary: $($summaries[$key])"
  }

  $lines += "- git status -sb:"
  $lines += '```'
  $lines += $gitStatus
  $lines += '```'
  $lines += "- git diff --stat:"
  $lines += '```'
  $lines += $gitDiffStat
  $lines += '```'
  if ($statusText -eq "FAIL" -and $failurePayload) {
    $lines += "- Failure payload:"
    $lines += '```'
    $lines += $failurePayload
    $lines += '```'
  }
  $lines += ""

  Add-Content -LiteralPath $logPath -Value $lines -Encoding utf8
}

function Write-TestRunLatest(
  [string]$root,
  [string]$statusText,
  [string]$runtimePath,
  [string]$startUtc,
  [string]$endUtc,
  [hashtable]$exitCodes,
  [hashtable]$summaries,
  [string]$failingTests,
  [string]$gitBranch,
  [string]$gitHead,
  [string]$gitStatus,
  [string]$gitDiffStat,
  [string]$failurePayload = ""
) {
  $logPath = Join-Path $root "evidence\test_runs_latest.md"
  $logDir = Split-Path -Parent $logPath
  if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }

  $lines = @()
  $lines += "Status: $statusText"
  $lines += "Start: $startUtc"
  $lines += "End: $endUtc"
  $lines += "Branch: $gitBranch"
  $lines += "HEAD: $gitHead"
  $lines += "Runtime: $runtimePath"

  foreach ($key in $exitCodes.Keys) {
    $lines += "$key exit: $($exitCodes[$key])"
  }
  foreach ($key in $summaries.Keys) {
    $lines += "$key summary: $($summaries[$key])"
  }

  if ($statusText -eq "FAIL") {
    $lines += "Failing tests:"
    if ($failingTests) { $lines += $failingTests }
    else { $lines += "(see console output)" }
    if ($failurePayload) {
      $lines += "Failure payload:"
      $lines += '```'
      $lines += $failurePayload
      $lines += '```'
    }
  }

  $lines += "git status -sb:"
  $lines += '```'
  $lines += $gitStatus
  $lines += '```'
  $lines += "git diff --stat:"
  $lines += '```'
  $lines += $gitDiffStat
  $lines += '```'
  $lines += ""

  Set-Content -LiteralPath $logPath -Value $lines -Encoding utf8
}

# ── Main ─────────────────────────────────────────────────────────────────

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root
Load-DotEnv

$startUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$statusText = "FAIL"
$failingTests = ""
$failurePayload = ""

$exitCodes = [ordered]@{}
$summaries = [ordered]@{}
$outputCaptures = [ordered]@{}

$gitBranch = "git unavailable"
$gitHead = "git unavailable"
$gitStatus = "git unavailable"
$gitDiffStat = "git unavailable"

try {
  $gitBranch = (& git rev-parse --abbrev-ref HEAD 2>$null)
  if ($LASTEXITCODE -ne 0 -or -not $gitBranch) { $gitBranch = "git unavailable" }
  $gitHead = (& git rev-parse HEAD 2>$null)
  if ($LASTEXITCODE -ne 0 -or -not $gitHead) { $gitHead = "git unavailable" }
  $gitStatus = (& git status -sb 2>$null)
  if ($LASTEXITCODE -ne 0 -or -not $gitStatus) { $gitStatus = "git unavailable" }
  $gitDiffStat = (& git diff --stat 2>$null)
  if ($LASTEXITCODE -ne 0) { $gitDiffStat = "git unavailable" }
}
catch {
  $gitBranch = "git unavailable"
  $gitHead = "git unavailable"
  $gitStatus = "git unavailable"
  $gitDiffStat = "git unavailable"
}

# Read forge.json for stack config
$forgeJsonPath = Join-Path $root "forge.json"
$forge = $null
if (Test-Path $forgeJsonPath) {
  $forge = Get-Content $forgeJsonPath -Raw | ConvertFrom-Json
  Info "forge.json loaded: $($forge.project_name) ($($forge.backend.language))"
} else {
  Warn "forge.json not found. Using defaults (Python)."
  # Create a default config object
  $forge = [PSCustomObject]@{
    project_name = "unknown"
    backend = [PSCustomObject]@{
      language = "python"
      entry_module = "app.main"
      test_framework = "pytest"
      test_dir = "tests"
      dependency_file = "requirements.txt"
      venv_path = ".venv"
    }
    frontend = [PSCustomObject]@{
      enabled = $false
      dir = "web"
      build_cmd = $null
      test_cmd = $null
    }
  }
}

$runtimePath = ""

try {

  # ── Backend Tests ────────────────────────────────────────────────────

  if ($Scope -eq "all" -or $Scope -eq "backend") {

    switch ($forge.backend.language) {

      "python" {
        $py = Resolve-Python -root $root -venvPath $forge.backend.venv_path
        $runtimePath = $py
        Info "Python: $py"

        # Static: compileall
        $compileOutLines = & $py -m compileall app 2>&1
        $exitCodes["compileall"] = $LASTEXITCODE
        $outputCaptures["compileall"] = $compileOutLines
        if ($LASTEXITCODE -eq 0) { Info "compileall: ok" } else { Err "compileall failed ($LASTEXITCODE)" }

        # Static: import sanity
        $entryModule = $forge.backend.entry_module
        $importOutLines = & $py -c "import $entryModule; print('import ok')" 2>&1
        $exitCodes["import_sanity"] = $LASTEXITCODE
        $outputCaptures["import_sanity"] = $importOutLines
        if ($LASTEXITCODE -eq 0) { Info "import $entryModule`: ok" } else { Err "import $entryModule failed ($LASTEXITCODE)" }

        # Tests: pytest
        $pytestLines = @()
        $testDir = $forge.backend.test_dir
        Info "pytest scope: $testDir"
        $pytestOutput = & $py -m pytest $testDir -q 2>&1 | Tee-Object -Variable pytestLines
        $exitCodes["pytest"] = $LASTEXITCODE
        $outputCaptures["pytest"] = $pytestLines
        $nonEmpty = $pytestLines | Where-Object { $_ -and $_.Trim().Length -gt 0 }
        if ($nonEmpty.Count -gt 0) { $summaries["pytest"] = $nonEmpty[-1] } else { $summaries["pytest"] = "(no output)" }
        if ($LASTEXITCODE -ne 0) {
          $failingTests = ($nonEmpty | Where-Object { $_ -match "FAILED" -or $_ -match "::" }) -join "`n"
        }
        if ($LASTEXITCODE -eq 0) { Info "pytest: ok" } else { Err "pytest failed ($LASTEXITCODE)" }
      }

      "typescript" {
        $runtimePath = "node"
        Info "Runtime: Node.js (TypeScript)"

        # Static: tsc --noEmit
        $tscLines = & npx tsc --noEmit 2>&1
        $exitCodes["tsc"] = $LASTEXITCODE
        $outputCaptures["tsc"] = $tscLines
        if ($LASTEXITCODE -eq 0) { Info "tsc --noEmit: ok" } else { Err "tsc --noEmit failed ($LASTEXITCODE)" }

        # Tests
        $testFramework = $forge.backend.test_framework
        $testLines = & npm test 2>&1 | Tee-Object -Variable testCapture
        $exitCodes[$testFramework] = $LASTEXITCODE
        $outputCaptures[$testFramework] = $testCapture
        $nonEmpty = $testCapture | Where-Object { $_ -and $_.Trim().Length -gt 0 }
        if ($nonEmpty.Count -gt 0) { $summaries[$testFramework] = $nonEmpty[-1] } else { $summaries[$testFramework] = "(no output)" }
        if ($LASTEXITCODE -eq 0) { Info "$testFramework`: ok" } else { Err "$testFramework failed ($LASTEXITCODE)" }
      }

      "go" {
        $runtimePath = "go"
        Info "Runtime: Go"

        # Static: go vet
        $vetLines = & go vet ./... 2>&1
        $exitCodes["go_vet"] = $LASTEXITCODE
        $outputCaptures["go_vet"] = $vetLines
        if ($LASTEXITCODE -eq 0) { Info "go vet: ok" } else { Err "go vet failed ($LASTEXITCODE)" }

        # Tests: go test
        $goTestLines = & go test ./... -v 2>&1 | Tee-Object -Variable goTestCapture
        $exitCodes["go_test"] = $LASTEXITCODE
        $outputCaptures["go_test"] = $goTestCapture
        $nonEmpty = $goTestCapture | Where-Object { $_ -and $_.Trim().Length -gt 0 }
        if ($nonEmpty.Count -gt 0) { $summaries["go_test"] = $nonEmpty[-1] } else { $summaries["go_test"] = "(no output)" }
        if ($LASTEXITCODE -eq 0) { Info "go test: ok" } else { Err "go test failed ($LASTEXITCODE)" }
      }

      "javascript" {
        $runtimePath = "node"
        Info "Runtime: Node.js"

        $testFramework = $forge.backend.test_framework
        $testLines = & npm test 2>&1 | Tee-Object -Variable testCapture
        $exitCodes[$testFramework] = $LASTEXITCODE
        $outputCaptures[$testFramework] = $testCapture
        $nonEmpty = $testCapture | Where-Object { $_ -and $_.Trim().Length -gt 0 }
        if ($nonEmpty.Count -gt 0) { $summaries[$testFramework] = $nonEmpty[-1] } else { $summaries[$testFramework] = "(no output)" }
        if ($LASTEXITCODE -eq 0) { Info "$testFramework`: ok" } else { Err "$testFramework failed ($LASTEXITCODE)" }
      }

      default {
        Warn "Unknown backend language: $($forge.backend.language). Skipping backend tests."
        $runtimePath = "unknown"
      }
    }
  } else {
    Info "Skipping backend tests (scope=$Scope)"
  }

  # ── Frontend Tests ───────────────────────────────────────────────────

  if (($Scope -eq "all" -or $Scope -eq "frontend") -and $forge.frontend.enabled) {
    $frontendDir = $forge.frontend.dir
    Info "Frontend: $frontendDir"

    # Build
    if ($forge.frontend.build_cmd) {
      Info "Running frontend build: $($forge.frontend.build_cmd)"
      $buildParts = $forge.frontend.build_cmd -split " ", 2
      $buildLines = & npm --prefix $frontendDir run ($buildParts[-1]) 2>&1
      $exitCodes["frontend_build"] = $LASTEXITCODE
      $outputCaptures["frontend_build"] = $buildLines
      if ($LASTEXITCODE -eq 0) { Info "frontend build: ok" } else { Err "frontend build failed ($LASTEXITCODE)" }
    }

    # Test
    if ($forge.frontend.test_cmd) {
      Info "Running frontend tests: $($forge.frontend.test_cmd)"
      $feTestLines = @()
      # Parse command — support both "npm run test:e2e" and custom commands
      $testCmd = $forge.frontend.test_cmd
      if ($testCmd.StartsWith("npm")) {
        $cmdParts = $testCmd -split " "
        $feTestLines = & npm --prefix $frontendDir @($cmdParts[1..($cmdParts.Count-1)]) 2>&1
      } else {
        $feTestLines = & $testCmd 2>&1
      }
      $exitCodes["frontend_test"] = $LASTEXITCODE
      $outputCaptures["frontend_test"] = $feTestLines
      $nonEmpty = $feTestLines | Where-Object { $_ -and $_.Trim().Length -gt 0 }
      if ($nonEmpty.Count -gt 0) { $summaries["frontend_test"] = $nonEmpty[-1] } else { $summaries["frontend_test"] = "(no output)" }
      if ($LASTEXITCODE -eq 0) { Info "frontend tests: ok" } else { Err "frontend tests failed ($LASTEXITCODE)" }
    }
  } elseif ($Scope -eq "all" -and -not $forge.frontend.enabled) {
    Info "Frontend disabled in forge.json; skipping frontend tests."
  } else {
    Info "Skipping frontend tests (scope=$Scope)"
  }

}
finally {
  $endUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

  # Determine overall status
  $overall = 0
  foreach ($key in $exitCodes.Keys) {
    if ($exitCodes[$key] -ne 0) { $overall = 1 }
  }
  if ($exitCodes.Count -eq 0) {
    # No tests ran at all — treat as failure
    $overall = 1
    $summaries["note"] = "No test phases executed"
  }

  if ($overall -eq 0) { $statusText = "PASS" } else { $statusText = "FAIL" }

  # Build failure payload
  if ($statusText -eq "FAIL") {
    $sections = @()
    foreach ($key in $exitCodes.Keys) {
      if ($exitCodes[$key] -ne 0 -and $outputCaptures.ContainsKey($key)) {
        $sections += @("=== $key (exit $($exitCodes[$key])) ===")
        $sections += (Tail-Lines $outputCaptures[$key] 200)
      }
    }
    $failurePayload = ($sections -join "`n").Trim()
  }

  Append-TestRunLog -root $root -statusText $statusText -runtimePath $runtimePath -startUtc $startUtc -endUtc $endUtc `
    -exitCodes $exitCodes -summaries $summaries `
    -gitBranch $gitBranch -gitHead $gitHead -gitStatus ($gitStatus -join "`n") -gitDiffStat ($gitDiffStat -join "`n") `
    -failurePayload $failurePayload

  Write-TestRunLatest -root $root -statusText $statusText -runtimePath $runtimePath -startUtc $startUtc -endUtc $endUtc `
    -exitCodes $exitCodes -summaries $summaries `
    -failingTests $failingTests -gitBranch $gitBranch -gitHead $gitHead -gitStatus ($gitStatus -join "`n") -gitDiffStat ($gitDiffStat -join "`n") `
    -failurePayload $failurePayload

  if ($overall -ne 0) { exit 1 } else { exit 0 }
}
