@echo off
REM Start HTML_MeetingProtokol - backend + frontend
REM Use full paths to avoid CMD/PATH issues with cyrillic paths

chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM E061: Globally disable ALL proxy variables (SOCKS breaks huggingface_hub)
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set SOCKS_PROXY=
set http_proxy=
set https_proxy=
set all_proxy=
set socks_proxy=

REM Auto-detect project root
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

if exist "%PROJECT_DIR%\scripts\cleanup-docker.bat" set "PROJECT_DIR=%PROJECT_DIR%\.."

if not exist "%PROJECT_DIR%\code\hmp-backend" (
    if exist "%USERPROFILE%\HTML_MeetingProtokol\code\hmp-backend" (
        set "PROJECT_DIR=%USERPROFILE%\HTML_MeetingProtokol"
    ) else (
        if exist "C:\HTML_Protokol\code\hmp-backend" (
            set "PROJECT_DIR=C:\HTML_Protokol"
        ) else (
            if exist "C:\Projects\AI\HTML_MeetingProtokol\code\hmp-backend" (
                set "PROJECT_DIR=C:\Projects\AI\HTML_MeetingProtokol"
            ) else (
                echo.
                echo ============================================================
                echo  ERROR: Cannot find code\hmp-backend
                echo ============================================================
                echo.
                echo  Searched in:
                echo    1. %PROJECT_DIR%
                echo    2. %USERPROFILE%\HTML_MeetingProtokol
                echo    3. C:\HTML_Protokol
                echo    4. C:\Projects\AI\HTML_MeetingProtokol
                echo.
                echo  Place this script in project root or fix paths.
                echo.
                pause
                exit /b 1
            )
        )
    )
)

echo.
echo ============================================================
echo  HTML_MeetingProtokol Starting...
echo ============================================================
echo  Project: %PROJECT_DIR%
echo.

REM Start PostgreSQL if Docker is available
docker --version >nul 2>&1
if not errorlevel 1 (
    echo  Starting PostgreSQL...
    docker start hmp-postgres >nul 2>&1
)

REM Set paths
set "BACKEND_DIR=%PROJECT_DIR%\code\hmp-backend"
set "FRONTEND_DIR=%PROJECT_DIR%\code\hmp-frontend"
set "PUBLIC_DIR=%FRONTEND_DIR%\public"
set "VENV_DIR=%BACKEND_DIR%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_UVICORN=%VENV_DIR%\Scripts\uvicorn.exe"

REM Check if venv exists and has uvicorn
if not exist "%VENV_UVICORN%" (
    echo.
    echo ============================================================
    echo  Backend not installed. Running fix-install.ps1...
    echo ============================================================
    echo.
    powershell -ExecutionPolicy Bypass -File "%PROJECT_DIR%\fix-install.ps1"
    if errorlevel 1 (
        echo.
        echo  Backend installation failed. Run manually:
        echo    cd %BACKEND_DIR%
        echo    python -m venv .venv
        echo    .venv\Scripts\python.exe -m pip install -r requirements-minimal.txt
        echo.
        pause
        exit /b 1
    )
)

echo  Starting backend on http://127.0.0.1:8000...
REM E061: Unset proxy env vars before starting backend
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set SOCKS_PROXY=
set http_proxy=
set https_proxy=
set all_proxy=
set socks_proxy=

start "HMP Backend" cmd /k "cd /d %BACKEND_DIR% && %VENV_UVICORN% app.main:app --reload --host 127.0.0.1 --port 8000"

REM Wait for backend
timeout /t 3 /nobreak >nul

REM Start frontend
if exist "%PUBLIC_DIR%\index.html" (
    echo  Starting frontend on http://127.0.0.1:5173...
    REM Sync src/ -> public/src/ (force-refresh)
    call "%PROJECT_DIR%\force-refresh-frontend.bat" >nul 2>&1
    REM Use system python (not venv) for http.server
    start "HMP Frontend" cmd /k "cd /d %PUBLIC_DIR% && python -m http.server 5173"
) else (
    echo  Frontend not found, skipping
)

REM Open browser
timeout /t 3 /nobreak >nul
start http://127.0.0.1:8000/docs
start http://127.0.0.1:5173/

echo.
echo ============================================================
echo  HTML_MeetingProtokol started!
echo ============================================================
echo.
echo  Backend:    http://127.0.0.1:8000
echo  API docs:   http://127.0.0.1:8000/docs
echo  Frontend:   http://127.0.0.1:5173/
echo.
echo  To stop:    .\stop.bat
echo.
pause
