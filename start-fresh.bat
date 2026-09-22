@echo off
REM ============================================================
REM start-fresh.bat -- DROP -> CREATE -> start backend с миграцией
REM ============================================================

setlocal

REM Остановить backend
call kill-all-nuclear.bat >nul 2>&1

REM Запустить PostgreSQL
docker start hmp-postgres >nul 2>&1
timeout /t 3 /nobreak >nul

REM Сбросить БД
echo [start-fresh] Удаляем базу html_mp...
docker exec hmp-postgres psql -U hmp -d postgres -c "DROP DATABASE IF EXISTS html_mp WITH (FORCE);"
if errorlevel 1 (
    echo [start-fresh] FAIL: DROP DATABASE
    exit /b 1
)

echo [start-fresh] Создаём базу html_mp...
docker exec hmp-postgres psql -U hmp -d postgres -c "CREATE DATABASE html_mp OWNER hmp;"
if errorlevel 1 (
    echo [start-fresh] FAIL: CREATE DATABASE
    exit /b 1
)

REM Стартуем backend (init_db() применит миграцию)
echo [start-fresh] Запускаем backend с миграцией...
start.bat

endlocal
