@echo off
REM ============================================================
REM install-faster-whisper.bat — install + verify faster-whisper
REM (Russian comment removed for CMD compatibility)
REM
REM (Russian comment removed for CMD compatibility)
REM   "ModuleNotFoundError: No module named 'faster_whisper'"
REM (Russian comment removed for CMD compatibility)
REM
REM (Russian comment removed for CMD compatibility)
REM   cd C:\HTML_Protokol
REM   .\install-faster-whisper.bat
REM
REM (Russian comment removed for CMD compatibility)
REM (Russian comment removed for CMD compatibility)
REM (Russian comment removed for CMD compatibility)
REM (Russian comment removed for CMD compatibility)
REM (Russian comment removed for CMD compatibility)
REM (Russian comment removed for CMD compatibility)
REM
REM (Russian comment removed for CMD compatibility)
REM ============================================================

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM ============================================================
REM 1. Setup: paths, log file, timestamp
REM ============================================================

set "LOG_DIR=logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Generate timestamp YYYY-MM-DD_HH-MM-SS
for /f "tokens=2 delims==" %%a in ('wmic os get localdatetime /value 2^>nul') do set "DATETIME=%%a"
set "TS=!DATETIME:~0,4!-!DATETIME:~4,2!-!DATETIME:~6,2!_!DATETIME:~8,2!-!DATETIME:~10,2!-!DATETIME:~12,2!"
set "LOG_FILE=%LOG_DIR%\install-faster-whisper_!TS!.log"

if exist "code\hmp-backend\.venv\Scripts\python.exe" goto VENV_WIN
goto VENV_NEXT

:VENV_WIN
set "PY=code\hmp-backend\.venv\Scripts\python.exe"
goto VENV_DONE

:VENV_NEXT
if exist "code\hmp-backend\.venv\bin\python" goto VENV_UNIX
goto VENV_DONE

:VENV_UNIX
set "PY=code\hmp-backend\.venv\bin\python"

:VENV_DONE
REM (PY is empty string if no venv found)

echo ============================================================
echo  Install faster-whisper and dependencies
echo ============================================================
echo  Working dir: %CD%
echo  Python venv: %PY%
echo  Log file: %LOG_FILE%
echo ============================================================
echo.

REM Header in log
> "%LOG_FILE%" (
    echo ============================================================
    echo [%TS%] Install started
    echo Working dir: %CD%
    echo Python: %PY%
    echo ============================================================
)

REM ============================================================
REM 2. venv check
REM ============================================================

echo [1/5] Checking venv Python...
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo [1/5] Checking venv Python...

if "%PY%"=="" goto VENV_FAIL
goto VENV_OK

:VENV_FAIL
echo   [ERROR] venv not found!
echo   Run first: .\install-deps-and-run.bat
>> "%LOG_FILE%" echo [ERROR] venv not found
>> "%LOG_FILE%" echo Run first: install-deps-and-run.bat
exit /b 1

:VENV_OK
"%PY%" --version >> "%LOG_FILE%" 2>&1
echo   OK: %PY% reports
echo.

REM ============================================================
REM 3. State BEFORE install
REM ============================================================

echo [2/5] State BEFORE install...
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo [2/5] State BEFORE install:
>> "%LOG_FILE%" echo ----------------------------------------

REM Run check script - records which modules are importable
"%PY%" "code\hmp-backend\scripts\check_whisper_deps.py" --check-only >> "%LOG_FILE%" 2>&1
echo   Logged state to %LOG_FILE%
echo.

REM ============================================================
REM 4. pip install
REM ============================================================

echo [3/5] Installing faster-whisper and ALL deps...
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo [3/5] pip install:
>> "%LOG_FILE%" echo ----------------------------------------

"%PY%" -m pip install --upgrade ^
    "faster-whisper==1.0.3" ^
    "ctranslate2==4.6.0" ^
    "tokenizers>=0.20.0" ^
    "urllib3>=2.0.0" ^
    "requests>=2.31.0" ^
    "huggingface-hub>=0.20.0" ^
    "numpy>=1.24.0" ^
    >> "%LOG_FILE%" 2>&1

set "PIP_EXIT=%ERRORLEVEL%"
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo pip exit code: %PIP_EXIT%

if not "%PIP_EXIT%"=="0" goto PIP_RETRY
goto PIP_DONE

:PIP_RETRY
echo   [WARN] pip failed (exit %PIP_EXIT%), retrying with --trusted-host
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo [WARN] pip failed, retrying with --trusted-host

"%PY%" -m pip install --upgrade ^
    "faster-whisper==1.0.3" ^
    "ctranslate2==4.6.0" ^
    "tokenizers>=0.20.0" ^
    "urllib3>=2.0.0" ^
    "requests>=2.31.0" ^
    "huggingface-hub>=0.20.0" ^
    "numpy>=1.24.0" ^
    --trusted-host pypi.org ^
    --trusted-host files.pythonhosted.org ^
    >> "%LOG_FILE%" 2>&1

set "PIP_EXIT=%ERRORLEVEL%"

if not "%PIP_EXIT%"=="0" goto PIP_FAIL
goto PIP_DONE

:PIP_FAIL
echo.
echo   [ERROR] pip failed again (exit %PIP_EXIT%)!
echo   Check log: %LOG_FILE%
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo [ERROR] pip failed
exit /b 1

:PIP_DONE
echo   Installed.
echo.

REM ============================================================
REM 5. Verification through Python script
REM ============================================================

echo [4/5] Verifying with check_whisper_deps.py...
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo [4/5] Verify:
>> "%LOG_FILE%" echo ----------------------------------------

"%PY%" "code\hmp-backend\scripts\check_whisper_deps.py" >> "%LOG_FILE%" 2>&1
set "VERIFY_EXIT=%ERRORLEVEL%"
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo verify exit code: %VERIFY_EXIT%

if not "%VERIFY_EXIT%"=="0" goto VERIFY_FAIL
echo   OK: all modules importable.
echo.
goto VERIFY_DONE

:VERIFY_FAIL
echo   [ERROR] Some modules failed to import!
echo   See log: %LOG_FILE%
exit /b 1

:VERIFY_DONE

REM ============================================================
REM 6. Smoke test: load tiny model
REM ============================================================

echo [5/5] Smoke test: load tiny model (~30-90 sec on CPU)...
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo [5/5] Smoke test:
>> "%LOG_FILE%" echo ----------------------------------------

"%PY%" "code\hmp-backend\scripts\check_whisper_deps.py" --test-model >> "%LOG_FILE%" 2>&1
set "TEST_EXIT=%ERRORLEVEL%"
>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo test exit code: %TEST_EXIT%

if not "%TEST_EXIT%"=="0" goto TEST_FAIL
echo   OK: model loaded successfully.
goto TEST_DONE

:TEST_FAIL
echo   [WARN] Model load failed (but install is OK)
echo   Run diagnostic: %PY% code\hmp-backend\scripts\check_whisper_deps.py

:TEST_DONE

echo.
echo ============================================================
echo  Install complete.
echo ============================================================
echo  Log: %LOG_FILE%
echo.
echo  Next steps:
echo    1. Run: .\restart.bat
echo    2. Open http://127.0.0.1:8000/docs
echo    3. Try POST /api/v1/hmp/transcribe/run
echo ============================================================

>> "%LOG_FILE%" echo.
>> "%LOG_FILE%" echo Install completed at %TS%

endlocal
