# HTML_MeetingProtokol — Windows PowerShell Deployment Script
# Полное развертывание на Windows 10/11: Docker + PostgreSQL + Python + ML модели
#
# Использование:
#   1. Скачайте проект в C:\Users\YourName\HTML_MeetingProtokol\
#   2. Откройте PowerShell от Администратора
#   3. cd C:\Users\YourName\HTML_MeetingProtokol
#   4. powershell -ExecutionPolicy Bypass -File .\deploy-windows.ps1
#

#Requires -Version 5.1
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ============================================================
# Цветной вывод
# ============================================================
function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] " -ForegroundColor Cyan -NoNewline
    Write-Host $Message -ForegroundColor White
}
function Write-OK {
    param([string]$Message)
    Write-Host "  [OK] " -ForegroundColor Green -NoNewline
    Write-Host $Message
}
function Write-Warn {
    param([string]$Message)
    Write-Host "  [WARN] " -ForegroundColor Yellow -NoNewline
    Write-Host $Message
}
function Write-Err {
    param([string]$Message)
    Write-Host "  [ERROR] " -ForegroundColor Red -NoNewline
    Write-Host $Message
}

# ============================================================
# Шаг 1/8: Проверка prerequisites
# ============================================================
Clear-Host
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " HTML_MeetingProtokol - Windows Deployment" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Инициализируем $PROJECT_DIR ДО проверки зависимостей
# (нужно для скачивания Docker installer, если Docker не найден)
$PROJECT_DIR = Join-Path $env:USERPROFILE "HTML_MeetingProtokol"
if (-not (Test-Path $PROJECT_DIR)) {
    if (Test-Path "C:\HTML_Protokol") {
        $PROJECT_DIR = "C:\HTML_Protokol"
    }
}

Write-Step "Step 1/8: Checking system dependencies..."

$missing = @()

# Docker
$dockerFound = $false
$dockerHints = @()

# Способ 1: через PATH
try {
    $dockerVer = docker --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Docker: $dockerVer"
        $dockerFound = $true
    }
} catch {}

# Способ 2: поискать в стандартных местах
if (-not $dockerFound) {
    $dockerPaths = @(
        "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
        "$env:ProgramFiles\Docker\Docker\bin\docker.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\resources\bin\docker.exe",
        "$env:LOCALAPPDATA\Programs\Docker\Docker\resources\bin\docker.exe"
    )
    foreach ($p in $dockerPaths) {
        if ($p -and (Test-Path $p)) {
            Write-Warn "Docker found at: $p"
            Write-Warn "Add this folder to PATH or run from Docker Desktop terminal"
            $dockerHints += $p
            $dockerFound = $true
            break
        }
    }
}

# Способ 3: проверка процесса Docker Desktop
if (-not $dockerFound) {
    $dockerProc = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
    if ($dockerProc) {
        Write-Warn "Docker Desktop is running but 'docker' command not in PATH"
        Write-Warn "Try: open Docker Desktop, then Settings → Advanced → 'Add to PATH'"
        $dockerFound = $true
    }
}

if (-not $dockerFound) {
    Write-Host ""
    Write-Host "  [INFO] Docker Desktop not detected." -ForegroundColor Yellow

    # Предлагаем установить автоматически
    Write-Host ""
    $choice = Read-Host "  Install Docker Desktop automatically? (y/n)"

    if ($choice -eq 'y' -or $choice -eq 'Y') {
        Write-Host ""
        $wingetPath = $null
        # Поиск winget в стандартных местах (может быть не в PATH)
        $wingetCandidates = @(
            "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe",
            "$env:ProgramFiles\WindowsApps\Microsoft.Winget.Source_*\winget.exe",
            "$env:ProgramFiles\WindowsApps\Microsoft.DesktopAppInstaller_*\winget.exe"
        )
        foreach ($w in $wingetCandidates) {
            if ($w -and (Test-Path $w)) {
                $wingetPath = (Get-ChildItem $w -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
                if ($wingetPath) { break }
            }
        }

        if ($wingetPath) {
            Write-Host "  Found winget at: $wingetPath" -ForegroundColor Green
            Write-Host "  Using winget for installation..." -ForegroundColor Cyan
            & $wingetPath install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements

            if ($LASTEXITCODE -eq 0) {
                Write-OK "Docker Desktop installed via winget"
                Write-Host ""
                Write-Host "  IMPORTANT STEPS:" -ForegroundColor Yellow
                Write-Host "    1. RESTART your computer (required for Hyper-V/WSL2)" -ForegroundColor Yellow
                Write-Host "    2. Open Docker Desktop after restart" -ForegroundColor Yellow
                Write-Host "    3. Wait for 'Engine running' notification in system tray" -ForegroundColor Yellow
                Write-Host "    4. Run this script again" -ForegroundColor Yellow
                Write-Host ""
                Read-Host "Press Enter to exit (restart and re-run the script)"
                exit 0
            }
            Write-Host "  winget failed, trying direct download..." -ForegroundColor Yellow
        } else {
            Write-Host "  winget not found in standard locations" -ForegroundColor Yellow
            Write-Host "  Will download Docker Desktop installer directly..." -ForegroundColor Cyan
        }

        $downloadUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
        # Гарантируем, что $PROJECT_DIR определён (Шаг 2 ещё не выполнялся)
        if (-not $PROJECT_DIR) {
            $PROJECT_DIR = Join-Path $env:USERPROFILE "HTML_MeetingProtokol"
        }
        if (-not (Test-Path $PROJECT_DIR)) {
            New-Item -ItemType Directory -Path $PROJECT_DIR | Out-Null
        }
        $installerPath = Join-Path $PROJECT_DIR "DockerDesktopInstaller.exe"

        Write-Host ""
        Write-Host "  Downloading Docker Desktop Installer (~600 MB)..." -ForegroundColor Cyan
        Write-Host "  URL: $downloadUrl" -ForegroundColor Gray
        Write-Host ""

        try {
            # Используем PowerShell Invoke-WebRequest (встроенный, не требует curl)
            Write-Host "  Downloading (may take 3-5 minutes)..."
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing
            $ProgressPreference = 'Continue'

            if ((Test-Path $installerPath) -and ((Get-Item $installerPath).Length -gt 100MB)) {
                Write-OK "Downloaded Docker Desktop Installer"
                Write-Host ""

                # Тихая установка через --quiet
                Write-Host "  Installing Docker Desktop silently (requires Admin)..." -ForegroundColor Cyan
                Write-Host "  Installer path: $installerPath" -ForegroundColor Gray
                Write-Host ""

                $installProcess = Start-Process -FilePath $installerPath -ArgumentList "install", "--quiet", "--accept-license" -Wait -PassThru -NoNewWindow

                if ($installProcess.ExitCode -eq 0) {
                    Write-OK "Docker Desktop installed successfully!"
                    Write-Host ""
                    Write-Host "  IMPORTANT STEPS:" -ForegroundColor Yellow
                    Write-Host "    1. RESTART your computer (required for Hyper-V/WSL2)" -ForegroundColor Yellow
                    Write-Host "    2. Open Docker Desktop after restart" -ForegroundColor Yellow
                    Write-Host "    3. Wait for 'Engine running' notification in system tray" -ForegroundColor Yellow
                    Write-Host "    4. Run this script again" -ForegroundColor Yellow
                    Write-Host ""

                    # Удаляем инсталлятор
                    Remove-Item $installerPath -ErrorAction SilentlyContinue
                    Read-Host "Press Enter to exit (restart and re-run the script)"
                    exit 0
                } else {
                    Write-Err "Installer exit code: $($installProcess.ExitCode)"
                    Write-Host "  Try installing manually by double-clicking: $installerPath" -ForegroundColor Yellow
                    Read-Host "Press Enter to continue (script will exit)"
                    exit 1
                }
            } else {
                Write-Err "Download failed or file too small"
                Write-Host "  Try manually: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
                $missing += "Docker Desktop"
            }
        } catch {
            Write-Err "Download error: $_"
            Write-Host "  Try manually: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
            Write-Host "  Or run separately: powershell -ExecutionPolicy Bypass -File .\install-docker-only.ps1" -ForegroundColor Cyan
            $missing += "Docker Desktop"
        }
    } else {
        Write-Host "  Skipping Docker install." -ForegroundColor Yellow
        Write-Host "  Note: This project needs Docker Desktop for PostgreSQL." -ForegroundColor Yellow
        Write-Host "  Install manually: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
        $missing += "Docker Desktop"
    }
}

# Python
try {
    $pythonVer = python --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Python: $pythonVer"
        # Извлекаем версию для проверки
        if ($pythonVer -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
                Write-Err "Python 3.10+ required, found $major.$minor"
                $missing += "Python 3.10+ (https://www.python.org/downloads/)"
            } elseif ($major -eq 3 -and $minor -eq 10) {
                Write-Warn "Python 3.10 detected. Recommended: 3.11+ (some features may not work)"
            }
        }
    } else {
        $missing += "Python 3.10+ (https://www.python.org/downloads/)"
    }
} catch {
    $missing += "Python 3.10+"
}

# Git (optional)
try {
    $gitVer = git --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Git: $gitVer"
    } else {
        Write-Warn "Git not found (optional)"
    }
} catch {
    Write-Warn "Git not found (optional)"
}

# curl (опционально, есть альтернатива через PowerShell Invoke-WebRequest)
try {
    $null = & curl.exe --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "curl available"
    } else {
        Write-Warn "curl.exe not found (using PowerShell Invoke-WebRequest instead)"
    }
} catch {
    Write-Warn "curl.exe not found (PowerShell will use Invoke-WebRequest)"
}

# PowerShell version (всегда есть, нужна >= 5.1)
$psVersion = $PSVersionTable.PSVersion
if ($psVersion.Major -ge 5) {
    Write-OK "PowerShell: $psVersion"
} else {
    Write-Err "PowerShell 5.1+ required, found $psVersion"
    $missing += "PowerShell 5.1+ (https://aka.ms/powershell)"
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Err "Missing dependencies:"
    foreach ($m in $missing) {
        Write-Host "    - $m" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Install them and run again." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Quick install commands:" -ForegroundColor Cyan
    Write-Host "  winget install -e --id Docker.DockerDesktop" -ForegroundColor White
    Write-Host "  winget install -e --id Python.Python.3.12" -ForegroundColor White
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# ============================================================
# Шаг 2/8: Создание директории
# ============================================================
Write-Step "Step 2/8: Preparing project directory..."

$PROJECT_DIR = Join-Path $env:USERPROFILE "HTML_MeetingProtokol"
if (-not (Test-Path $PROJECT_DIR)) {
    New-Item -ItemType Directory -Path $PROJECT_DIR | Out-Null
    Write-OK "Created: $PROJECT_DIR"
} else {
    Write-OK "Exists: $PROJECT_DIR"
}
Set-Location $PROJECT_DIR

# ============================================================
# Шаг 3/8: Создание .env
# ============================================================
Write-Step "Step 3/8: Creating .env file..."

$envFile = Join-Path $PROJECT_DIR ".env"
if (-not (Test-Path $envFile)) {
    $keyBytes = New-Object byte[] 32
    (New-Object Random).NextBytes($keyBytes)
    $masterKey = [Convert]::ToBase64String($keyBytes)

    # Используем here-string с @"
    $envContent = @"
# Application
APP_NAME=HTML_MeetingProtokol
APP_ENV=development
DEBUG=true
APP_VERSION=1.0.0

# Server
SERVER_HOST=127.0.0.1
SERVER_PORT=8000
SERVER_WORKERS=1

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Database (Docker postgres)
DATABASE_URL=postgresql+asyncpg://hmp:hmp_password@localhost:5432/html_mp
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
DATABASE_ECHO=false

# Encryption (ADR-014)
ENCRYPTION_MASTER_KEY=$masterKey

# File storage
PROTOCOLS_PATH=/data/protocols
MAX_UPLOAD_SIZE_MB=2048
UPLOAD_CHUNK_SIZE_MB=8

# ML Models
WHISPER_MODEL=large-v3
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=float16
PYANNOTE_TOKEN=

# LLM providers (ADR-004)
LLM_PROVIDER=hermes
HERMES_API_KEY=
HERMES_BASE_URL=https://hermes.example.com/v1
GIGACHAT_TOKEN=

# Telegram bot
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_IDS=

# CORS
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# RSS monitoring (NFR QG-7)
RSS_LIMIT_MB=4096
RSS_AUTOPAUSE_THRESHOLD=0.8
RSS_CHECK_INTERVAL_SEC=10
"@
    $envContent | Out-File -FilePath $envFile -Encoding UTF8
    Write-OK "Created .env with new ENCRYPTION_MASTER_KEY"
    Write-Host ""
    Write-Host "  [IMPORTANT] Open .env and fill in:" -ForegroundColor Yellow
    Write-Host "     PYANNOTE_TOKEN   - https://huggingface.co/settings/tokens" -ForegroundColor Yellow
    Write-Host "     HERMES_API_KEY    - for AI features (optional)" -ForegroundColor Yellow
    Write-Host "     GIGACHAT_TOKEN    - Hermes alternative (optional)" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-OK ".env already exists"
}

# ============================================================
# Шаг 4/8: PostgreSQL в Docker
# ============================================================
Write-Step "Step 4/8: Starting PostgreSQL in Docker..."

# Повторная проверка Docker (после возможной перезагрузки)
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    # Поиск в стандартных местах
    $dockerPaths = @(
        "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
        "$env:ProgramFiles\Docker\Docker\bin\docker.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\resources\bin\docker.exe",
        "$env:LOCALAPPDATA\Programs\Docker\Docker\resources\bin\docker.exe"
    )
    foreach ($p in $dockerPaths) {
        if ($p -and (Test-Path $p)) {
            Write-Host "  Docker found at: $p" -ForegroundColor Green
            Write-Host "  Adding to current session PATH..." -ForegroundColor Cyan
            $env:PATH = $env:PATH + ";$(Split-Path $p -Parent)"
            $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
            if ($dockerCmd) { break }
        }
    }
}

if (-not $dockerCmd) {
    Write-Err "Docker still not found!"
    Write-Host ""
    Write-Host "  Possible causes:" -ForegroundColor Yellow
    Write-Host "    1. Docker Desktop not installed" -ForegroundColor Yellow
    Write-Host "    2. Need to RESTART computer after Docker install" -ForegroundColor Yellow
    Write-Host "    3. Docker Desktop not running (open it from Start menu)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Manual start Docker Desktop, wait for 'Engine running'," -ForegroundColor Cyan
    Write-Host "  then run this script again." -ForegroundColor Cyan
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Проверяем что Docker daemon работает
Write-Host "  Checking Docker daemon..."

# Пытаемся запустить Docker Desktop если он есть, но не запущен
$dockerProc = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $dockerProc) {
    # Поиск exe Docker Desktop
    $dockerDesktopPaths = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Programs\Docker\Docker\Docker Desktop.exe"
    )
    $dockerDesktopExe = $null
    foreach ($p in $dockerDesktopPaths) {
        if ($p -and (Test-Path $p)) {
            $dockerDesktopExe = $p
            break
        }
    }

    if ($dockerDesktopExe) {
        Write-Host "  Starting Docker Desktop (this may take 30-60 seconds)..." -ForegroundColor Cyan
        try {
            Start-Process -FilePath $dockerDesktopExe
        } catch {
            Write-Err "Cannot start Docker Desktop: $_"
        }
    } else {
        # Docker Desktop.exe не найден — установка не завершилась
        Write-Err "Docker Desktop executable not found!"
        Write-Host "  Installation may have failed." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  OPTIONS:" -ForegroundColor Cyan
        Write-Host "    1. Reinstall Docker Desktop:" -ForegroundColor Cyan
        Write-Host "       winget install -e --id Docker.DockerDesktop" -ForegroundColor White
        Write-Host ""
        Write-Host "    2. Use SQLite mode (no Docker needed):" -ForegroundColor Cyan
        Write-Host "       Continue with SQLite-only backend" -ForegroundColor White
        Write-Host ""
        $useSqlite = Read-Host "  Continue with SQLite? (y/n)"
        if ($useSqlite -ne 'y' -and $useSqlite -ne 'Y') {
            Write-Host "Reinstall Docker Desktop, then re-run this script." -ForegroundColor Yellow
            Read-Host "Press Enter to exit"
            exit 1
        }
        Write-Host "  Switching to SQLite mode..." -ForegroundColor Cyan
        $global:DOCKER_AVAILABLE = $false
    }
}

if ($global:DOCKER_AVAILABLE -ne $false) {
    # Ждём готовности Docker daemon (до 60 секунд)
    $daemonReady = $false
    for ($i = 1; $i -le 60; $i++) {
        try {
            $dockerInfo = docker info 2>&1
            if ($LASTEXITCODE -eq 0) {
                $daemonReady = $true
                Write-OK "Docker daemon ready (waited $i seconds)"
                break
            }
        } catch { }
        if ($i -eq 1) {
            Write-Host "  Waiting for Docker daemon to start..." -ForegroundColor Yellow
        }
        if ($i % 10 -eq 0 -and $i -gt 0) {
            Write-Host "    Still waiting... ($i seconds)" -ForegroundColor Yellow
            Write-Host "    Hint: open Docker Desktop manually if not started" -ForegroundColor Yellow
        }
        Start-Sleep -Seconds 1
    }

    if (-not $daemonReady) {
        Write-Err "Docker daemon not responding after 60 seconds"
        Write-Host ""
        Write-Host "  TROUBLESHOOTING:" -ForegroundColor Yellow
        Write-Host "    1. Open Docker Desktop manually from Start menu" -ForegroundColor Yellow
        Write-Host "    2. Wait for 'Engine running' in system tray" -ForegroundColor Yellow
        Write-Host "    3. Check Settings -> Resources -> WSL Integration" -ForegroundColor Yellow
        Write-Host "    4. Or restart via: wsl --shutdown && docker desktop" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  OR continue with SQLite mode (no Docker):" -ForegroundColor Cyan
        $useSqlite = Read-Host "  Continue with SQLite? (y/n)"
        if ($useSqlite -ne 'y' -and $useSqlite -ne 'Y') {
            Read-Host "Press Enter to exit"
            exit 1
        }
        Write-Host "  Switching to SQLite mode..." -ForegroundColor Cyan
        $global:DOCKER_AVAILABLE = $false
    }
}

if ($global:DOCKER_AVAILABLE -ne $false) {
    $pgExists = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq "hmp-postgres" }
    if (-not $pgExists) {
        Write-Host "  Starting hmp-postgres container..."
        docker run -d `
            --name hmp-postgres `
            -e POSTGRES_DB=html_mp `
            -e POSTGRES_USER=hmp `
            -e POSTGRES_PASSWORD=hmp_password `
            -p 127.0.0.1:5432:5432 `
            -v hmp_pgdata:/var/lib/postgresql/data `
            --restart unless-stopped `
            postgres:15-alpine | Out-Null

        Write-Host "  Waiting for PostgreSQL to be ready..."
        for ($i = 1; $i -le 30; $i++) {
            $ready = docker exec hmp-postgres pg_isready -U hmp 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-OK "PostgreSQL ready"
                break
            }
            Start-Sleep -Seconds 1
        }
    } else {
        Write-OK "hmp-postgres already exists"
        docker start hmp-postgres | Out-Null
    }
} else {
    # SQLite fallback
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host "  SQLITE MODE (no Docker)" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Backend will use SQLite file instead of PostgreSQL." -ForegroundColor Cyan
    Write-Host "  Functionality: 90% (no Alembic migrations, but tables auto-created)" -ForegroundColor Cyan
    Write-Host ""

    # Обновляем .env для SQLite
    $envContent = Get-Content $envFile -Raw
    $envContent = $envContent -replace "DATABASE_URL=postgresql\+asyncpg://hmp:hmp_password@localhost:5432/html_mp", "DATABASE_URL=sqlite+aiosqlite:///$PROJECT_DIR/data/hmp.db"
    $envContent | Out-File -FilePath $envFile -Encoding UTF8 -Force

    Write-OK ".env updated to use SQLite"
    Write-Host "  SQLite DB will be at: $PROJECT_DIR\data\hmp.db" -ForegroundColor Gray
    Write-Host ""
}

# ============================================================
# Шаг 5/8: ML модели — используем отдельные .py файлы
# ============================================================
Write-Step "Step 5/8: Downloading ML models (~3 GB)..."

# Поиск backend папки (тот же что в Шаге 6)
$backendCandidates5 = @(
    (Join-Path $PROJECT_DIR "code\hmp-backend"),
    (Join-Path (Get-Location) "code\hmp-backend"),
    ".\code\hmp-backend",
    "$PSScriptRoot\code\hmp-backend",
    "$PSScriptRoot\..\code\hmp-backend"
)
$backendDir5 = $null
foreach ($candidate in $backendCandidates5) {
    if ($candidate -and (Test-Path $candidate)) {
        $backendDir5 = $candidate
        break
    }
}

$modelsDir = Join-Path $PROJECT_DIR "models"
$scriptsDir = if ($backendDir5) { Join-Path $backendDir5 "scripts" } else { Join-Path $PROJECT_DIR "code\hmp-backend\scripts" }

if (-not (Test-Path $modelsDir)) {
    New-Item -ItemType Directory -Path $modelsDir | Out-Null
}

# Устанавливаем faster-whisper если нужно
Write-Host "  Installing faster-whisper..."
try {
    pip install --quiet --disable-pip-version-check --trusted-host pypi.org --trusted-host files.pythonhosted.org faster-whisper 2>&1 | Out-Null
    Write-OK "faster-whisper installed"
} catch {
    Write-Warn "Could not install faster-whisper (continuing)"
    Write-Host "    This might be OK if we run from venv after" -ForegroundColor Gray
}

# Создаём временный Python скрипт для загрузки моделей
$whisperScript = Join-Path $PROJECT_DIR "download_models.py"
$modelsDirEscaped = $modelsDir -replace '\\', '\\\\'

@"
import os
import sys

models_dir = r"$modelsDir"

# Step 1: Whisper
print("  Downloading Whisper Large-v3 (~3 GB)...", flush=True)
try:
    from faster_whisper import WhisperModel
    WhisperModel('large-v3', device='auto', compute_type='float16', download_root=os.path.join(models_dir, 'whisper'))
    print("  [OK] Whisper Large-v3 ready", flush=True)
except Exception as e:
    print(f"  [WARN] Whisper download failed: {e}", flush=True)

# Step 2: pyannote (only if HF_TOKEN set)
hf_token = os.environ.get('HF_TOKEN', '')
if hf_token:
    print("  Downloading pyannote diarization...", flush=True)
    try:
        from pyannote.audio import Pipeline
        Pipeline.from_pretrained('pyannote/speaker-diarization-3.1', cache_dir=os.path.join(models_dir, 'pyannote'))
        print("  [OK] pyannote ready", flush=True)
    except Exception as e:
        print(f"  [WARN] pyannote download failed: {e}", flush=True)
        print("    Check HF_TOKEN and accept terms: https://huggingface.co/pyannote/speaker-diarization-3.1", flush=True)
else:
    print("  [WARN] HF_TOKEN not set - pyannote skipped", flush=True)
    print("    Add token to .env and run later:", flush=True)
    print("    python -c \"from pyannote.audio import Pipeline; Pipeline.from_pretrained('pyannote/speaker-diarization-3.1')\"", flush=True)
"@ | Out-File -FilePath $whisperScript -Encoding UTF8

# Читаем HF_TOKEN из .env если есть
$hfToken = ""
if (Test-Path $envFile) {
    $tokenLine = Select-String -Path $envFile -Pattern "^PYANNOTE_TOKEN=(.+)$"
    if ($tokenLine) {
        $hfToken = $tokenLine.Matches[0].Groups[1].Value
        if ($hfToken -eq "") { $hfToken = "" }
    }
}

# Запускаем скрипт
Write-Host "  Starting model download..."
$env:HF_TOKEN = $hfToken
try {
    python $whisperScript
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Model downloads complete"
    } else {
        Write-Warn "Some models failed to download (see above)"
    }
} catch {
    Write-Warn "Error running download script: $_"
}

# Чистим временный файл
Remove-Item $whisperScript -ErrorAction SilentlyContinue

# ============================================================
# Шаг 6/8: Python зависимости
# ============================================================
Write-Step "Step 6/8: Installing Python dependencies (5-15 min)..."

# Поиск backend папки: сначала USERPROFILE, потом fallback
$backendCandidates = @(
    (Join-Path $PROJECT_DIR "code\hmp-backend"),
    (Join-Path (Get-Location) "code\hmp-backend"),
    ".\code\hmp-backend",
    "$PSScriptRoot\code\hmp-backend",
    "$PSScriptRoot\..\code\hmp-backend",
    "C:\Проекты\IT Архитектор\AI\HTML_Protokol\HTML_MeetingProtokol\code\hmp-backend"
)

$backendDir = $null
foreach ($candidate in $backendCandidates) {
    if ($candidate -and (Test-Path $candidate)) {
        $backendDir = $candidate
        Write-Host "  Found backend at: $backendDir" -ForegroundColor Green
        break
    }
}

if (-not $backendDir) {
    Write-Warn "Could not find code\hmp-backend"
    Write-Host "  Tried paths:" -ForegroundColor Yellow
    foreach ($candidate in $backendCandidates) {
        Write-Host "    - $candidate" -ForegroundColor Gray
    }
    Write-Host "  Current directory: $(Get-Location)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Run this script from project root:" -ForegroundColor Yellow
    Write-Host "    cd C:\path\to\HTML_MeetingProtokol" -ForegroundColor Cyan
    Write-Host "    powershell -ExecutionPolicy Bypass -File .\deploy-windows.ps1" -ForegroundColor Cyan
    Read-Host "Press Enter to exit"
    exit 1
}

Set-Location $backendDir

# КРИТИЧНО: отключаем SOCKS proxy для pip (если есть в env)
# Эта ошибка часто возникает из-за настроенного прокси в Windows
$env:HTTP_PROXY = $null
$env:HTTPS_PROXY = $null
$env:ALL_PROXY = $null
$env:NO_PROXY = "*"
# Также отключаем системные pip настройки
$pipConfPath = Join-Path $env:APPDATA "pip\pip.ini"
if (Test-Path $pipConfPath) {
    Write-Host "  Found pip.ini at $pipConfPath - temporarily disabling..." -ForegroundColor Yellow
    Move-Item $pipConfPath "$pipConfPath.disabled" -Force
}
$pipUserConfPath = Join-Path $env:USERPROFILE ".pip\pip.conf"
if (Test-Path $pipUserConfPath) {
    Write-Host "  Found pip.conf - temporarily disabling..." -ForegroundColor Yellow
    Move-Item $pipUserConfPath "$pipUserConfPath.disabled" -Force
}

if (-not (Test-Path ".venv")) {
    Write-Host "  Creating virtual environment..."
    python -m venv .venv | Out-Null
    Write-OK ".venv created"
}

& .\.venv\Scripts\Activate.ps1

Write-Host "  Upgrading pip..."
python -m pip install --quiet --upgrade --disable-pip-version-check --trusted-host pypi.org --trusted-host files.pythonhosted.org pip 2>&1 | Out-Null
Write-OK "pip upgraded"

# Базовые зависимости
$reqFile = Join-Path $PROJECT_DIR "requirements-minimal.txt"
$backendReqFile = Join-Path $backendDir "requirements-minimal.txt"

if (-not (Test-Path $backendReqFile) -and (Test-Path $reqFile)) {
    # Копируем в UTF-8 (pip в Python 3.10+ использует UTF-8 по умолчанию)
    Copy-Item $reqFile $backendReqFile
}

# Настройки pip для обхода SOCKS/proxy
$pipCommonArgs = @("--quiet", "--disable-pip-version-check", "--no-cache-dir", "--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org")

if (Test-Path $backendReqFile) {
    Write-Host "  Installing requirements-minimal.txt..."
    try {
        & pip install @pipCommonArgs -r requirements-minimal.txt 2>&1 | Out-Null
        Write-OK "Base dependencies installed"
    } catch {
        Write-Warn "Some base dependencies failed (continuing)"
    }
} else {
    Write-Warn "requirements-minimal.txt not found"
}

# PyTorch (GPU или CPU)
Write-Host "  Installing PyTorch..."

# Определяем реальный GPU (не виртуальный от Hyper-V/WSL2)
$realGpu = $false
try {
    $gpuOutput = nvidia-smi 2>&1
    # Реальная NVIDIA карта показывает модель (RTX, GTX, Tesla, etc.)
    # Виртуальная от WSL2 показывает "vGPU" или "Hyper-V Virtual GPU"
    if ($LASTEXITCODE -eq 0 -and ($gpuOutput -match "RTX|GTX|Tesla|Quadro|TITAN" -or $gpuOutput -match "Driver Version: \d+\.\d+")) {
        # Дополнительная проверка - в WSL2 nvidia-smi работает, но внутри WSL2
        # На чистом Windows без NVIDIA драйвера - это будет "vGPU"
        if ($gpuOutput -notmatch "vGPU|Hyper-V Virtual") {
            $realGpu = $true
        }
    }
} catch { }

if ($realGpu) {
    Write-Host "    NVIDIA GPU detected, installing CUDA version..." -ForegroundColor Cyan
    try {
        & pip install @pipCommonArgs torch --index-url https://download.pytorch.org/whl/cu121 2>&1 | Out-Null
        Write-OK "PyTorch (CUDA) installed"
    } catch {
        Write-Warn "CUDA PyTorch failed, falling back to CPU"
        & pip install @pipCommonArgs torch --index-url https://download.pytorch.org/whl/cpu 2>&1 | Out-Null
        Write-OK "PyTorch (CPU) installed"
    }
} else {
    Write-Host "    No NVIDIA GPU (or virtual GPU detected), installing CPU version..." -ForegroundColor Cyan
    & pip install @pipCommonArgs torch --index-url https://download.pytorch.org/whl/cpu 2>&1 | Out-Null
    Write-OK "PyTorch (CPU) installed"
}

# ML библиотеки
Write-Host "  Installing ML libraries..."
try {
    & pip install @pipCommonArgs faster-whisper 2>&1 | Out-Null
    & pip install @pipCommonArgs pyannote.audio 2>&1 | Out-Null
    Write-OK "ML libraries installed"
} catch {
    Write-Warn "Some ML libraries failed (continuing)"
}

# ============================================================
# Шаг 7/8: Миграции БД
# ============================================================
Write-Step "Step 7/8: Applying Alembic migrations..."

if ($global:DOCKER_AVAILABLE -ne $false) {
    # PostgreSQL: применяем Alembic миграции
    try {
        alembic upgrade head 2>&1 | Out-Null
        Write-OK "Migrations applied"
    } catch {
        Write-Warn "Alembic migrations failed"
        Write-Host "     Try later: cd code\hmp-backend && .venv\Scripts\activate && alembic upgrade head" -ForegroundColor Yellow
    }
} else {
    # SQLite: таблицы создаются автоматически при старте (init_db)
    Write-Host "  SQLite mode - skipping Alembic migrations" -ForegroundColor Yellow
    Write-Host "  Tables will be auto-created when backend starts" -ForegroundColor Yellow
    Write-OK "Skipped (not needed for SQLite)"
}

# ============================================================
# Шаг 8/8: Финал
# ============================================================
Write-Step "Step 8/8: Creating start scripts..."

$startBat = Join-Path $PROJECT_DIR "start.bat"
$startBatContent = @"
@echo off
set PROJECT_DIR=$PROJECT_DIR
docker start hmp-postgres >nul 2>&1
start "HMP Backend" cmd /k "cd /d %PROJECT_DIR%\code\hmp-backend && .venv\Scripts\activate && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
timeout /t 3 /nobreak >nul
start "HMP Frontend" cmd /k "cd /d %PROJECT_DIR%\code\hmp-frontend\public && python -m http.server 5173"
timeout /t 3 /nobreak >nul
start http://127.0.0.1:8000/docs
start http://127.0.0.1:5173/
echo Started! Backend: 8000, Frontend: 5173.
pause
"@
$startBatContent | Out-File -FilePath $startBat -Encoding ASCII

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Project: $PROJECT_DIR" -ForegroundColor White
Write-Host ""
Write-Host "Quick start:" -ForegroundColor Yellow
Write-Host "   Double-click: start.bat" -ForegroundColor White
Write-Host ""
Write-Host "Manual start:" -ForegroundColor Yellow
Write-Host "   1. Backend (first terminal):" -ForegroundColor White
Write-Host "      cd $backendDir" -ForegroundColor Gray
Write-Host "      .venv\Scripts\activate" -ForegroundColor Gray
Write-Host "      uvicorn app.main:app --reload --host 127.0.0.1 --port 8000" -ForegroundColor Gray
Write-Host ""
Write-Host "   2. Frontend (second terminal):" -ForegroundColor White
Write-Host "      cd $PROJECT_DIR\code\hmp-frontend\public" -ForegroundColor Gray
Write-Host "      python -m http.server 5173" -ForegroundColor Gray
Write-Host ""
Write-Host "   3. Open in browser:" -ForegroundColor White
Write-Host "      API docs:   http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Write-Host "      Frontend:   http://127.0.0.1:5173/" -ForegroundColor Cyan
Write-Host ""
Write-Host "Stop: Ctrl+C in terminals, or stop hmp-postgres in Docker Desktop" -ForegroundColor Gray
Write-Host ""
Write-Host "Edit .env for AI features:" -ForegroundColor Yellow
Write-Host "   notepad $envFile" -ForegroundColor White
Write-Host ""
Read-Host "Press Enter to exit"
