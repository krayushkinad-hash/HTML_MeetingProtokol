# ============================================================
# Полное удаление Docker Desktop с очисткой всех следов
# Запускать от Администратора!
# ============================================================
Write-Host "============================================================" -ForegroundColor Red
Write-Host " Docker Desktop - Complete Removal" -ForegroundColor Red
Write-Host "============================================================" -ForegroundColor Red
Write-Host ""
Write-Host "This will completely remove Docker Desktop and all its data." -ForegroundColor Yellow
Write-Host "BACKUP YOUR DATA first if you have important containers!" -ForegroundColor Yellow
Write-Host ""

$confirm = Read-Host "Continue? (y/n)"
if ($confirm -ne 'y' -and $confirm -ne 'Y') {
    Write-Host "Cancelled."
    Read-Host "Press Enter to exit"
    exit 0
}

Write-Host ""
Write-Host "[1/6] Stopping all Docker processes..." -ForegroundColor Cyan
$dockerProcesses = Get-Process | Where-Object {
    $_.Name -match "docker" -or $_.Name -match "Docker"
}
if ($dockerProcesses) {
    Write-Host "  Found $($dockerProcesses.Count) Docker processes, stopping..." -ForegroundColor Yellow
    $dockerProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Write-OK "Docker processes stopped"
} else {
    Write-Host "  No Docker processes running" -ForegroundColor Green
}

Write-Host ""
Write-Host "[2/6] Removing Docker services..." -ForegroundColor Cyan
$services = @("com.docker.service", "docker", "Docker Desktop Service")
foreach ($svc in $services) {
    $exists = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($exists) {
        Write-Host "  Stopping service: $svc"
        Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Write-Host "  Removing service: $svc"
        sc.exe delete $svc 2>&1 | Out-Null
    }
}
Write-OK "Docker services removed"

Write-Host ""
Write-Host "[3/6] Removing Docker Desktop application..." -ForegroundColor Cyan

# Try winget uninstall (if available)
$wingetPath = Get-Command winget -ErrorAction SilentlyContinue
if ($wingetPath) {
    Write-Host "  Trying winget uninstall..."
    winget uninstall -e --id Docker.DockerDesktop --silent --accept-source-agreements 2>&1 | Out-Null
    Start-Sleep -Seconds 5
}

# Manual uninstall via uninstaller
$uninstallerPaths = @(
    "$env:ProgramFiles\Docker\Docker\uninstall.exe",
    "${env:ProgramFiles(x86)}\Docker\Docker\uninstall.exe"
)
foreach ($uninst in $uninstallerPaths) {
    if (Test-Path $uninst) {
        Write-Host "  Running uninstaller: $uninst"
        $proc = Start-Process -FilePath $uninst -ArgumentList "/quiet", "/S" -Wait -PassThru -NoNewWindow
        Start-Sleep -Seconds 5
        break
    }
}

# Verify
$dockerExe = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerExe) {
    Write-Host "  Docker still found, manual cleanup needed..." -ForegroundColor Yellow
} else {
    Write-OK "Docker Desktop uninstalled"
}

Write-Host ""
Write-Host "[4/6] Removing Docker files and folders..." -ForegroundColor Cyan

$pathsToRemove = @(
    "$env:ProgramFiles\Docker",
    "${env:ProgramFiles(x86)}\Docker",
    "$env:LOCALAPPDATA\Programs\Docker",
    "$env:APPDATA\Docker",
    "$env:LOCALAPPDATA\Docker",
    "$env:PROGRAMDATA\Docker",
    "$env:PROGRAMDATA\docker",
    "$env:PROGRAMDATA\DockerDesktop",
    "$env:APPDATA\Docker Desktop"
)

foreach ($p in $pathsToRemove) {
    if (Test-Path $p) {
        Write-Host "  Removing: $p"
        try {
            Remove-Item -Recurse -Force $p -ErrorAction Stop
            Write-Host "    Removed" -ForegroundColor Green
        } catch {
            Write-Host "    Failed: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}
Write-OK "Docker folders removed"

Write-Host ""
Write-Host "[5/6] Removing WSL Docker data (safely, with try-catch)..." -ForegroundColor Cyan
# Используем try-catch чтобы ошибка Remote Desktop ActiveX не прерывала скрипт
$wslAvailable = $false
try {
    $null = & wsl.exe --status 2>&1
    $wslAvailable = $true
} catch {
    Write-Host "  wsl.exe not available (skipping WSL cleanup)" -ForegroundColor Yellow
}

if ($wslAvailable) {
    try {
        $wslList = & wsl.exe --list --quiet 2>&1
        if ($wslList -and $wslList -match "docker-desktop") {
            Write-Host "  Found docker-desktop WSL distro, unregistering..."
            & wsl.exe --unregister docker-desktop 2>&1 | Out-Null
            Write-Host "    Done" -ForegroundColor Green
        } else {
            Write-Host "  No WSL docker-desktop found" -ForegroundColor Green
        }
    } catch {
        Write-Host "  WSL list failed (ActiveX error ignored)" -ForegroundColor Yellow
    }
}
Write-OK "WSL Docker data cleaned"

Write-Host ""
Write-Host "[6/6] Removing PATH entries..." -ForegroundColor Cyan
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath) {
    $newPath = ($currentPath -split ";" | Where-Object { $_ -notlike "*docker*" }) -join ";"
    if ($newPath -ne $currentPath) {
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        $env:PATH = ($env:PATH -split ";" | Where-Object { $_ -notlike "*docker*" }) -join ";"
        Write-Host "  Removed Docker entries from PATH" -ForegroundColor Green
    } else {
        Write-Host "  No Docker entries in PATH" -ForegroundColor Green
    }
}
$machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
if ($machinePath -and $machinePath -match "docker") {
    Write-Host "  WARNING: Machine PATH still contains Docker entries" -ForegroundColor Yellow
    Write-Host "    Manual cleanup needed via System Properties > Environment Variables" -ForegroundColor Yellow
}
Write-OK "PATH cleaned (user scope)"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " CLEANUP COMPLETE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Cyan
Write-Host "  1. RESTART Windows (Start menu > Power > Restart)" -ForegroundColor White
Write-Host "  2. After restart, install Docker Desktop:" -ForegroundColor White
Write-Host "     powershell -ExecutionPolicy Bypass -File .\install-docker-only.bat" -ForegroundColor Gray
Write-Host "  3. If install fails, try manually:" -ForegroundColor White
Write-Host "     https://www.docker.com/products/docker-desktop/" -ForegroundColor Gray
Write-Host ""
Write-Host "REBOOT REQUIRED to clear:" -ForegroundColor Yellow
Write-Host "  - Docker Desktop service (com.docker.service)" -ForegroundColor Yellow
Write-Host "  - WSL2 distro (docker-desktop-data)" -ForegroundColor Yellow
Write-Host "  - Hyper-V VM (if Hyper-V backend was used)" -ForegroundColor Yellow
Write-Host ""
Read-Host "Press Enter to exit"
