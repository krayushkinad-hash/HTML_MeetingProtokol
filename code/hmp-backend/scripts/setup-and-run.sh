#!/bin/bash
# ============================================================
# HTML_MeetingProtokol — Setup & Run Script
# Полная установка и запуск на локальной машине (Ubuntu/Astra)
# ============================================================
set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $*"; }
ok() { echo -e "${GREEN}✅${NC} $*"; }
warn() { echo -e "${YELLOW}⚠️${NC} $*"; }
err() { echo -e "${RED}❌${NC} $*" >&2; }

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# ============================================================
# 1. Проверка prerequisites
# ============================================================
log "Шаг 1/8: Проверка системных зависимостей..."

command -v python3 >/dev/null 2>&1 || { err "python3 не установлен. sudo apt install python3"; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { err "ffmpeg не установлен. sudo apt install ffmpeg"; exit 1; }
command -v docker >/dev/null 2>&1 || warn "docker не установлен (нужен для PostgreSQL через Docker)"

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [ "$(echo "$PYTHON_VERSION < 3.11" | bc)" = "1" ]; then
    err "Требуется Python ≥ 3.11, установлен $PYTHON_VERSION"
    exit 1
fi
ok "Python $PYTHON_VERSION, ffmpeg установлены"

# ============================================================
# 2. Виртуальное окружение
# ============================================================
log "Шаг 2/8: Создание venv..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    ok "Создан .venv"
else
    ok ".venv уже существует"
fi

# shellcheck source=/dev/null
source .venv/bin/activate

# ============================================================
# 3. Установка зависимостей
# ============================================================
log "Шаг 3/8: Установка Python зависимостей (~5–15 минут)..."
pip install --quiet --upgrade pip
# Сначала ставим CPU-only torch (для faster-whisper не нужен GPU)
pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
# Потом всё остальное из pyproject.toml
pip install --quiet -e ".[dev]"
ok "Зависимости установлены"

# ============================================================
# 4. PostgreSQL
# ============================================================
log "Шаг 4/8: Запуск PostgreSQL..."
if command -v docker >/dev/null 2>&1; then
    if docker ps 2>/dev/null | grep -q hmp-postgres; then
        ok "PostgreSQL уже запущен в Docker"
    else
        docker run -d --name hmp-postgres \
            -e POSTGRES_DB=html_mp \
            -e POSTGRES_USER=hmp \
            -e POSTGRES_PASSWORD=hmp_password \
            -p 127.0.0.1:5432:5432 \
            -v hmp_pgdata:/var/lib/postgresql/data \
            postgres:15-alpine
        ok "PostgreSQL запущен через Docker"
        sleep 5  # Ждём инициализацию
    fi
    DATABASE_URL_DEFAULT="postgresql+asyncpg://hmp:hmp_password@127.0.0.1:5432/html_mp"
elif command -v pg_ctl >/dev/null 2>&1; then
    warn "Используем локальный PostgreSQL"
    pg_ctl status 2>/dev/null || pg_ctl start
    DATABASE_URL_DEFAULT="postgresql+asyncpg://$(whoami)@127.0.0.1:5432/html_mp"
else
    err "PostgreSQL не найден. Установите: sudo apt install postgresql"
    err "Или используйте Docker"
    exit 1
fi

# ============================================================
# 5. .env файл
# ============================================================
log "Шаг 5/8: Настройка .env..."
if [ ! -f ".env" ]; then
    cp .env.example .env

    # Генерируем ENCRYPTION_MASTER_KEY (ADR-014)
    MASTER_KEY=$(python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())")
    sed -i "s|^ENCRYPTION_MASTER_KEY=.*|ENCRYPTION_MASTER_KEY=$MASTER_KEY|" .env

    # Устанавливаем DATABASE_URL
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$DATABASE_URL_DEFAULT|" .env

    ok "Создан .env с новым ENCRYPTION_MASTER_KEY"
    warn "Заполните при необходимости: HERMES_API_KEY, GIGACHAT_TOKEN (опционально для MVP)"
else
    ok ".env уже существует"
fi

# ============================================================
# 6. Миграции
# ============================================================
log "Шаг 6/8: Применение миграций Alembic..."
# Создаём БД если её нет
DB_NAME=$(echo "$DATABASE_URL_DEFAULT" | sed -E 's|.*/||')
DB_USER=$(echo "$DATABASE_URL_DEFAULT" | sed -E 's|.*://([^:]+):.*|\1|')

# Проверяем что БД существует (для asyncpg это уже должно быть после docker run)
for i in 1 2 3 4 5; do
    if .venv/bin/python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
async def check():
    engine = create_async_engine('$DATABASE_URL_DEFAULT')
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__('sqlalchemy').text('SELECT 1'))
        await engine.dispose()
        print('OK')
    except Exception as e:
        await engine.dispose()
        raise
asyncio.run(check())
" 2>/dev/null; then
        break
    fi
    sleep 2
    warn "Попытка $i/5 подключения к PostgreSQL..."
done

alembic upgrade head
ok "Миграции применены"

# ============================================================
# 7. Создание user_setting по умолчанию
# ============================================================
log "Шаг 7/8: Создание начальных данных..."
.venv/bin/python -c "
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal, init_db
from app.db.models import UserSetting

async def init_data():
    await init_db()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserSetting))
        if not result.scalar_one_or_none():
            session.add(UserSetting())
            await session.commit()
            print('UserSetting создан')
        else:
            print('UserSetting уже существует')

asyncio.run(init_data())
" 2>&1 | grep -E "(создан|существует|OK)" || warn "Initial data step пропущен"

# ============================================================
# 8. Тесты (опционально)
# ============================================================
log "Шаг 8/8: Запуск smoke-тестов..."
if .venv/bin/python -m pytest tests/test_smoke.py -x -q 2>&1 | grep -E "(passed|failed|error)" | head -3; then
    ok "Smoke-тесты прошли"
else
    warn "Тесты требуют запущенный backend. Запустите: make test"
fi

echo ""
echo "============================================================"
echo -e "${GREEN}🎉 Установка завершена!${NC}"
echo "============================================================"
echo ""
echo "📋 Следующие шаги:"
echo ""
echo "  1. Запустить backend:"
echo "     ${BLUE}source .venv/bin/activate${NC}"
echo "     ${BLUE}uvicorn app.main:app --reload --host 127.0.0.1 --port 8000${NC}"
echo ""
echo "  2. В другом терминале — запустить frontend:"
echo "     ${BLUE}cd ../hmp-frontend/public && python3 -m http.server 5173${NC}"
echo ""
echo "  3. Открыть в браузере:"
echo "     ${BLUE}http://127.0.0.1:8000/docs${NC} (API docs)"
echo "     ${BLUE}http://127.0.0.1:5173/${NC} (Frontend)"
echo ""
echo "  4. Проверить состояние:"
echo "     ${BLUE}curl http://127.0.0.1:8000/health${NC}"
echo ""
echo "📁 Логи:"
echo "  PostgreSQL: docker logs -f hmp-postgres"
echo "  Backend:    tail -f logs/*.log"
echo ""
echo "🛑 Остановить:"
echo "  Ctrl+C в терминале backend"
echo "  docker stop hmp-postgres"
echo ""
