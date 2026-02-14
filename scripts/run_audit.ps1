# scripts/run_audit.ps1
# Deterministic audit script for Forge AEM (Autonomous Execution Mode).
# Runs 9 blocking checks (A1-A9) and 3 non-blocking warnings (W1-W3).
# Reads layer boundaries from Contracts/boundaries.json.
# Appends results to evidence/audit_ledger.md.
#
# Usage:
#   pwsh -File .\scripts\run_audit.ps1 -ClaimedFiles "file1.py,file2.py,..."
#   pwsh -File .\scripts\run_audit.ps1 -ClaimedFiles "file1.py" -Phase "Phase 1"
#
# Exit codes:
#   0 — All blocking checks PASS.
#   1 — One or more blocking checks FAIL.
#   2 — Script execution error (missing dependencies, unreadable files, etc.).

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$ClaimedFiles,

  [string]$Phase = "unknown"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Info([string]$m) { Write-Host "[run_audit] $m" -ForegroundColor Cyan }
function Warn([string]$m) { Write-Host "[run_audit] $m" -ForegroundColor Yellow }
function Err ([string]$m) { Write-Host "[run_audit] $m" -ForegroundColor Red }

function RequireGit {
  $ok = & git rev-parse --is-inside-work-tree 2>$null
  if ($LASTEXITCODE -ne 0 -or $ok.Trim() -ne "true") {
    throw "Not inside a git repo."
  }
}

function RepoRoot {
  return (& git rev-parse --show-toplevel).Trim()
}

# ── Main ─────────────────────────────────────────────────────────────────────

try {
  RequireGit
  $root = RepoRoot

  $timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

  # Parse claimed files into a sorted, normalized set
  $claimed = $ClaimedFiles.Split(",") |
    ForEach-Object { $_.Trim().Replace("\", "/") } |
    Where-Object { $_ -ne "" } |
    Sort-Object -Unique

  if ($claimed.Count -eq 0) {
    throw "ClaimedFiles is empty."
  }

  # Paths
  $evidenceDir       = Join-Path $root "evidence"
  $testRunsLatest    = Join-Path $evidenceDir "test_runs_latest.md"
  $diffLog           = Join-Path $evidenceDir "updatedifflog.md"
  $auditLedger       = Join-Path $evidenceDir "audit_ledger.md"
  $physicsYaml       = Join-Path $root "Contracts" "physics.yaml"
  $boundariesJson    = Join-Path $root "Contracts" "boundaries.json"
  $forgeJson         = Join-Path $root "forge.json"

  # Results accumulator
  $results   = [ordered]@{}
  $warnings  = [ordered]@{}
  $anyFail   = $false

  # ── A1: Scope compliance ───────────────────────────────────────────────

  try {
    $diffStagedRaw   = & git diff --cached --name-only 2>$null
    $diffUnstagedRaw = & git diff --name-only 2>$null

    $diffFiles = @()
    if ($diffStagedRaw)   { $diffFiles += $diffStagedRaw }
    if ($diffUnstagedRaw) { $diffFiles += $diffUnstagedRaw }

    $diffFiles = $diffFiles |
      ForEach-Object { "$_".Trim().Replace("\", "/") } |
      Where-Object { $_ -ne "" } |
      Sort-Object -Unique

    $unclaimed = $diffFiles | Where-Object { $_ -notin $claimed }
    $phantom   = $claimed   | Where-Object { $_ -notin $diffFiles }

    if ($unclaimed -or $phantom) {
      $detail = ""
      if ($unclaimed) { $detail += "Unclaimed in diff: $($unclaimed -join ', '). " }
      if ($phantom)   { $detail += "Claimed but not in diff: $($phantom -join ', ')." }
      $results["A1"] = "FAIL — $detail"
      $anyFail = $true
    } else {
      $results["A1"] = "PASS — git diff matches claimed files exactly ($($diffFiles.Count) files)."
    }
  } catch {
    $results["A1"] = "FAIL — Error running git diff: $_"
    $anyFail = $true
  }

  # ── A2: Minimal-diff discipline ────────────────────────────────────────

  try {
    $summaryRaw = & git diff --cached --summary 2>&1
    $summaryAll = & git diff --summary 2>&1
    $allSummary = @()
    if ($summaryRaw) { $allSummary += $summaryRaw }
    if ($summaryAll) { $allSummary += $summaryAll }

    $renames = $allSummary | Where-Object { $_ -match '\brename\b' }

    if ($renames) {
      $results["A2"] = "FAIL — Rename detected: $($renames -join '; ')"
      $anyFail = $true
    } else {
      $results["A2"] = "PASS — No renames; diff is minimal."
    }
  } catch {
    $results["A2"] = "FAIL — Error checking minimal-diff: $_"
    $anyFail = $true
  }

  # ── A3: Evidence completeness ──────────────────────────────────────────

  try {
    $a3Failures = @()

    if (-not (Test-Path $testRunsLatest)) {
      $a3Failures += "test_runs_latest.md missing"
    } else {
      $firstLine = (Get-Content $testRunsLatest -TotalCount 1).Trim()
      if ($firstLine -notmatch '^Status:\s*PASS') {
        $a3Failures += "test_runs_latest.md line 1 is '$firstLine', expected 'Status: PASS'"
      }
    }

    if (-not (Test-Path $diffLog)) {
      $a3Failures += "updatedifflog.md missing"
    } elseif ((Get-Item $diffLog).Length -eq 0) {
      $a3Failures += "updatedifflog.md is empty"
    }

    if ($a3Failures.Count -gt 0) {
      $results["A3"] = "FAIL — $($a3Failures -join '; ')"
      $anyFail = $true
    } else {
      $results["A3"] = "PASS — test_runs_latest.md=PASS, updatedifflog.md present."
    }
  } catch {
    $results["A3"] = "FAIL — Error checking evidence: $_"
    $anyFail = $true
  }

  # ── A4: Boundary compliance (reads Contracts/boundaries.json) ──────────

  try {
    $a4Violations = @()

    if (-not (Test-Path $boundariesJson)) {
      $results["A4"] = "PASS — No boundaries.json found; boundary check skipped."
    } else {
      $boundaries = Get-Content $boundariesJson -Raw | ConvertFrom-Json

      foreach ($layer in $boundaries.layers) {
        $layerName = $layer.name
        $layerGlob = $layer.glob

        # Resolve glob to actual files
        $globPath = Join-Path $root $layerGlob
        $globDir  = Split-Path $globPath -Parent
        $globFilter = Split-Path $globPath -Leaf

        if (Test-Path $globDir) {
          $layerFiles = Get-ChildItem -Path $globDir -Filter $globFilter -File -ErrorAction SilentlyContinue
          foreach ($lf in $layerFiles) {
            if ($lf.Name -eq "__init__.py" -or $lf.Name -eq "__pycache__") { continue }
            $content = Get-Content $lf.FullName -Raw -ErrorAction SilentlyContinue
            if (-not $content) { continue }

            foreach ($rule in $layer.forbidden) {
              $pat = $rule.pattern
              $reason = $rule.reason
              if ($content -match "(?i)$pat") {
                $a4Violations += "[$layerName] $($lf.Name) contains '$pat' ($reason)"
              }
            }
          }
        }
      }

      if ($a4Violations.Count -gt 0) {
        $results["A4"] = "FAIL — $($a4Violations -join '; ')"
        $anyFail = $true
      } else {
        $results["A4"] = "PASS — No forbidden patterns found in any boundary layer."
      }
    }
  } catch {
    $results["A4"] = "FAIL — Error checking boundaries: $_"
    $anyFail = $true
  }

  # ── A5: Diff Log Gate ──────────────────────────────────────────────────

  try {
    if (-not (Test-Path $diffLog)) {
      $results["A5"] = "FAIL — updatedifflog.md missing."
      $anyFail = $true
    } else {
      $dlContent = Get-Content $diffLog -Raw
      if ($dlContent -match '(?i)TODO:') {
        $results["A5"] = "FAIL — updatedifflog.md contains TODO: placeholders."
        $anyFail = $true
      } else {
        $results["A5"] = "PASS — No TODO: placeholders in updatedifflog.md."
      }
    }
  } catch {
    $results["A5"] = "FAIL — Error checking diff log: $_"
    $anyFail = $true
  }

  # ── A6: Authorization Gate ─────────────────────────────────────────────

  try {
    $lastAuthHash = $null
    if (Test-Path $auditLedger) {
      $ledgerContent = Get-Content $auditLedger -Raw
      $hashMatches = [regex]::Matches($ledgerContent, '(?m)commit[:\s]+([0-9a-f]{7,40})')
      if ($hashMatches.Count -gt 0) {
        $lastAuthHash = $hashMatches[$hashMatches.Count - 1].Groups[1].Value
      }
    }

    if ($lastAuthHash) {
      $recentCommits = & git log --oneline "$lastAuthHash..HEAD" 2>&1
      if ($LASTEXITCODE -ne 0) {
        $results["A6"] = "PASS — Could not resolve last AUTHORIZED hash; assuming clean."
      } elseif ($recentCommits -and $recentCommits.Trim() -ne "") {
        $commitCount = ($recentCommits | Measure-Object -Line).Lines
        $results["A6"] = "FAIL — $commitCount unauthorized commit(s) since last AUTHORIZED ($lastAuthHash)."
        $anyFail = $true
      } else {
        $results["A6"] = "PASS — No unauthorized commits since $lastAuthHash."
      }
    } else {
      $results["A6"] = "PASS — No prior AUTHORIZED entry; first AEM cycle."
    }
  } catch {
    $results["A6"] = "FAIL — Error checking authorization: $_"
    $anyFail = $true
  }

  # ── A7: Verification hierarchy order ───────────────────────────────────

  try {
    if (-not (Test-Path $diffLog)) {
      $results["A7"] = "FAIL — updatedifflog.md missing; cannot verify order."
      $anyFail = $true
    } else {
      $dlText = Get-Content $diffLog -Raw
      $keywords = @("Static", "Runtime", "Behavior", "Contract")
      $positions = @()
      $missing = @()

      foreach ($kw in $keywords) {
        $idx = $dlText.IndexOf($kw, [System.StringComparison]::OrdinalIgnoreCase)
        if ($idx -lt 0) {
          $missing += $kw
        } else {
          $positions += $idx
        }
      }

      if ($missing.Count -gt 0) {
        $results["A7"] = "FAIL — Missing verification keywords: $($missing -join ', ')."
        $anyFail = $true
      } else {
        $ordered = $true
        for ($i = 1; $i -lt $positions.Count; $i++) {
          if ($positions[$i] -le $positions[$i - 1]) {
            $ordered = $false
            break
          }
        }
        if ($ordered) {
          $results["A7"] = "PASS — Verification keywords appear in correct order (Static > Runtime > Behavior > Contract)."
        } else {
          $results["A7"] = "FAIL — Verification keywords are out of order."
          $anyFail = $true
        }
      }
    }
  } catch {
    $results["A7"] = "FAIL — Error checking verification order: $_"
    $anyFail = $true
  }

  # ── A8: Test gate ──────────────────────────────────────────────────────

  try {
    if (-not (Test-Path $testRunsLatest)) {
      $results["A8"] = "FAIL — test_runs_latest.md missing."
      $anyFail = $true
    } else {
      $firstLine = (Get-Content $testRunsLatest -TotalCount 1).Trim()
      if ($firstLine -match '^Status:\s*PASS') {
        $results["A8"] = "PASS — test_runs_latest.md reports PASS."
      } else {
        $results["A8"] = "FAIL — test_runs_latest.md line 1: '$firstLine'."
        $anyFail = $true
      }
    }
  } catch {
    $results["A8"] = "FAIL — Error checking test gate: $_"
    $anyFail = $true
  }

  # ── A9: Dependency gate ────────────────────────────────────────────────

  try {
    $a9Failures = @()

    # Read forge.json to determine stack and dependency file
    if (-not (Test-Path $forgeJson)) {
      $results["A9"] = "PASS — No forge.json found; dependency check skipped (Phase 0?)."
    } else {
      $forge = Get-Content $forgeJson -Raw | ConvertFrom-Json
      $depFile = $forge.backend.dependency_file
      $lang = $forge.backend.language

      $depFilePath = Join-Path $root $depFile
      if (-not (Test-Path $depFilePath)) {
        $results["A9"] = "FAIL — Dependency file '$depFile' not found."
        $anyFail = $true
      } else {
        $depContent = Get-Content $depFilePath -Raw

        # Only check claimed files that are source files
        $sourceExtensions = switch ($lang) {
          "python" { @(".py") }
          "typescript" { @(".ts", ".tsx") }
          "javascript" { @(".js", ".jsx") }
          "go" { @(".go") }
          default { @() }
        }

        foreach ($cf in $claimed) {
          $ext = [System.IO.Path]::GetExtension($cf)
          if ($ext -notin $sourceExtensions) { continue }

          $cfPath = Join-Path $root $cf
          if (-not (Test-Path $cfPath)) { continue }

          $fileContent = Get-Content $cfPath -Raw -ErrorAction SilentlyContinue
          if (-not $fileContent) { continue }

          # Extract imports based on language
          $imports = @()
          switch ($lang) {
            "python" {
              # Match: import X, from X import Y
              $importMatches = [regex]::Matches($fileContent, '(?m)^(?:from\s+(\S+)|import\s+(\S+))')
              foreach ($m in $importMatches) {
                $mod = if ($m.Groups[1].Value) { $m.Groups[1].Value } else { $m.Groups[2].Value }
                # Get top-level module name
                $topLevel = ($mod -split '\.')[0]
                $imports += $topLevel
              }
            }
            "typescript" {
              $importMatches = [regex]::Matches($fileContent, "(?m)(?:import|require)\s*\(?['\""]([@\w][^'""]*)['\""]\)?")
              foreach ($m in $importMatches) {
                $pkg = $m.Groups[1].Value
                # Handle scoped packages: @scope/pkg -> @scope/pkg
                if ($pkg.StartsWith("@")) {
                  $parts = $pkg -split "/"
                  if ($parts.Count -ge 2) { $imports += "$($parts[0])/$($parts[1])" }
                } else {
                  $imports += ($pkg -split "/")[0]
                }
              }
            }
            "javascript" {
              $importMatches = [regex]::Matches($fileContent, "(?m)(?:import|require)\s*\(?['\""]([@\w][^'""]*)['\""]\)?")
              foreach ($m in $importMatches) {
                $pkg = $m.Groups[1].Value
                if ($pkg.StartsWith("@")) {
                  $parts = $pkg -split "/"
                  if ($parts.Count -ge 2) { $imports += "$($parts[0])/$($parts[1])" }
                } else {
                  $imports += ($pkg -split "/")[0]
                }
              }
            }
          }

          $imports = $imports | Sort-Object -Unique

          # Check each import against dependency file
          foreach ($imp in $imports) {
            # Skip standard library / local imports
            switch ($lang) {
              "python" {
                # Skip known stdlib modules and local imports
                $stdlibModules = @(
                  "abc", "asyncio", "base64", "collections", "contextlib", "copy",
                  "csv", "dataclasses", "datetime", "decimal", "enum", "functools",
                  "glob", "hashlib", "html", "http", "importlib", "inspect", "io",
                  "itertools", "json", "logging", "math", "mimetypes", "operator",
                  "os", "pathlib", "pickle", "platform", "pprint", "random", "re",
                  "secrets", "shutil", "signal", "socket", "sqlite3", "string",
                  "struct", "subprocess", "sys", "tempfile", "textwrap", "threading",
                  "time", "timeit", "traceback", "types", "typing", "unittest",
                  "urllib", "uuid", "warnings", "xml", "zipfile",
                  # typing extensions
                  "typing_extensions",
                  # test modules
                  "pytest", "unittest",
                  # local project modules (convention: module matches a dir in root)
                  "app", "tests", "scripts"
                )
                if ($imp -in $stdlibModules) { continue }
                # Check if it's a local directory
                $localDir = Join-Path $root $imp
                if (Test-Path $localDir) { continue }

                # Python: package name might differ from import name
                # Common mappings
                $pyNameMap = @{
                  "PIL" = "Pillow"
                  "cv2" = "opencv-python"
                  "sklearn" = "scikit-learn"
                  "yaml" = "PyYAML"
                  "bs4" = "beautifulsoup4"
                  "dotenv" = "python-dotenv"
                  "jose" = "python-jose"
                  "jwt" = "PyJWT"
                  "pg8000" = "pg8000"
                }
                $lookFor = if ($pyNameMap.ContainsKey($imp)) { $pyNameMap[$imp] } else { $imp }
                if ($depContent -notmatch "(?i)$([regex]::Escape($lookFor))") {
                  $a9Failures += "$cf imports '$imp' (looked for '$lookFor' in $depFile)"
                }
              }
              "typescript" {
                # Skip relative imports and node builtins
                if ($imp.StartsWith(".") -or $imp.StartsWith("/")) { continue }
                $nodeBuiltins = @("fs", "path", "http", "https", "url", "util", "os",
                  "stream", "crypto", "events", "buffer", "child_process", "net",
                  "tls", "dns", "cluster", "zlib", "readline", "assert", "querystring")
                if ($imp -in $nodeBuiltins) { continue }
                if ($depContent -notmatch [regex]::Escape($imp)) {
                  $a9Failures += "$cf imports '$imp' not found in $depFile"
                }
              }
              "javascript" {
                if ($imp.StartsWith(".") -or $imp.StartsWith("/")) { continue }
                $nodeBuiltins = @("fs", "path", "http", "https", "url", "util", "os",
                  "stream", "crypto", "events", "buffer", "child_process", "net")
                if ($imp -in $nodeBuiltins) { continue }
                if ($depContent -notmatch [regex]::Escape($imp)) {
                  $a9Failures += "$cf imports '$imp' not found in $depFile"
                }
              }
            }
          }
        }

        if ($a9Failures.Count -gt 0) {
          $results["A9"] = "FAIL — $($a9Failures -join '; ')"
          $anyFail = $true
        } else {
          $results["A9"] = "PASS — All imports in changed files have declared dependencies."
        }
      }
    }
  } catch {
    $results["A9"] = "FAIL — Error checking dependencies: $_"
    $anyFail = $true
  }

  # ── W1: No secrets in diff ────────────────────────────────────────────

  try {
    $diffContent = & git diff --cached 2>&1
    $diffContentUnstaged = & git diff 2>&1
    $allDiff = ""
    if ($diffContent)         { $allDiff += ($diffContent -join "`n") }
    if ($diffContentUnstaged) { $allDiff += "`n" + ($diffContentUnstaged -join "`n") }

    $secretPatterns = @('sk-', 'AKIA', '-----BEGIN', 'password=', 'secret=', 'token=')
    $found = @()
    foreach ($sp in $secretPatterns) {
      if ($allDiff -match [regex]::Escape($sp)) {
        $found += $sp
      }
    }

    if ($found.Count -gt 0) {
      $warnings["W1"] = "WARN — Potential secrets found: $($found -join ', ')"
    } else {
      $warnings["W1"] = "PASS — No secret patterns detected."
    }
  } catch {
    $warnings["W1"] = "WARN — Error scanning for secrets: $_"
  }

  # ── W2: Audit ledger integrity ────────────────────────────────────────

  try {
    if (-not (Test-Path $auditLedger)) {
      $warnings["W2"] = "WARN — audit_ledger.md does not exist yet."
    } elseif ((Get-Item $auditLedger).Length -eq 0) {
      $warnings["W2"] = "WARN — audit_ledger.md is empty."
    } else {
      $warnings["W2"] = "PASS — audit_ledger.md exists and is non-empty."
    }
  } catch {
    $warnings["W2"] = "WARN — Error checking audit ledger: $_"
  }

  # ── W3: Physics route coverage ────────────────────────────────────────

  try {
    if (-not (Test-Path $physicsYaml)) {
      $warnings["W3"] = "WARN — physics.yaml not found."
    } else {
      $yamlContent = Get-Content $physicsYaml
      $physicsPaths = $yamlContent |
        Where-Object { $_ -match '^\s{2}/[^:]+:' } |
        ForEach-Object { ($_ -replace ':\s*$', '').Trim() }

      # Attempt to find router/handler directory from forge.json or common conventions
      $routerDirs = @()
      if (Test-Path $forgeJson) {
        $forge = Get-Content $forgeJson -Raw | ConvertFrom-Json
        switch ($forge.backend.language) {
          "python" { $routerDirs = @(Join-Path $root "app/api/routers") }
          "typescript" { $routerDirs = @((Join-Path $root "src/routes"), (Join-Path $root "src/controllers")) }
          "go" { $routerDirs = @((Join-Path $root "handlers"), (Join-Path $root "api")) }
        }
      } else {
        # Fallback: check common paths
        $routerDirs = @(
          (Join-Path $root "app/api/routers"),
          (Join-Path $root "src/routes"),
          (Join-Path $root "handlers")
        )
      }

      $routerDir = $routerDirs | Where-Object { Test-Path $_ } | Select-Object -First 1

      if (-not $routerDir) {
        $warnings["W3"] = "WARN — No router/handler directory found."
      } else {
        $routerFiles = (Get-ChildItem -Path $routerDir -File).Name |
          Where-Object { $_ -ne "__init__.py" -and $_ -ne "__pycache__" }

        $uncovered = @()
        foreach ($p in $physicsPaths) {
          if ($p -eq "/" -or $p -match '/static/') { continue }
          $segment = ($p -split '/')[1]
          if (-not $segment) { continue }

          # Determine expected file based on language
          $expectedFiles = @("$segment.py", "$segment.ts", "$segment.js", "$segment.go")
          $found = $false
          foreach ($ef in $expectedFiles) {
            if ($ef -in $routerFiles) { $found = $true; break }
          }
          if (-not $found) {
            $uncovered += "$p (expected handler for '$segment')"
          }
        }

        if ($uncovered.Count -gt 0) {
          $warnings["W3"] = "WARN — Uncovered routes: $($uncovered -join '; ')"
        } else {
          $warnings["W3"] = "PASS — All physics paths have corresponding handler files."
        }
      }
    }
  } catch {
    $warnings["W3"] = "WARN — Error checking physics coverage: $_"
  }

  # ── Build output ──────────────────────────────────────────────────────

  $overall = if ($anyFail) { "FAIL" } else { "PASS" }

  $output = @"
=== AUDIT SCRIPT RESULT ===
Timestamp: $timestamp
Phase: $Phase
Claimed files: $($claimed -join ', ')

A1 Scope compliance:       $($results["A1"])
A2 Minimal-diff:           $($results["A2"])
A3 Evidence completeness:  $($results["A3"])
A4 Boundary compliance:    $($results["A4"])
A5 Diff Log Gate:          $($results["A5"])
A6 Authorization Gate:     $($results["A6"])
A7 Verification order:     $($results["A7"])
A8 Test gate:              $($results["A8"])
A9 Dependency gate:        $($results["A9"])

W1 No secrets in diff:     $($warnings["W1"])
W2 Audit ledger integrity: $($warnings["W2"])
W3 Physics route coverage: $($warnings["W3"])

Overall: $overall
=== END AUDIT SCRIPT RESULT ===
"@

  Write-Output $output

  # ── Append to audit ledger ─────────────────────────────────────────────

  $iteration = 1
  if (Test-Path $auditLedger) {
    $ledgerText = Get-Content $auditLedger -Raw
    $iterMatches = [regex]::Matches($ledgerText, '(?m)^## Audit Entry:.*Iteration (\d+)')
    if ($iterMatches.Count -gt 0) {
      $lastIter = [int]$iterMatches[$iterMatches.Count - 1].Groups[1].Value
      $iteration = $lastIter + 1
    }
  }

  $outcome = if ($anyFail) { "FAIL" } else { "SIGNED-OFF (awaiting AUTHORIZED)" }

  $fixPlan = ""
  if ($anyFail) {
    $fixPlan = "`n### Fix Plan (FAIL items)`n"
    foreach ($key in $results.Keys) {
      if ($results[$key] -match '^FAIL') {
        $fixPlan += "- $key`: $($results[$key])`n"
      }
    }
  }

  $checklist = @"

### Checklist
- A1 Scope compliance:      $($results["A1"])
- A2 Minimal-diff:          $($results["A2"])
- A3 Evidence completeness: $($results["A3"])
- A4 Boundary compliance:   $($results["A4"])
- A5 Diff Log Gate:         $($results["A5"])
- A6 Authorization Gate:    $($results["A6"])
- A7 Verification order:    $($results["A7"])
- A8 Test gate:             $($results["A8"])
- A9 Dependency gate:       $($results["A9"])
"@

  $ledgerEntry = @"

---
## Audit Entry: $Phase — Iteration $iteration
Timestamp: $timestamp
AEM Cycle: $Phase
Outcome: $outcome
$checklist
$fixPlan
### Files Changed
- $($claimed -join "`n- ")

### Notes
W1: $($warnings["W1"])
W2: $($warnings["W2"])
W3: $($warnings["W3"])
"@

  if (-not (Test-Path $auditLedger)) {
    $header = @"
# Audit Ledger — Forge AEM
Append-only record of all Internal Audit Pass results.
Do not overwrite or truncate this file.
"@
    New-Item -Path $auditLedger -ItemType File -Force | Out-Null
    Set-Content -Path $auditLedger -Value $header -Encoding UTF8
    Info "Created audit_ledger.md."
  }

  Add-Content -Path $auditLedger -Value $ledgerEntry -Encoding UTF8
  Info "Appended audit entry (Iteration $iteration, Outcome: $outcome)."

  # ── Exit ───────────────────────────────────────────────────────────────

  if ($anyFail) {
    exit 1
  } else {
    exit 0
  }

} catch {
  Err "SCRIPT ERROR: $_"
  Err $_.ScriptStackTrace
  exit 2
}
