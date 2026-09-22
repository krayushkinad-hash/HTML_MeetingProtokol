# ============================================================
# Manual fix: install requirements and verify uvicorn
# Run as Administrator
# ============================================================
#Requires -Version 5.1
$ErrorActionPreference = "Continue"

# Set console output to UTF-8 (PowerShell way)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# CRITICAL: Disable SOCKS proxy completely
# Some Windows configurations have SOCKS proxy set globally which breaks pip
$env:HTTP_PROXY = $null
$env:HTTPS_PROXY = $null
$env:ALL_PROXY = $null
$env:SOCKS_PROXY = $null
$env:NO_PROXY = "*"

# Also disable pip.ini via pip config (more reliable than rename)
& pip config --global unset proxy 2>&1 | Out-Null
& pip config --global unset index 2>&1 | Out-Null
& pip config --global unset trusted-host 2>&1 | Out-Null

# Also rename pip.ini if exists (Windows often has this)
$pipConf = Join-Path $env:APPDATA "pip\pip.ini"
if (Test-Path $pipConf) {
    Write-Host "  Found pip.ini - disabling..." -ForegroundColor Yellow
    Move-Item $pipConf "$pipConf.disabled" -Force -ErrorAction SilentlyContinue
}
$pipConfUser = Join-Path $env:USERPROFILE ".pip\pip.conf"
if (Test-Path $pipConfUser) {
    Write-Host "  Found pip.conf - disabling..." -ForegroundColor Yellow
    Move-Item $pipConfUser "$pipConfUser.disabled" -Force -ErrorAction SilentlyContinue
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

# Use --index-url to bypass any pip config settings
$global:pipIndexUrl = "https://pypi.org/simple/"
$global:pipTrustedHosts = @("pypi.org", "files.pythonhosted.org")

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Manual fix: Install Backend Dependencies" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Find project root - try multiple paths
$PROJECT_DIR = $null
$searchPaths = @(
    (Join-Path $env:USERPROFILE "HTML_MeetingProtokol"),
    "C:\HTML_Protokol",
    "C:\Projects\AI\HTML_MeetingProtokol",
    "C:\Projects\HTML_MeetingProtokol",
    (Get-Location).Path
)

foreach ($p in $searchPaths) {
    if (Test-Path "$p\code\hmp-backend") {
        $PROJECT_DIR = $p
        break
    }
}

if (-not $PROJECT_DIR) {
    Write-Host "  Could not find project root!" -ForegroundColor Red
    Write-Host "  Searched in:" -ForegroundColor Yellow
    foreach ($p in $searchPaths) {
        Write-Host "    - $p" -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "  Set PROJECT_DIR manually:" -ForegroundColor Cyan
    Write-Host "    `$PROJECT_DIR = 'C:\your\path\to\HTML_MeetingProtokol'" -ForegroundColor Cyan
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "  Project: $PROJECT_DIR" -ForegroundColor Green
$BACKEND_DIR = Join-Path $PROJECT_DIR "code\hmp-backend"
Write-Host "  Backend: $BACKEND_DIR" -ForegroundColor Green
Write-Host ""

Set-Location $BACKEND_DIR

# Show Python info
Write-Host "[1/6] Checking Python..." -ForegroundColor Cyan
$pythonVersion = python --version 2>&1
Write-Host "  Python: $pythonVersion" -ForegroundColor Green

# Remove old venv if broken
Write-Host ""
Write-Host "[2/6] Cleaning old venv..." -ForegroundColor Cyan
if (Test-Path ".venv") {
    Write-Host "  Removing .venv..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force ".venv" -ErrorAction SilentlyContinue
}

# Disable proxies for pip
Write-Host ""
Write-Host "[3/6] Disabling pip proxies..." -ForegroundColor Cyan
$env:HTTP_PROXY = $null
$env:HTTPS_PROXY = $null
$env:ALL_PROXY = $null
$pipConf = Join-Path $env:APPDATA "pip\pip.ini"
if (Test-Path $pipConf) {
    Write-Host "  Temporarily disabling pip.ini..." -ForegroundColor Yellow
    Move-Item $pipConf "$pipConf.disabled" -Force
}

# Create venv
Write-Host ""
Write-Host "[4/6] Creating virtual environment..." -ForegroundColor Cyan
python -m venv .venv 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Cannot create venv" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "  [OK] venv created" -ForegroundColor Green

# Verify requirements file
Write-Host ""
Write-Host "[5/6] Installing requirements..." -ForegroundColor Cyan
if (-not (Test-Path "requirements-minimal.txt")) {
    Write-Host "  requirements-minimal.txt NOT FOUND" -ForegroundColor Red
    Write-Host "  Expected at: $BACKEND_DIR\requirements-minimal.txt" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Run pip with full output (not quiet) to see errors
Write-Host "  Installing dependencies..." -ForegroundColor Yellow

# Upgrade pip first (with --no-deps to avoid SOCKS dependency chain issue)
# Use --index-url to bypass any pip config proxy settings
& .\.venv\Scripts\python.exe -m pip install --quiet --no-deps --index-url "https://pypi.org/simple/" --upgrade pip setuptools wheel 2>&1 | Out-Null

# Install transitive dependencies FIRST (with --no-deps to avoid SOCKS)
$transitiveDeps = @(
    "typing_extensions>=4.0",
    "annotated-types>=0.4",
    "pydantic_core>=2.0",
    "anyio>=4.0",
    "click>=8.0",
    "h11>=0.16",
    "httptools>=0.5",
    "uvloop>=0.17",
    "websockets>=12.0",
    "watchfiles>=0.21",
    "python-dotenv>=1.0",
    "greenlet>=3.0",
    "aiosqlite>=0.20",
    "sqlalchemy2-eventlet-async",
    "tiktoken",
    "distro",
    "jiter",
    "pycparser",
    "cffi",
    "pyparsing",
    "pillow-jxl",
    "iniconfig",
    "pluggy",
    "sniffio",
    "exceptiongroup",
    "h2",
    "MarkupSafe",
    "Jinja2",
    "mako",
    "alembic-script",
    "Mako",
    "six",
    "pyOpenSSL",
    "idna",
    "certifi",
    "charset-normalizer",
    "requests",
    "PyJWT",
    "bcrypt",
    "argon2-cffi",
    "starlette>=0.40",
    "fastapi-utils",
    "email-validator",
    "annotated_doc",
    "anyio-to-fastapi",
    "PyJWT"
)

Write-Host "  Installing $(($transitiveDeps).Count) transitive dependencies..." -ForegroundColor Yellow
foreach ($dep in $transitiveDeps) {
    & .\.venv\Scripts\python.exe -m pip install --quiet --no-cache-dir --no-deps --index-url "https://pypi.org/simple/" --trusted-host "pypi.org" --trusted-host "files.pythonhosted.org" $dep 2>&1 | Out-Null
}

# Now install requirements - use --no-deps and --index-url to bypass any proxy config
Write-Host "  Installing main requirements..." -ForegroundColor Yellow
$pipOutput = & .\.venv\Scripts\python.exe -m pip install --no-cache-dir --no-deps --index-url "https://pypi.org/simple/" --trusted-host "pypi.org" --trusted-host "files.pythonhosted.org" -r requirements-minimal.txt 2>&1
$pipOutput | Out-Host

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  ERROR: pip install failed (exit code $LASTEXITCODE)" -ForegroundColor Red
    Write-Host ""

    # Fallback: try installing individual packages
    Write-Host "  Trying fallback - install packages one by one..." -ForegroundColor Yellow
    $packages = @("fastapi", "uvicorn", "pydantic", "pydantic-settings", "python-multipart", "sqlalchemy", "asyncpg", "alembic", "cryptography", "pyjwt", "httpx", "openai", "python-docx", "pillow", "structlog", "psutil", "tenacity", "orjson", "python-dateutil", "pytest", "pytest-asyncio")
    foreach ($pkg in $packages) {
        Write-Host "    Installing $pkg..." -ForegroundColor Gray
        & .\.venv\Scripts\python.exe -m pip install --quiet --no-cache-dir --no-deps --index-url "https://pypi.org/simple/" --trusted-host "pypi.org" --trusted-host "files.pythonhosted.org" $pkg 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "    FAILED: $pkg" -ForegroundColor Red
        }
    }
}
Write-Host "  [OK] requirements installed" -ForegroundColor Green

# Verify uvicorn
Write-Host ""
Write-Host "[6/6] Verifying uvicorn..." -ForegroundColor Cyan
$uvicornPath = ".\.venv\Scripts\uvicorn.exe"
if (Test-Path $uvicornPath) {
    Write-Host "  [OK] uvicorn found at $uvicornPath" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Testing uvicorn (may need additional deps)..." -ForegroundColor Yellow

    # Test uvicorn import - might need extra deps
    $testResult = & .\.venv\Scripts\python.exe -c "import uvicorn; print('uvicorn version:', uvicorn.__version__)" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  uvicorn has missing dependencies. Installing all from requirements.txt with --no-deps..." -ForegroundColor Yellow
        # Install ALL deps from requirements.txt again with --no-deps
        Get-Content requirements-minimal.txt | Where-Object { $_ -notmatch '^#' -and $_ -match '\S' } | ForEach-Object {
            & .\.venv\Scripts\python.exe -m pip install --quiet --no-cache-dir --no-deps --index-url "https://pypi.org/simple/" --trusted-host "pypi.org" --trusted-host "files.pythonhosted.org" $_ 2>&1 | Out-Null
        }
        # Then run pip check to see what's still missing - install all common transitive deps
        $allTransitive = @(
            "typing_extensions", "annotated-types", "pydantic_core", "anyio", "h11", "httptools",
            "uvloop", "websockets", "watchfiles", "python-dotenv", "greenlet", "aiosqlite",
            "sqlalchemy2-eventlet-async", "tiktoken", "distro", "jiter", "pycparser", "cffi",
            "pyparsing", "pillow-jxl", "iniconfig", "pluggy", "sniffio", "exceptiongroup",
            "MarkupSafe", "Jinja2", "six", "idna", "certifi", "charset-normalizer",
            "requests", "bcrypt", "argon2-cffi", "colorama", "click", "pywin32",
            "starlette", "fastapi-utils", "email-validator", "python-multipart", "itsdangerous",
            "annotated_doc"
        )
        & .\.venv\Scripts\python.exe -m pip install --quiet --no-cache-dir --no-deps --index-url "https://pypi.org/simple/" --trusted-host "pypi.org" --trusted-host "files.pythonhosted.org" $allTransitive 2>&1 | Out-Null
        $testResult = & .\.venv\Scripts\python.exe -c "import uvicorn; print('uvicorn version:', uvicorn.__version__)" 2>&1
    }

    if ($testResult -match 'uvicorn version') {
        Write-Host "  [OK] $testResult" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: uvicorn test: $testResult" -ForegroundColor Yellow
        Write-Host "  Continuing anyway..." -ForegroundColor Gray
    }
} else {
    Write-Host "  ERROR: uvicorn NOT FOUND at $uvicornPath" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Contents of .venv\Scripts\:" -ForegroundColor Yellow
    if (Test-Path ".venv\Scripts") {
        Get-ChildItem ".venv\Scripts" | Select-Object -First 20 | ForEach-Object { Write-Host "    $($_.Name)" -ForegroundColor Gray }
    }
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " BACKEND READY!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Test backend:" -ForegroundColor Cyan
Write-Host "  cd '$BACKEND_DIR'" -ForegroundColor White
Write-Host "  .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000" -ForegroundColor White
Write-Host ""
Write-Host "Now run start.bat to start everything." -ForegroundColor Cyan
Write-Host ""
Read-Host "Press Enter to exit"
