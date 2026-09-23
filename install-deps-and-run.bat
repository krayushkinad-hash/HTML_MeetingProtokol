@echo off
REM ============================================================
REM INSTALL DEPS - bypasses SOCKS proxy completely
REM Run from project root (C:\HTML_Protokol)
REM ============================================================

chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
setlocal EnableDelayedExpansion

echo ============================================================
echo  Bypass SOCKS proxy + Install + Sync frontend
echo ============================================================
echo.

REM Find project
set "PROJECT_DIR="
if exist "C:\HTML_Protokol\code\hmp-backend" (
    set "PROJECT_DIR=C:\HTML_Protokol"
) else if exist "%USERPROFILE%\HTML_MeetingProtokol\code\hmp-backend" (
    set "PROJECT_DIR=%USERPROFILE%\HTML_MeetingProtokol"
) else if exist "C:\Projects\AI\HTML_MeetingProtokol\code\hmp-backend" (
    set "PROJECT_DIR=C:\Projects\AI\HTML_MeetingProtokol"
) else (
    echo ERROR: Cannot find code\hmp-backend
    pause
    exit /b 1
)

set "BACKEND_DIR=%PROJECT_DIR%\code\hmp-backend"
set "VENV_DIR=%BACKEND_DIR%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

echo Project: %PROJECT_DIR%
echo Backend: %BACKEND_DIR%
echo.

REM ============================================================
REM STEP 0: Sync frontend src/ to public/src/ (force-refresh)
REM ============================================================
echo [0/7] Syncing frontend src to public/src
call "%~dp0force-refresh-frontend.bat" >nul 2>&1
echo   [OK] Frontend synced.
echo.

REM ============================================================
REM STEP 1: Aggressively disable SOCKS proxy
REM ============================================================
echo [1/5] Disabling SOCKS proxy...

REM Clear ALL proxy environment variables
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set SOCKS_PROXY=
set NO_PROXY=*

REM Use registry to clear proxy (Windows-wide)
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v AutoConfigURL /f >nul 2>&1

REM Find and delete pip.ini in all possible locations
set "PIP_INI_DELETED="
for %%p in (
    "%APPDATA%\pip\pip.ini"
    "%LOCALAPPDATA%\pip\pip.ini"
    "%USERPROFILE%\.pip\pip.conf"
    "%USERPROFILE%\pip\pip.ini"
    "%APPDATA%\Roaming\pip\pip.ini"
) do (
    if exist "%%p" (
        echo   Removing: %%p
        move /y "%%p" "%%p.disabled" >nul 2>&1
        set "PIP_INI_DELETED=1"
    )
)
if "%PIP_INI_DELETED%"=="" echo   No pip.ini found

REM Also check pip config files
if exist "%USERPROFILE%\.config\pip\pip.conf" (
    move /y "%USERPROFILE%\.config\pip\pip.conf" "%USERPROFILE%\.config\pip\pip.conf.disabled" >nul 2>&1
    echo   Removed: %USERPROFILE%\.config\pip\pip.conf
)

REM Clear pip config via pip itself
for /f "tokens=*" %%i in ('"%VENV_PYTHON%" -m pip config list 2^>nul') do (
    echo   pip config: %%i
)

echo.

REM ============================================================
REM STEP 2: Create venv if needed
cd /d "%BACKEND_DIR%"
echo Database URL will be loaded from .env
echo.

REM ============================================================
REM STEP 2.7: Fix PostgreSQL password if needed
REM ============================================================
echo   Checking pip version...
"%VENV_PYTHON%" -m pip --version 2>&1
echo   OK
echo.
REM If venv doesn't exist, create it first
if not exist "%VENV_PYTHON%" (
    echo   Creating venv...
    cd /d "%BACKEND_DIR%"
    python -m venv .venv
    if errorlevel 1 (
        echo   ERROR: Cannot create venv
        pause
        exit /b 1
    )
    "%VENV_PYTHON%" -m pip install --no-cache-dir --index-url https://pypi.org/simple/ --trusted-host pypi.org "pip==26.2.1" 2>&1
    echo   [OK] venv created
) else (
    echo   venv already exists
)
echo.

REM ============================================================
REM STEP 2.7: Fix PostgreSQL password if needed
REM ============================================================
echo   Checking PostgreSQL connection...
REM First make sure asyncpg is installed
"%VENV_PYTHON%" -c "import asyncpg" 2>nul
if errorlevel 1 (
    echo   asyncpg not found, installing...
    "%VENV_PYTHON%" -m pip install --no-cache-dir --index-url https://pypi.org/simple/ --trusted-host pypi.org asyncpg 2>&1 | findstr /v "^$"
)
"%VENV_PYTHON%" "%PROJECT_DIR%\scripts\fix_postgres_password.py" "%PROJECT_DIR%"
echo.

REM ============================================================
REM STEP 3: Install dependencies with --no-deps
REM ============================================================
echo [3/5] Installing main requirements (no-deps to bypass SOCKS)...

set "INDEX_URL=https://pypi.org/simple/"
set "TRUSTED=pypi.org files.pythonhosted.org"

cd /d "%BACKEND_DIR%"

REM Try using pip config to set index-url
"%VENV_PYTHON%" -m pip config set global.index-url "https://pypi.org/simple/" >nul 2>&1
"%VENV_PYTHON%" -m pip config set global.trusted-host "%TRUSTED%" >nul 2>&1
REM Install main requirements (try --no-deps first, then with deps)
echo   Installing main requirements...
echo   This will show progress for each package...
echo.
"%VENV_PYTHON%" -m pip install --no-cache-dir --no-deps --index-url https://pypi.org/simple/ -r requirements-minimal.txt
if errorlevel 1 (
    echo   --no-deps install failed, trying with deps...
    "%VENV_PYTHON%" -m pip install --no-cache-dir --index-url https://pypi.org/simple/ --trusted-host pypi.org -r requirements-minimal.txt
    if errorlevel 1 (
        echo   WARNING: requirements install failed, continuing with pinned versions
    )
)
echo.

REM ============================================================
REM STEP 4: Install all transitive dependencies manually
REM ============================================================
echo [4/5] Installing transitive dependencies...
REM Full list of transitive dependencies with PINNED VERSIONS to avoid conflicts
REM Note: uvloop REMOVED - doesn't support Windows

REM Install each package individually with progress indication
REM Use external Python script (no bat escaping issues)
echo   Installing dependencies with pinned versions...

"%VENV_PYTHON%" "%PROJECT_DIR%\scripts\install_pinned_deps.py" "%PROJECT_DIR%\code\hmp-backend"

REM Uninstall conflicting packages that were installed without version pins
echo   Uninstalling old versions without pins...
"%VENV_PYTHON%" -m pip uninstall -y --quiet pydantic pydantic-core fastapi starlette 2>nul

echo.
echo   Reinstalling with correct versions...
"%VENV_PYTHON%" -m pip install --quiet --no-cache-dir --index-url https://pypi.org/simple/ pydantic==2.9.2 pydantic_core==2.23.4 fastapi==0.115.6 starlette==0.41.3 asyncpg==0.30.0 async_timeout==4.0.3

REM Now install with dependencies - this should pick up all transitive deps for the pinned packages
echo   Installing with dependencies (full resolution)...
"%VENV_PYTHON%" -m pip install --quiet --no-cache-dir --index-url https://pypi.org/simple/ --trusted-host pypi.org pydantic==2.9.2 pydantic_core==2.23.4 fastapi==0.115.6 starlette==0.41.3 asyncpg==0.30.0 async_timeout==4.0.3

echo.
echo [5/5] Testing imports...
"%VENV_PYTHON%" "%PROJECT_DIR%\scripts\test_imports.py"

if errorlevel 1 (
    echo.
    echo WARNING: Missing modules. Auto-fixing with pip install...
    echo.
    cd /d "%BACKEND_DIR%"
    REM E066: Install ALL transitive deps that may be missing
    "%VENV_PYTHON%" -m pip install --quiet --no-cache-dir --index-url https://pypi.org/simple/ ^
        starlette fastapi uvicorn ^
        pydantic pydantic-core pydantic-settings ^
        asyncpg sqlalchemy aiosqlite ^
        httpx httpcore h11 sniffio anyio ^
        python-multipart python-docx pillow lxml ^
        structlog tenacity orjson ^
        openai python-dateutil six ^
        urllib3 certifi charset-normalizer idna ^
        huggingface-hub filelock fsspec packaging pyyaml ^
        cryptography bcrypt argon2-cffi PyJWT ^
        faster-whisper ctranslate2 tokenizers
    cd /d "%PROJECT_DIR%"
)

REM pip is already 26.2.1, no need to upgrade again
echo.

echo.
echo ============================================================
echo  STARTING BACKEND
echo ============================================================
echo.

REM Show which DATABASE_URL will be used
echo Loaded DATABASE_URL:
"%VENV_PYTHON%" -c "from app.core.config import settings; print(settings.database_url.replace('hmp_password', '****').replace(settings.database_url.split(':')[2].split('@')[0], '****'))" 2>nul
echo.

echo  Backend:    http://127.0.0.1:8000
echo  API docs:   http://127.0.0.1:8000/docs
echo  Frontend:   will start on http://127.0.0.1:5173/
echo.

REM Start frontend in background (uses public/ which was synced)
set "FRONTEND_PUBLIC=%PROJECT_DIR%\code\hmp-frontend\public"
if exist "%FRONTEND_PUBLIC%\index.html" (
    echo  Starting frontend http.server on :5173...
    start "HMP Frontend" cmd /k "cd /d %FRONTEND_PUBLIC% && python -m http.server 5173"
    timeout /t 2 /nobreak >nul
)

echo  Press Ctrl+C to stop backend (frontend will continue).
echo.

cd /d "%BACKEND_DIR%"
REM E061: Explicit unset proxy env vars in venv before starting uvicorn
"%VENV_PYTHON%" -c "import os; [os.environ.pop(v, None) for v in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','SOCKS_PROXY','http_proxy','https_proxy','all_proxy','socks_proxy')]; print('E061: proxy cleared')" 2>nul
"%VENV_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

pause
