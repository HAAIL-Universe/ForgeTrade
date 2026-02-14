<#
.SYNOPSIS
    Scans a Forge-managed project and produces a human-readable setup checklist.
    Tells the user what credentials, services, and config they need to go live.

.DESCRIPTION
    Run this after the build is complete. It reads forge.json, .env.example, and
    the dependency manifest to figure out what external services, API keys,
    database connections, and other setup steps the user needs to complete.

.EXAMPLE
    pwsh -File .\scripts\setup_checklist.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Locate project root ──────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Root = Split-Path -Parent $ScriptDir

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  PROJECT SETUP CHECKLIST" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── Read forge.json ──────────────────────────────────────────────────
$ForgeFile = Join-Path $Root "forge.json"
$forge = $null
if (Test-Path $ForgeFile) {
    $forge = Get-Content $ForgeFile -Raw | ConvertFrom-Json
    Write-Host "Project:  $($forge.project_name)" -ForegroundColor White
    Write-Host "Stack:    $($forge.backend.language) backend" -ForegroundColor White
    if ($forge.PSObject.Properties["frontend"] -and $forge.frontend.enabled) {
        Write-Host "Frontend: enabled ($($forge.frontend.framework))" -ForegroundColor White
    }
    Write-Host ""
} else {
    Write-Host "[!] forge.json not found at project root." -ForegroundColor Yellow
    Write-Host "    This script works best after Phase 0 (Genesis) is complete." -ForegroundColor Yellow
    Write-Host ""
}

$sections = @()
$totalItems = 0

# ── 1. Environment Variables (from .env.example) ────────────────────
$EnvExample = Join-Path $Root ".env.example"
if (Test-Path $EnvExample) {
    $envLines = Get-Content $EnvExample | Where-Object {
        $_ -match "^\s*[A-Z_][A-Z0-9_]*\s*=" -and $_ -notmatch "^\s*#"
    }
    $envVars = @()
    foreach ($line in $envLines) {
        $parts = $line -split "=", 2
        $varName = $parts[0].Trim()
        $varValue = if ($parts.Length -gt 1) { $parts[1].Trim() } else { "" }
        $envVars += @{ Name = $varName; Example = $varValue }
    }

    if ($envVars.Count -gt 0) {
        $section = @{
            Title = "ENVIRONMENT VARIABLES"
            Icon  = [char]0x1F511   # key emoji fallback
            Items = @()
        }

        $section.Items += "Copy .env.example to .env at the project root:"
        $section.Items += "  cp .env.example .env"
        $section.Items += ""
        $section.Items += "Then fill in the following values:"
        $section.Items += ""

        foreach ($v in $envVars) {
            $hint = ""
            $name = $v.Name

            # Categorize by name pattern
            switch -Regex ($name) {
                "DATABASE_URL|DB_URL|DB_HOST|DB_NAME|DB_USER|DB_PASS" {
                    $hint = "(database connection)"
                }
                "JWT_SECRET|JWT_AUDIENCE|JWT_ISSUER|JWKS_URL|AUTH0|SUPABASE_KEY|SUPABASE_URL" {
                    $hint = "(authentication)"
                }
                "OPENAI_API_KEY|ANTHROPIC_API_KEY|LLM_MODEL|LLM_API_KEY" {
                    $hint = "(AI / LLM service)"
                }
                "STRIPE|PAYMENT|BILLING" {
                    $hint = "(payment service)"
                }
                "SMTP|EMAIL|SENDGRID|MAILGUN|RESEND" {
                    $hint = "(email service)"
                }
                "AWS|S3_BUCKET|AZURE|GCP|CLOUD" {
                    $hint = "(cloud service)"
                }
                "REDIS|CACHE" {
                    $hint = "(cache / Redis)"
                }
                "SECRET_KEY|APP_SECRET|SESSION_SECRET" {
                    $hint = "(app secret — generate a random string)"
                }
                "PORT|HOST|BASE_URL|APP_URL|CORS" {
                    $hint = "(app configuration)"
                }
                default {
                    $hint = ""
                }
            }

            $example = if ($v.Example -and $v.Example -ne '""' -and $v.Example -ne "''") {
                "  example: $($v.Example)"
            } else { "" }

            $section.Items += "  - $name $hint"
            if ($example) { $section.Items += "    $example" }
        }

        $totalItems += $envVars.Count
        $sections += $section
    }
} else {
    $sections += @{
        Title = "ENVIRONMENT VARIABLES"
        Items = @("[!] No .env.example found. Check Contracts/stack.md for required variables.")
    }
}

# ── 2. Database ──────────────────────────────────────────────────────
$needsDB = $false
$dbEngine = "unknown"

# Check forge.json
if ($forge -and $forge.PSObject.Properties["backend"]) {
    $depFile = $forge.backend.dependency_file
    if ($depFile) {
        $depPath = Join-Path $Root $depFile
        if (Test-Path $depPath) {
            $depContent = Get-Content $depPath -Raw
            if ($depContent -match "psycopg|asyncpg|pg8000|sqlalchemy|prisma|mysql|sqlite|sequelize|typeorm|knex|drizzle|database/sql|gorm") {
                $needsDB = $true
            }
            if ($depContent -match "psycopg|asyncpg|pg8000") { $dbEngine = "PostgreSQL" }
            elseif ($depContent -match "mysql") { $dbEngine = "MySQL" }
            elseif ($depContent -match "sqlite") { $dbEngine = "SQLite" }
            elseif ($depContent -match "prisma") { $dbEngine = "Check prisma schema" }
        }
    }
}

# Fallback: check common dependency files
if (-not $needsDB) {
    $reqTxt = Join-Path $Root "requirements.txt"
    $pkgJson = Join-Path $Root "package.json"
    $goMod = Join-Path $Root "go.mod"

    foreach ($f in @($reqTxt, $pkgJson, $goMod)) {
        if (Test-Path $f) {
            $content = Get-Content $f -Raw
            if ($content -match "psycopg|asyncpg|pg8000") { $needsDB = $true; $dbEngine = "PostgreSQL" }
            elseif ($content -match "mysql2?[^a-z]") { $needsDB = $true; $dbEngine = "MySQL" }
            elseif ($content -match "sqlite") { $needsDB = $true; $dbEngine = "SQLite" }
            elseif ($content -match "prisma|sequelize|typeorm|knex|drizzle") { $needsDB = $true; $dbEngine = "Check ORM config" }
            elseif ($content -match "database/sql|gorm|pgx") { $needsDB = $true; $dbEngine = "PostgreSQL (likely)" }
        }
    }
}

if ($needsDB) {
    $dbSection = @{
        Title = "DATABASE"
        Items = @(
            "This project uses $dbEngine.",
            "",
            "You need to:",
            "  1. Set up a $dbEngine instance (local or hosted)",
            "  2. Create a database for the project",
            "  3. Set the connection string in .env (usually DATABASE_URL)"
        )
    }

    # Check for migrations
    $migrationDirs = @("db/migrations", "migrations", "prisma/migrations", "alembic/versions")
    foreach ($mDir in $migrationDirs) {
        $mPath = Join-Path $Root $mDir
        if (Test-Path $mPath) {
            $dbSection.Items += ""
            $dbSection.Items += "  Migrations found in: $mDir"
            $dbSection.Items += "  Run migrations after setting up the database."
            break
        }
    }

    $totalItems++
    $sections += $dbSection
}

# ── 3. Authentication ────────────────────────────────────────────────
$needsAuth = $false
$authType = ""

# Scan env vars for auth hints
if (Test-Path $EnvExample) {
    $envRaw = Get-Content $EnvExample -Raw
    if ($envRaw -match "JWT_SECRET|JWT_AUDIENCE|JWKS_URL|JWT_ISSUER") {
        $needsAuth = $true; $authType = "JWT"
    }
    if ($envRaw -match "AUTH0") {
        $needsAuth = $true; $authType = "Auth0"
    }
    if ($envRaw -match "SUPABASE") {
        $needsAuth = $true; $authType = "Supabase"
    }
    if ($envRaw -match "CLERK") {
        $needsAuth = $true; $authType = "Clerk"
    }
}

if ($needsAuth) {
    $authSection = @{
        Title = "AUTHENTICATION ($authType)"
        Items = @(
            "This project uses $authType for authentication.",
            ""
        )
    }
    switch ($authType) {
        "JWT" {
            $authSection.Items += "You need to:"
            $authSection.Items += "  1. Decide on a JWT provider (Auth0, Supabase, self-signed, etc.)"
            $authSection.Items += "  2. Set the JWT-related variables in .env"
            $authSection.Items += "  3. If using JWKS, ensure the JWKS URL is publicly reachable"
        }
        "Auth0" {
            $authSection.Items += "You need to:"
            $authSection.Items += "  1. Create an Auth0 account and application"
            $authSection.Items += "  2. Set AUTH0_DOMAIN, AUTH0_AUDIENCE, etc. in .env"
        }
        "Supabase" {
            $authSection.Items += "You need to:"
            $authSection.Items += "  1. Create a Supabase project"
            $authSection.Items += "  2. Set SUPABASE_URL and SUPABASE_KEY in .env"
        }
        default {
            $authSection.Items += "Check .env.example for the required auth variables."
        }
    }
    $totalItems++
    $sections += $authSection
}

# ── 4. AI / LLM Services ────────────────────────────────────────────
$needsLLM = $false
$llmProvider = ""

if (Test-Path $EnvExample) {
    $envRaw = Get-Content $EnvExample -Raw
    if ($envRaw -match "OPENAI_API_KEY|OPENAI_ORG") {
        $needsLLM = $true; $llmProvider = "OpenAI"
    }
    if ($envRaw -match "ANTHROPIC_API_KEY") {
        $needsLLM = $true; $llmProvider = "Anthropic"
    }
    if ($envRaw -match "LLM_API_KEY|LLM_MODEL") {
        $needsLLM = $true; $llmProvider = if ($llmProvider) { $llmProvider } else { "LLM provider" }
    }
}

# Also check dependencies
$depFiles = @("requirements.txt", "package.json", "go.mod")
foreach ($df in $depFiles) {
    $dfPath = Join-Path $Root $df
    if (Test-Path $dfPath) {
        $dfContent = Get-Content $dfPath -Raw
        if ($dfContent -match "openai") { $needsLLM = $true; if (-not $llmProvider) { $llmProvider = "OpenAI" } }
        if ($dfContent -match "anthropic") { $needsLLM = $true; if (-not $llmProvider) { $llmProvider = "Anthropic" } }
    }
}

if ($needsLLM) {
    $llmSection = @{
        Title = "AI / LLM ($llmProvider)"
        Items = @(
            "This project integrates with $llmProvider.",
            "",
            "You need to:",
            "  1. Create an account with $llmProvider"
        )
    }
    if ($llmProvider -eq "OpenAI") {
        $llmSection.Items += "  2. Generate an API key at https://platform.openai.com/api-keys"
        $llmSection.Items += "  3. Set OPENAI_API_KEY in .env"
        $llmSection.Items += "  4. Note: API usage is billed per token"
    } elseif ($llmProvider -eq "Anthropic") {
        $llmSection.Items += "  2. Generate an API key at https://console.anthropic.com/"
        $llmSection.Items += "  3. Set ANTHROPIC_API_KEY in .env"
        $llmSection.Items += "  4. Note: API usage is billed per token"
    } else {
        $llmSection.Items += "  2. Set the API key in .env (check .env.example for the variable name)"
    }
    $totalItems++
    $sections += $llmSection
}

# ── 5. Other External Services ───────────────────────────────────────
$externalServices = @()

if (Test-Path $EnvExample) {
    $envRaw = Get-Content $EnvExample -Raw

    if ($envRaw -match "STRIPE|PAYMENT") {
        $externalServices += @{ Name = "Stripe / Payment"; Hint = "Set up a Stripe account and add API keys to .env" }
    }
    if ($envRaw -match "SMTP|SENDGRID|MAILGUN|RESEND|EMAIL_API") {
        $externalServices += @{ Name = "Email service"; Hint = "Set up an email provider and add credentials to .env" }
    }
    if ($envRaw -match "REDIS|CACHE_URL") {
        $externalServices += @{ Name = "Redis / Cache"; Hint = "Set up a Redis instance and add the URL to .env" }
    }
    if ($envRaw -match "S3_BUCKET|AWS_ACCESS|AWS_SECRET") {
        $externalServices += @{ Name = "AWS S3"; Hint = "Set up an S3 bucket and add AWS credentials to .env" }
    }
    if ($envRaw -match "TWILIO|SMS") {
        $externalServices += @{ Name = "Twilio / SMS"; Hint = "Set up a Twilio account and add credentials to .env" }
    }
    if ($envRaw -match "GOOGLE_MAPS|MAPS_API") {
        $externalServices += @{ Name = "Google Maps"; Hint = "Get a Maps API key and add it to .env" }
    }
    if ($envRaw -match "SENTRY|ERROR_TRACKING") {
        $externalServices += @{ Name = "Sentry / Error tracking"; Hint = "Set up a Sentry project and add DSN to .env" }
    }
}

if ($externalServices.Count -gt 0) {
    $extSection = @{
        Title = "EXTERNAL SERVICES"
        Items = @()
    }
    foreach ($svc in $externalServices) {
        $extSection.Items += "  - $($svc.Name): $($svc.Hint)"
    }
    $totalItems += $externalServices.Count
    $sections += $extSection
}

# ── 6. Dependencies ─────────────────────────────────────────────────
$depSection = @{
    Title = "DEPENDENCIES"
    Items = @()
}

$lang = if ($forge) { $forge.backend.language } else { "" }

switch -Regex ($lang) {
    "python|Python" {
        $venvPath = if ($forge -and $forge.backend.PSObject.Properties["venv_path"]) { $forge.backend.venv_path } else { ".venv" }
        $depFile = if ($forge) { $forge.backend.dependency_file } else { "requirements.txt" }
        $depSection.Items += "Python project. Install dependencies:"
        $depSection.Items += ""
        $depSection.Items += "  python -m venv $venvPath"
        if ($env:OS -match "Windows") {
            $depSection.Items += "  $venvPath\Scripts\activate"
        } else {
            $depSection.Items += "  source $venvPath/bin/activate"
        }
        $depSection.Items += "  pip install -r $depFile"
    }
    "typescript|TypeScript|javascript|JavaScript" {
        $depSection.Items += "Node.js project. Install dependencies:"
        $depSection.Items += ""
        $depSection.Items += "  npm install"
    }
    "go|Go" {
        $depSection.Items += "Go project. Install dependencies:"
        $depSection.Items += ""
        $depSection.Items += "  go mod download"
    }
    default {
        # Try to detect from files
        if (Test-Path (Join-Path $Root "requirements.txt")) {
            $depSection.Items += "Python project detected. Run: pip install -r requirements.txt"
        } elseif (Test-Path (Join-Path $Root "package.json")) {
            $depSection.Items += "Node.js project detected. Run: npm install"
        } elseif (Test-Path (Join-Path $Root "go.mod")) {
            $depSection.Items += "Go project detected. Run: go mod download"
        } else {
            $depSection.Items += "Could not detect package manager. Check the project README."
        }
    }
}

# Frontend deps
if ($forge -and $forge.PSObject.Properties["frontend"] -and $forge.frontend.enabled) {
    $feDir = if ($forge.frontend.PSObject.Properties["dir"]) { $forge.frontend.dir } else { "web" }
    $depSection.Items += ""
    $depSection.Items += "Frontend ($feDir/):"
    $depSection.Items += "  cd $feDir && npm install"
}

$totalItems++
$sections += $depSection

# ── 7. First Run ─────────────────────────────────────────────────────
$runSection = @{
    Title = "FIRST RUN"
    Items = @(
        "After completing the above:"
        ""
    )
}

$stepNum = 1
if ($needsDB) {
    $runSection.Items += "  $stepNum. Run database migrations"
    $stepNum++
}
$runSection.Items += "  $stepNum. Copy .env.example to .env and fill in all values"
$stepNum++

# Detect start command
$startCmd = ""
if ($forge) {
    switch -Regex ($forge.backend.language) {
        "python|Python" {
            $entry = if ($forge.backend.PSObject.Properties["entry_module"]) { $forge.backend.entry_module } else { "app.main" }
            $startCmd = "uvicorn ${entry}:app --reload"
        }
        "typescript|TypeScript|javascript|JavaScript" {
            $startCmd = "npm run dev"
        }
        "go|Go" {
            $startCmd = "go run ."
        }
    }
}
if (-not $startCmd -and (Test-Path (Join-Path $Root "scripts/run_local.ps1"))) {
    $startCmd = "pwsh -File scripts/run_local.ps1"
}

if ($startCmd) {
    $runSection.Items += "  $stepNum. Start the app: $startCmd"
} else {
    $runSection.Items += "  $stepNum. Start the app (check README or scripts/ for the run command)"
}

$sections += $runSection

# ── Output ───────────────────────────────────────────────────────────
foreach ($s in $sections) {
    Write-Host "--------------------------------------------" -ForegroundColor DarkGray
    Write-Host "  $($s.Title)" -ForegroundColor Yellow
    Write-Host "--------------------------------------------" -ForegroundColor DarkGray
    foreach ($line in $s.Items) {
        Write-Host $line
    }
    Write-Host ""
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  CHECKLIST COMPLETE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "All environment variables go in .env (copy from .env.example)." -ForegroundColor White
Write-Host "See Contracts/stack.md for full tech stack details." -ForegroundColor White
Write-Host ""
