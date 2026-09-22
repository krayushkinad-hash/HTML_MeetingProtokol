@echo off
REM Wrapper for fix-install.ps1 (created 2026-09-21)
chcp 65001 >nul
powershell -ExecutionPolicy Bypass -File "%~dp0fix-install.ps1"
