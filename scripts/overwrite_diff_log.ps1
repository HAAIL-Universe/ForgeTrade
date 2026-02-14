# scripts/overwrite_diff_log.ps1
# Overwrite the diff log with a structured Markdown entry.
# Default: STAGED changes only (recommended for scoped, minimal diffs).
#
# Usage:
#   git add <scoped files>
#   .\scripts\overwrite_diff_log.ps1 -Status COMPLETE `
#     -Summary @("Did X", "Did Y") `
#     -Verification @("compileall: pass", "pytest: pass") `
#     -NextSteps @("Next: do Z")
#
# Unstaged (not recommended):
#   .\scripts\overwrite_diff_log.ps1 -IncludeUnstaged
#
# Finalize (check for remaining TODOs):
#   .\scripts\overwrite_diff_log.ps1 -Finalize
#
# Open the log in VS Code:
#   .\scripts\overwrite_diff_log.ps1 -OpenInVSCode

[CmdletBinding()]
param(
  [ValidateSet("IN_PROCESS","COMPLETE","BLOCKED")]
  [string]$Status = "IN_PROCESS",

  [string[]]$Summary = @(),
  [string[]]$Verification = @(),
  [string[]]$NextSteps = @(),

  [switch]$Finalize,
  [switch]$IncludeUnstaged,
  [switch]$OpenInVSCode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$m) { Write-Host "[overwrite_diff_log] $m" -ForegroundColor Cyan }
function Warn([string]$m) { Write-Host "[overwrite_diff_log] $m" -ForegroundColor Yellow }
function Err ([string]$m) { Write-Host "[overwrite_diff_log] $m" -ForegroundColor Red }

function HasCmd([string]$name) {
  return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function RequireGit {
  if (-not (HasCmd "git")) { throw "git not found on PATH." }
  $ok = & git rev-parse --is-inside-work-tree 2>$null
  if ($LASTEXITCODE -ne 0 -or $ok.Trim() -ne "true") {
    throw "Not inside a git repo. Run from the repo (or a subdir)."
  }
}

function RepoRoot {
  return (& git rev-parse --show-toplevel).Trim()
}

function ResolveLogPath([string]$root) {
  $pEvidence = Join-Path $root "evidence\updatedifflog.md"
  if (Test-Path $pEvidence) { return $pEvidence }
  # Default: create in evidence folder
  return $pEvidence
}

function EnsureParent([string]$path) {
  $parent = Split-Path -Parent $path
  if ($parent -and -not (Test-Path $parent)) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
  }
}

function Bullets([string[]]$items, [string]$todo) {
  if ($null -eq $items -or $items.Count -eq 0) { return @("- $todo") }
  return @($items | ForEach-Object { "- $_" })
}

function Indent4([string[]]$lines) {
  if ($null -eq $lines -or $lines.Count -eq 0) { return @("    (none)") }
  return @($lines | ForEach-Object { "    $_" })
}

try {
  RequireGit
  $root = RepoRoot
  Set-Location $root

  $logPath = ResolveLogPath $root
  EnsureParent $logPath

  $timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
  $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
  $head = (& git rev-parse HEAD).Trim()
  $baseHead = ""
  try {
    $baseHead = (& git rev-parse HEAD^).Trim()
  } catch {
    $baseHead = ""
  }

  if ($Finalize) {
    if (-not (Test-Path $logPath)) {
      Err "Finalize failed: evidence/updatedifflog.md not found at $logPath"
      exit 1
    }
    $todoMatches = Select-String -Path $logPath -Pattern "TODO:" -SimpleMatch -ErrorAction SilentlyContinue
    if ($todoMatches) {
      Err "Finalize failed: TODO placeholders remain in diff log."
      exit 1
    }
    Info "Finalize passed: no TODO placeholders found."
    exit 0
  }

  $stagedOnly = -not $IncludeUnstaged
  $basis = if ($stagedOnly) { "staged" } else { "unstaged (working tree)" }

  $nameOnlyArgs = @("diff","--name-only")
  if ($stagedOnly) { $nameOnlyArgs += "--staged" }
  $changedFiles = @((& git @nameOnlyArgs) | Where-Object { $_ -and $_.Trim().Length -gt 0 } | ForEach-Object { $_.Trim() })

  $diffArgs = @("diff","--unified=3")
  if ($stagedOnly) { $diffArgs += "--staged" }
  $patchRaw = & git @diffArgs
  $patchLines = @()
  if ($patchRaw -is [string]) { $patchLines = @($patchRaw -split "`r?`n") }
  else { $patchLines = @($patchRaw | ForEach-Object { "$_" }) }

  if ($stagedOnly -and $changedFiles.Count -eq 0) {
    Warn "No staged changes found. Recommended: git add <scoped files> then re-run."
    Warn "If you truly want unstaged, re-run with -IncludeUnstaged."
  }

  $summaryTodo = "TODO: 1-5 bullets (what changed, why, scope)."
  $verificationTodo = "TODO: verification evidence (static -> runtime -> behavior -> contract)."
  $nextStepsTodo = "TODO: next actions (small, specific)."
  $summaryLines = Bullets -items $Summary -todo $summaryTodo
  $verificationLines = Bullets -items $Verification -todo $verificationTodo
  $nextStepsLines = Bullets -items $NextSteps -todo $nextStepsTodo

  $filesLines = if ($changedFiles.Count -gt 0) { @($changedFiles | ForEach-Object { "- $_" }) } else { @("- (none detected)") }

  $statusShort = (& git status -sb).TrimEnd()
  $statusIndented = Indent4 @($statusShort -split "`r?`n")
  $patchIndented = Indent4 $patchLines

  $out = New-Object System.Collections.Generic.List[string]
  $out.Add("# Diff Log (overwrite each cycle)")
  $out.Add("")
  $baseHeadLabel = if ([string]::IsNullOrWhiteSpace($baseHead)) { "N/A (no parent)" } else { $baseHead }
  $out.Add("## Cycle Metadata")
  $out.Add("- Timestamp: $timestamp")
  $out.Add("- Branch: $branch")
  $out.Add("- HEAD: $head")
  $out.Add("- BASE_HEAD: $baseHeadLabel")
  $out.Add("- Diff basis: $basis")
  $out.Add("")
  $out.Add("## Cycle Status")
  $out.Add("- Status: $Status")
  $out.Add("")
  $out.Add("## Summary")
  $summaryLines | ForEach-Object { $out.Add($_) }
  $out.Add("")
  $out.Add("## Files Changed ($basis)")
  $filesLines | ForEach-Object { $out.Add($_) }
  $out.Add("")
  $out.Add("## git status -sb")
  $statusIndented | ForEach-Object { $out.Add($_) }
  $out.Add("")
  $out.Add("## Minimal Diff Hunks")
  $patchIndented | ForEach-Object { $out.Add($_) }
  $out.Add("")
  $out.Add("## Verification")
  $verificationLines | ForEach-Object { $out.Add($_) }
  $out.Add("")
  $out.Add("## Notes (optional)")
  $out.Add("- TODO: blockers, risks, constraints.")
  $out.Add("")
  $out.Add("## Next Steps")
  $nextStepsLines | ForEach-Object { $out.Add($_) }
  $out.Add("")

  $out | Out-File -LiteralPath $logPath -Encoding utf8

  Info "Wrote diff log (overwritten): $logPath"
  Info ("Files listed: {0}" -f $changedFiles.Count)

  if ($OpenInVSCode) {
    if (HasCmd "code") {
      & code -g ($logPath + ":1") | Out-Null
      Info "Opened in VS Code."
    } else {
      Warn "VS Code CLI 'code' not found on PATH. Skipping open."
    }
  }

  exit 0
}
catch {
  Err $_.Exception.Message
  exit 1
}
