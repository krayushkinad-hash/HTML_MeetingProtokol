# deploy-to-vps.bat
# Запускать из C:\HTML_Protokol на Windows
# Заливает zip-архив на VPS и распаковывает

@echo off
chcp 65001 >nul
setlocal

set VPS_IP=195.133.77.76
set VPS_USER=root
set PROJECT_DIR=C:\HTML_Protokol
set ZIP=%PROJECT_DIR%\..\HTML_MeetingProtokol-v1.0.0.zip
if not exist "%ZIP%" set ZIP=%PROJECT_DIR%\HTML_MeetingProtokol-v1.0.0.zip

echo ============================================================
echo  Deploy to VPS: %VPS_IP%
echo ============================================================

echo.
echo [1/3] Создаю zip архив...
cd /d "%PROJECT_DIR%"
if exist ..\HTML_MeetingProtokol-v1.0.0.zip del ..\HTML_MeetingProtokol-v1.0.0.zip
powershell -Command "Compress-Archive -Path '%PROJECT_DIR%\*' -DestinationPath '..\HTML_MeetingProtokol-v1.0.0.zip' -CompressionLevel Optimal -Force"

echo.
echo [2/3] scp архив на сервер...
where scp >nul 2>&1
if errorlevel 1 (
    echo [ERROR] scp не найден. Установите OpenSSH Client:
    echo   Settings → Apps → Optional Features → OpenSSH Client
    pause
    exit /b 1
)

scp "%ZIP%" %VPS_USER%@%VPS_IP%:/tmp/hmp-update.zip
if errorlevel 1 (
    echo [ERROR] scp не удалось. Проверьте SSH доступ.
    pause
    exit /b 1
)

echo.
echo [3/3] Распаковка + обновление на сервере...
ssh %VPS_USER%@%VPS_IP% "bash -s" << EOF
    set -e
    cd /root
    if [ ! -d HTML_MeetingProtokol ]; then
        echo "Первая установка — запустите deploy-vps.sh вручную"
        exit 1
    fi
    echo "Распаковка..."
    unzip -oq /tmp/hmp-update.zip
    rm /tmp/hmp-update.zip
    chown -R hmp:hmp /root/HTML_MeetingProtokol
    echo "Запуск update-vps.sh..."
    bash /root/HTML_MeetingProtokol/update-vps.sh
EOF

if errorlevel 1 (
    echo.
    echo [ERROR] Update failed. Подключитесь вручную:
    echo   ssh %VPS_USER%@%VPS_IP%
    echo   cat /var/log/hmp-backend.log
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  ✅ DEPLOYED
echo ============================================================
echo   http://%VPS_IP%/
echo.
pause
endlocal
