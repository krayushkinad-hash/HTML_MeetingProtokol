@echo off
REM ============================================================
REM NUCLEAR OPTION - kill ALL python and restart cleanly
REM ============================================================

chcp 65001 >nul

echo ============================================================
echo  KILLING ALL PYTHON PROCESSES
echo ============================================================
echo.

REM Kill ALL python processes
echo Killing all python.exe...
taskkill /F /IM python.exe 2>nul

REM Kill uvicorn
echo Killing uvicorn.exe...
taskkill /F /IM uvicorn.exe 2>nul

REM Kill anything on port 5173 (frontend)
echo Killing port 5173...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do (
    taskkill /F /PID %%a 2>nul
)

REM Kill anything on port 8000 (backend)
echo Killing port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    taskkill /F /PID %%a 2>nul
)

REM Close all cmd windows with HMP in title
taskkill /FI "WINDOWTITLE eq HMP*" /F 2>nul

echo.
echo All processes killed.
echo.
echo Waiting 3 seconds...
timeout /t 3 /nobreak >nul

REM Verify nothing is listening on 5173 and 8000
echo.
echo Checking ports are free...
netstat -ano | findstr :5173 >nul 2>&1
if errorlevel 1 (
    echo Port 5173 is FREE
) else (
    echo WARNING: Port 5173 still BUSY
)

netstat -ano | findstr :8000 >nul 2>&1
if errorlevel 1 (
    echo Port 8000 is FREE
) else (
    echo WARNING: Port 8000 still BUSY
)

echo.
echo ============================================================
echo  Now run restart.bat
echo ============================================================
echo.
pause
