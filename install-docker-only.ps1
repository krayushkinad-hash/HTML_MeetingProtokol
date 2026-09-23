# ============================================================
# Установка Docker Desktop (PowerShell версия)
# Использование: powershell -ExecutionPolicy Bypass -File .\install-docker-only.ps1
# ============================================================

#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Installing Docker Desktop..." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# Шаг 1: Попробовать winget
# ============================================================
$winget = Get-Command winget -ErrorAction SilentlyContinue
if ($winget) {
    Write-Host "[1/3] Trying winget..." -ForegroundColor Cyan
    try {
        winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "============================================================" -ForegroundColor Green
            Write-Host " Docker Desktop installed via winget!" -ForegroundColor Green
            Write-Host "============================================================" -ForegroundColor Green
            Write-Host ""
            Write-Host "NEXT STEPS:" -ForegroundColor Yellow
            Write-Host "  1. RESTART computer (required for Hyper-V/WSL2)" -ForegroundColor Yellow
            Write-Host "  2. Open Docker Desktop after restart" -ForegroundColor Yellow
            Write-Host "  3. Wait for 'Engine running' in system tray" -ForegroundColor Yellow
            Write-Host "  4. Run deploy-windows.ps1 again" -ForegroundColor Yellow
            Write-Host ""
            Read-Host "Press Enter to exit"
            exit 0
        }
        Write-Host "  winget failed, falling back to direct download..." -ForegroundColor Yellow
    } catch {
        Write-Host "  winget error: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "[1/3] winget not found, going to direct download..." -ForegroundColor Yellow
}

# ============================================================
# Шаг 2: Скачать Docker Desktop Installer
# ============================================================
Write-Host ""
Write-Host "[2/3] Downloading Docker Desktop Installer..." -ForegroundColor Cyan
Write-Host "  Size: ~600 MB" -ForegroundColor Gray
Write-Host "  URL: https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe" -ForegroundColor Gray
Write-Host ""

PROJECT_DIR = Join-Path env:USERPROFILE "HTML_MeetingProtokol"
if (-not (Test-Path PROJECT_DIR)) {
    if (Test-Path "C:\HTML_Protokol") {
        PROJECT_DIR = "C:\HTML_Protokol"
    }
}
installerPath = Join-Path PROJECT_DIR "DockerDesktopInstaller.exe"
downloadUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"

try {
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing
    $ProgressPreference = 'Continue'

    $fileSize = (Get-Item $installerPath).Length
    if ($fileSize -lt 100MB) {
        Write-Host "  ERROR: Downloaded file too small ($fileSize bytes)" -ForegroundColor Red
        Write-Host "  Expected ~600 MB" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  Downloaded: $([math]::Round($fileSize / 1MB, 1)) MB" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Download failed: $_" -ForegroundColor Red
    Write-Host "  Try manually: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
    exit 1
}

# ============================================================
# Шаг 3: Установить тихо
# ============================================================
Write-Host ""
Write-Host "[3/3] Installing Docker Desktop (silent, requires Admin)..." -ForegroundColor Cyan
Write-Host "  Installer: $installerPath" -ForegroundColor Gray
Write-Host "  This may take 5-10 minutes..." -ForegroundColor Yellow
Write-Host ""

try {
    $proc = Start-Process -FilePath $installerPath -ArgumentList "install", "--quiet", "--accept-license" -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -eq 0) {
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host " Docker Desktop installed successfully!" -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host ""

        # Удаляем инсталлятор
        Remove-Item $installerPath -ErrorAction SilentlyContinue

        Write-Host "NEXT STEPS:" -ForegroundColor Yellow
        Write-Host "  1. RESTART computer (required for Hyper-V/WSL2)" -ForegroundColor Yellow
        Write-Host "  2. Open Docker Desktop after restart" -ForegroundColor Yellow
        Write-Host "  3. Wait for 'Engine running' in system tray" -ForegroundColor Yellow
        Write-Host "  4. Run deploy-windows.ps1 again" -ForegroundColor Yellow
        Write-Host ""
        Read-Host "Press Enter to exit"
        exit 0
    } else {
        Write-Host "  ERROR: Installer exit code $($proc.ExitCode)" -ForegroundColor Red
        Write-Host "  Try double-clicking: $installerPath" -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
} catch {
    Write-Host "  ERROR: Installation failed: $_" -ForegroundColor Red
    exit 1
}
