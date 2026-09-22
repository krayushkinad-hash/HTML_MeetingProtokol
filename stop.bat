@echo off
REM ============================================================
REM Stop HTML_MeetingProtokol - kill all processes
REM ============================================================

chcp 65001 >nul

echo.
echo Stopping backend and frontend windows...
echo.

REM Kill uvicorn
taskkill /F /IM uvicorn.exe 2>nul

REM Kill python processes from backend
for /f "tokens=*" %%p in ('wmic process where "name='python.exe' and commandline like '%%hmp-backend%%'" get processid 2^>nul ^| findstr [0-9]') do (
    taskkill /F /PID %%p 2>nul
)

REM Kill anything on port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    taskkill /F /PID %%a 2>nul
)

REM Kill anything on port 5173
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do (
    taskkill /F /PID %%a 2>nul
)

REM Close windows by title
taskkill /FI "WINDOWTITLE eq HMP Backend*" /F 2>nul
taskkill /FI "WINDOWTITLE eq HMP Frontend*" /F 2>nul

echo.
echo Stopped!
echo.
pause
