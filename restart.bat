@echo off
REM ============================================================
REM restart.bat - Full restart with frontend auto-sync
REM ============================================================
REM
REM Pipeline:
REM   1. Sync src/ -> public/src/ (force-refresh-frontend.bat)
REM   2. Kill all Python processes
REM   3. Verify venv + dependencies
REM   4. Start PostgreSQL + backend + frontend
REM   5. Open browser
REM
REM IMPORTANT: After ANY changes in code/hmp-frontend/src/,
REM just run this script. It will auto-copy fresh files
REM before starting servers.
REM ============================================================

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


setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PROJECT_DIR=%CD%"

echo ============================================================
echo  HTML_MeetingProtokol - Full Restart
echo ============================================================
echo  Time: %date% %time%
echo  Dir:  %PROJECT_DIR%
echo ============================================================
echo.

REM ============================================================
REM STEP 0/4: Sync frontend src/ to public/src/ (force-refresh)
REM ============================================================
echo [0/4] Syncing frontend src to public/src

set "FRONTEND_DIR=%PROJECT_DIR%\code\hmp-frontend"
set "PUBLIC_DIR=%FRONTEND_DIR%\public"

if not exist "%FRONTEND_DIR%\src" goto SKIP_SYNC
REM Call dedicated script (avoids nested if/else + redirect parsing)
call "%PROJECT_DIR%\force-refresh-frontend.bat"
goto SYNC_DONE

:SKIP_SYNC
echo   [SKIP] src/ not found: %FRONTEND_DIR%\src

:SYNC_DONE
echo.
echo.

REM ============================================================
REM STEP 1/4: Kill all processes
REM ============================================================
echo [1/4] Killing all processes...

REM Kill ALL python
taskkill /F /IM python.exe 2>nul

REM Kill uvicorn
taskkill /F /IM uvicorn.exe 2>nul

REM Kill anything on port 8000 (backend)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    taskkill /F /PID %%a 2>nul
)

REM Kill anything on port 5173 (frontend)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do (
    taskkill /F /PID %%a 2>nul
)

REM Close windows by title
taskkill /FI "WINDOWTITLE eq HMP Backend*" /F 2>nul
taskkill /FI "WINDOWTITLE eq HMP Frontend*" /F 2>nul

echo   All processes killed.
timeout /t 2 /nobreak >nul
echo.

REM ============================================================
REM STEP 2/4: Check venv and uvicorn
REM ============================================================
echo [2/4] Checking venv...

set "BACKEND_DIR=%PROJECT_DIR%\code\hmp-backend"
set "VENV_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "VENV_UVICORN=%BACKEND_DIR%\.venv\Scripts\uvicorn.exe"

if not exist "%VENV_PYTHON%" (
    echo.
    echo   [ERROR] venv not found at %VENV_PYTHON%
    echo   Run install-deps-and-run.bat first
    echo.
    pause
    exit /b 1
)

if not exist "%VENV_UVICORN%" (
    echo.
    echo   [ERROR] uvicorn.exe not found
    echo   Run install-deps-and-run.bat to install dependencies
    echo.
    pause
    exit /b 1
)

if not exist "%PUBLIC_DIR%\index.html" (
    echo.
    echo   [ERROR] index.html not found in %PUBLIC_DIR%
    echo   Run install-deps-and-run.bat first
    echo.
    pause
    exit /b 1
)

echo   All checks passed.
echo.

REM ============================================================
REM STEP 3/4: Start backend + frontend
REM ============================================================
echo [3/4] Starting services...

REM Start PostgreSQL
docker --version >nul 2>&1
if not errorlevel 1 (
    echo   Starting PostgreSQL...
    docker start hmp-postgres >nul 2>&1
)

REM Start backend
echo   Starting backend on http://127.0.0.1:8000...
REM E061: Unset proxy env vars BEFORE starting uvicorn
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set SOCKS_PROXY=
set http_proxy=
set https_proxy=
set all_proxy=
set socks_proxy=

start "HMP Backend" cmd /k "cd /d %BACKEND_DIR% && %VENV_UVICORN% app.main:app --reload --host 127.0.0.1 --port 8000"

timeout /t 5 /nobreak >nul

REM Start frontend (serve public/ which now has both index.html and src/)
echo   Starting frontend on http://127.0.0.1:5173...
start "HMP Frontend" cmd /k "cd /d %PUBLIC_DIR% && python -m http.server 5173"

timeout /t 3 /nobreak >nul
echo.

REM ============================================================
REM STEP 4/4: Open browser
REM ============================================================
echo [4/4] Opening browser...
start http://127.0.0.1:8000/docs
start http://127.0.0.1:5173/

echo.
echo ============================================================
echo  Restart complete!
echo ============================================================
echo.
echo  Backend:    http://127.0.0.1:8000
echo  API docs:   http://127.0.0.1:8000/docs
echo  Frontend:   http://127.0.0.1:5173/
echo.
echo  To stop:    .\stop.bat
echo.
echo  After any src/ changes: just .\restart.bat
echo ============================================================
echo.

endlocal
pause
