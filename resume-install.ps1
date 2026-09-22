# ============================================================
# Resume Installation - запускать ПОСЛЕ перезагрузки
# Проверяет WSL2/Docker и продолжает установку с Шага 4
# ============================================================
#Requires -Version 5.1
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Resuming Installation After Reboot" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$PROJECT_DIR = Join-Path $env:USERPROFILE "HTML_MeetingProtokol"

# ============================================================
# Шаг A: Проверка WSL2 после перезагрузки
# ============================================================
Write-Host "[A/5] Checking WSL2 status (post-reboot)..." -ForegroundColor Cyan

$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -ErrorAction SilentlyContinue
$vmFeature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -ErrorAction SilentlyContinue
$lxssReg = Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss" -Name "DefaultVersion" -ErrorAction SilentlyContinue

Write-Host "  WSL:           $(if ($wslFeature.State -eq 'Enabled') { 'Enabled' } else { $wslFeature.State })" -ForegroundColor $(if ($wslFeature.State -eq 'Enabled') { 'Green' } else { 'Red' })
Write-Host "  VM Platform:   $(if ($vmFeature.State -eq 'Enabled') { 'Enabled' } else { $vmFeature.State })" -ForegroundColor $(if ($vmFeature.State -eq 'Enabled') { 'Green' } else { 'Red' })
Write-Host "  WSL2 default:  $($lxssReg.DefaultVersion)" -ForegroundColor $(if ($lxssReg.DefaultVersion -eq 2) { 'Green' } else { 'Red' })

if ($wslFeature.State -ne 'Enabled' -or $vmFeature.State -ne 'Enabled') {
    Write-Host ""
    Write-Err "WSL2 still not enabled! Run fix-wsl-nowsl.ps1 again"
    exit 1
}

Write-Host ""

# ============================================================
# Шаг B: Проверка и поиск Docker
# ============================================================
Write-Host "[B/5] Checking Docker..." -ForegroundColor Cyan

$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Host "  docker not in PATH, searching standard locations..." -ForegroundColor Yellow
    $dockerPaths = @(
        "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
        "$env:ProgramFiles\Docker\Docker\bin\docker.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\resources\bin\docker.exe",
        "$env:LOCALAPPDATA\Programs\Docker\Docker\resources\bin\docker.exe"
    )
    foreach ($p in $dockerPaths) {
        if (Test-Path $p) {
            $env:PATH = $env:PATH + ";$(Split-Path $p -Parent)"
            $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
            if ($dockerCmd) {
                Write-Host "    Found: $p" -ForegroundColor Green
                break
            }
        }
    }
}

if (-not $dockerCmd) {
    Write-Err "Docker not installed yet"
    Write-Host "  Run install-docker-only.ps1 first" -ForegroundColor Yellow
    exit 1
}

Write-Host "  Docker: $($dockerCmd.Version)" -ForegroundColor Green
Write-Host ""

# ============================================================
# Шаг C: Запуск Docker Desktop
# ============================================================
Write-Host "[C/5] Starting Docker Desktop..." -ForegroundColor Cyan

$dockerProc = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $dockerProc) {
    $dockerDesktopExe = $null
    $ddPaths = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Programs\Docker\Docker\Docker Desktop.exe"
    )
    foreach ($p in $ddPaths) {
        if (Test-Path $p) {
            $dockerDesktopExe = $p
            break
        }
    }

    if ($dockerDesktopExe) {
        Write-Host "  Starting: $dockerDesktopExe" -ForegroundColor Yellow
        Start-Process -FilePath $dockerDesktopExe
    } else {
        Write-Err "Docker Desktop.exe not found"
        exit 1
    }
}

# ============================================================
# Шаг D: Ожидание Docker daemon
# ============================================================
Write-Host "[D/5] Waiting for Docker daemon (up to 90 seconds)..." -ForegroundColor Cyan

$daemonReady = $false
for ($i = 1; $i -le 90; $i++) {
    try {
        $info = docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            $daemonReady = $true
            Write-Host "  [OK] Docker daemon ready (waited $i seconds)" -ForegroundColor Green
            break
        }
    } catch { }

    if ($i -eq 1) {
        Write-Host "  Waiting..." -ForegroundColor Yellow
    }
    if ($i % 15 -eq 0 -and $i -gt 0) {
        Write-Host "    Still waiting... ($i seconds)" -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 1
}

if (-not $daemonReady) {
    Write-Err "Docker daemon not responding after 90 seconds"
    Write-Host "  Open Docker Desktop manually from Start menu" -ForegroundColor Yellow
    Write-Host "  Wait for 'Engine running' notification" -ForegroundColor Yellow
    Write-Host "  Run this script again" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# ============================================================
# Шаг E: Запуск PostgreSQL
# ============================================================
Write-Host "[E/5] Starting PostgreSQL container..." -ForegroundColor Cyan

$pgExists = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq "hmp-postgres" }
if (-not $pgExists) {
    Write-Host "  Creating hmp-postgres container..." -ForegroundColor Yellow
    docker run -d `
        --name hmp-postgres `
        -e POSTGRES_DB=html_mp `
        -e POSTGRES_USER=hmp `
        -e POSTGRES_PASSWORD=hmp_password `
        -p 127.0.0.1:5432:5432 `
        -v hmp_pgdata:/var/lib/postgresql/data `
        --restart unless-stopped `
        postgres:15-alpine | Out-Null

    Write-Host "  Waiting for PostgreSQL (up to 30 seconds)..." -ForegroundColor Yellow
    for ($i = 1; $i -le 30; $i++) {
        $ready = docker exec hmp-postgres pg_isready -U hmp 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] PostgreSQL ready" -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds 1
    }
} else {
    Write-Host "  hmp-postgres exists, starting..." -ForegroundColor Yellow
    docker start hmp-postgres | Out-Null
    Write-Host "  [OK] PostgreSQL started" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " DOCKER READY!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "NEXT STEP: Run the full deployment script:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  cd $PROJECT_DIR" -ForegroundColor White
Write-Host "  powershell -ExecutionPolicy Bypass -File .\deploy-windows.ps1" -ForegroundColor White
Write-Host ""
Write-Host "Or skip Docker check:" -ForegroundColor Yellow
Write-Host "  .\start.bat" -ForegroundColor White
Write-Host ""
Read-Host "Press Enter to exit"
