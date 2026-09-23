@echo off
REM Test all API endpoints - run after backend started

chcp 65001 >nul
set PYTHONIOENCODING=utf-8

set "PROJECT_DIR=C:\HTML_Protokol"

REM Use system Python (no venv needed - httpx might not be installed)
python "%PROJECT_DIR%\scripts\test_endpoints.py"

echo.
pause
