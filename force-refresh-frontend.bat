@echo off
REM ============================================================
REM force-refresh-frontend.bat
REM
REM (Russian comment removed for CMD compatibility)
REM (Russian comment removed for CMD compatibility)
REM
REM (Russian comment removed for CMD compatibility)
REM   cd C:\HTML_Protokol
REM   .\force-refresh-frontend.bat
REM
REM (Russian comment removed for CMD compatibility)
REM   - views/*.js (settings, protocol, upload, list, etc.)
REM   - api/client.js
REM   - css/*.css (main, whisper-models, settings, etc.)
REM   - main.js, utils/*.js
REM ============================================================

setlocal
cd /d "%~dp0"

set "SRC_DIR=code\hmp-frontend\src"
set "PUB_DIR=code\hmp-frontend\public\src"

echo ============================================================
echo  Force-refresh frontend: src to public/src
echo ============================================================
echo  Source: %SRC_DIR%
echo  Dest:   %PUB_DIR%
echo.

if not exist "%SRC_DIR%" (
    echo "[ERROR] %SRC_DIR% not found!"
    exit /b 1
)

REM Delete old
if exist "%PUB_DIR%" rmdir /s /q "%PUB_DIR%" 2>nul

REM Copy fresh
xcopy /Y /E /I /Q "%SRC_DIR%\*" "%PUB_DIR%\" >nul 2>&1
if errorlevel 1 (
    echo "[ERROR] Copy failed"
    exit /b 1
)

echo "[OK] Copied successfully."
echo.
echo Next: Ctrl+F5 in browser, or .\restart.bat
echo.

endlocal
