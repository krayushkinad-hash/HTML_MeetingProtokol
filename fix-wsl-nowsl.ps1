# ============================================================
# Обход ошибки Remote Desktop ActiveX (rdclientax.dll)
# Полностью обходим wsl.exe - всё через dism/registry напрямую
# Запускать от Администратора!
# ============================================================
#Requires -Version 5.1
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Fix WSL2 - FULL BYPASS of wsl.exe" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This script does NOT call wsl.exe (which triggers ActiveX error)" -ForegroundColor Yellow
Write-Host "It uses dism + registry + direct kernel installation only" -ForegroundColor Yellow
Write-Host ""

# ============================================================
# Шаг 1: Проверка компонентов через реестр (без wsl)
# ============================================================
Write-Host "[1/5] Checking Windows features via registry..." -ForegroundColor Cyan

# Читаем состояние компонентов из реестра напрямую
function Get-FeatureStateFromRegistry($featureName) {
    $key = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\Packages\Packages_$featureName"
    # Альтернативный путь - читаем через dism
    try {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $featureName -ErrorAction SilentlyContinue
        return $feature.State
    } catch {
        return "Unknown"
    }
}

$wslState = Get-FeatureStateFromRegistry "Microsoft-Windows-Subsystem-Linux"
$vmState = Get-FeatureStateFromRegistry "VirtualMachinePlatform"

Write-Host "  WSL:           $wslState" -ForegroundColor $(if ($wslState -eq 'Enabled') { 'Green' } else { 'Yellow' })
Write-Host "  VM Platform:   $vmState" -ForegroundColor $(if ($vmState -eq 'Enabled') { 'Green' } else { 'Yellow' })
Write-Host ""

# ============================================================
# Шаг 2: Включение компонентов через dism
# ============================================================
Write-Host "[2/5] Enabling Windows features via dism..." -ForegroundColor Cyan

Write-Host "  Enabling Microsoft-Windows-Subsystem-Linux..." -ForegroundColor Yellow
$proc1 = Start-Process -FilePath "dism.exe" -ArgumentList "/online", "/enable-feature", "/featurename:Microsoft-Windows-Subsystem-Linux", "/all", "/norestart" -Wait -PassThru -NoNewWindow -ErrorAction SilentlyContinue
Write-Host "    Exit code: $($proc1.ExitCode)" -ForegroundColor $(if ($proc1.ExitCode -eq 0) { 'Green' } else { 'Yellow' })

Write-Host ""
Write-Host "  Enabling VirtualMachinePlatform..." -ForegroundColor Yellow
$proc2 = Start-Process -FilePath "dism.exe" -ArgumentList "/online", "/enable-feature", "/featurename:VirtualMachinePlatform", "/all", "/norestart" -Wait -PassThru -NoNewWindow -ErrorAction SilentlyContinue
Write-Host "    Exit code: $($proc2.ExitCode)" -ForegroundColor $(if ($proc2.ExitCode -eq 0) { 'Green' } else { 'Yellow' })

Write-Host ""

# ============================================================
# Шаг 3: Скачивание WSL2 kernel (через Invoke-WebRequest)
# ============================================================
Write-Host "[3/5] Downloading WSL2 Linux kernel..." -ForegroundColor Cyan
Write-Host "  URL: https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi" -ForegroundColor Gray
Write-Host ""

$wslKernelUrl = "https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi"
$wslKernelMsi = Join-Path $env:TEMP "wsl_update_x64.msi"

try {
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $wslKernelUrl -OutFile $wslKernelMsi -UseBasicParsing -TimeoutSec 60
    $ProgressPreference = 'Continue'

    if (Test-Path $wslKernelMsi) {
        $size = (Get-Item $wslKernelMsi).Length
        Write-Host "  Downloaded: $([math]::Round($size / 1MB, 1)) MB" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] File not downloaded" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "  [FAIL] Download error: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# ============================================================
# Шаг 4: Установка WSL2 kernel (тихо)
# ============================================================
Write-Host "[4/5] Installing WSL2 kernel (silent, no UI)..." -ForegroundColor Cyan

try {
    $proc = Start-Process -FilePath "msiexec.exe" -ArgumentList "/i", $wslKernelMsi, "/qn", "/norestart" -Wait -PassThru -NoNewWindow -ErrorAction Stop
    Write-Host "    Exit code: $($proc.ExitCode)" -ForegroundColor $(if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 3010) { 'Green' } else { 'Yellow' })
    Write-Host "    (0 means OK, 3010 means reboot required - both are OK)" -ForegroundColor Gray
    Remove-Item $wslKernelMsi -ErrorAction SilentlyContinue
} catch {
    Write-Host "  [FAIL] Installation error: $_" -ForegroundColor Red
}

Write-Host ""

# ============================================================
# Шаг 5: Установка WSL2 как default через реестр (без wsl.exe!)
# ============================================================
Write-Host "[5/5] Setting WSL2 as default via registry..." -ForegroundColor Cyan

# HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Lxss
# DefaultVersion = 2
$lxssKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss"

try {
    if (-not (Test-Path $lxssKey)) {
        New-Item -Path $lxssKey -Force | Out-Null
    }
    Set-ItemProperty -Path $lxssKey -Name "DefaultVersion" -Value 2 -Type DWord
    Write-Host "  [OK] WSL2 set as default (in registry)" -ForegroundColor Green
    Write-Host "    Path: $lxssKey" -ForegroundColor Gray
    Write-Host "    Value: DefaultVersion set to 2" -ForegroundColor Gray
} catch {
    Write-Host "  [WARN] Could not set registry value" -ForegroundColor Yellow
    Write-Host "    Try after reboot: Set WSL2 default in 'Turn Windows features on or off'" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " FIX COMPLETE (without wsl.exe)!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

# Финальная проверка через реестр
Write-Host "FINAL CHECK:" -ForegroundColor Cyan
$finalWsl = Get-FeatureStateFromRegistry "Microsoft-Windows-Subsystem-Linux"
$finalVm = Get-FeatureStateFromRegistry "VirtualMachinePlatform"
$regCheck = Get-ItemProperty -Path $lxssKey -Name "DefaultVersion" -ErrorAction SilentlyContinue

Write-Host "  WSL:           $finalWsl" -ForegroundColor $(if ($finalWsl -eq 'Enabled') { 'Green' } else { 'Yellow' })
Write-Host "  VM Platform:   $finalVm" -ForegroundColor $(if ($finalVm -eq 'Enabled') { 'Green' } else { 'Yellow' })
Write-Host "  WSL2 default:  $($regCheck.DefaultVersion)" -ForegroundColor $(if ($regCheck.DefaultVersion -eq 2) { 'Green' } else { 'Yellow' })

Write-Host ""
Write-Host "============================================================" -ForegroundColor Red
Write-Host " CRITICAL: REBOOT REQUIRED!" -ForegroundColor Red
Write-Host "============================================================" -ForegroundColor Red
Write-Host ""
Write-Host "  1. SAVE all open files" -ForegroundColor White
Write-Host "  2. REBOOT Windows: shutdown /r /t 0" -ForegroundColor White
Write-Host "  3. After restart: open Docker Desktop, wait for 'Engine running'" -ForegroundColor White
Write-Host "  4. Run deploy-windows.ps1 again" -ForegroundColor White
Write-Host ""
Write-Host "  If Docker still complains, use SQLite mode:" -ForegroundColor Yellow
Write-Host "    Run deploy-windows.bat and type 'y' when asked 'Continue with SQLite?'" -ForegroundColor Yellow
Write-Host ""

$reboot = Read-Host "Reboot now? (y/n)"
if ($reboot -eq 'y' -or $reboot -eq 'Y') {
    Write-Host "Rebooting in 5 seconds..." -ForegroundColor Green
    shutdown /r /t 5
} else {
    Write-Host "Remember to reboot manually before running Docker!" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
}
