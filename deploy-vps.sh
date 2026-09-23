#!/usr/bin/env bash
# ============================================================
# HTML_MeetingProtokol — Ubuntu VPS Deploy Script
# ============================================================
# Запускать от root: ./deploy-vps.sh
# Тестировано: Ubuntu 22.04/24.04/26.04
# ============================================================

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_DIR="/root/HTML_MeetingProtokol"
SERVICE_USER="hmp"
BACKEND_PORT=8000
FRONTEND_PORT=5173

echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN} HTML_MeetingProtokol — VPS Deploy${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""

# ============================================================
# 0. Проверка ОС
# ============================================================
echo -e "${YELLOW}[0/9] Проверка ОС...${NC}"
if ! grep -q "Ubuntu" /etc/os-release; then
    echo -e "${RED}Только Ubuntu поддерживается${NC}"
    exit 1
fi
. /etc/os-release
echo "  OS: ${PRETTY_NAME}"
echo "  Kernel: $(uname -r)"
echo ""

# ============================================================
# 1. Обновление системы
# ============================================================
echo -e "${YELLOW}[1/9] apt update && apt upgrade...${NC}"
apt update -qq
apt upgrade -y -qq
apt install -y -qq \
    software-properties-common \
    build-essential \
    git \
    curl \
    wget \
    htop \
    nano \
    nginx \
    postgresql \
    postgresql-contrib \
    ffmpeg \
    ca-certificates \
    gnupg \
    lsb-release
echo -e "${GREEN}  OK${NC}"
echo ""

# ============================================================
# 2. Python 3.12+
# ============================================================
echo -e "${YELLOW}[2/9] Установка Python 3.12...${NC}"
if ! command -v python3.12 &> /dev/null; then
    add-apt-repository -y ppa:deadsnakes/ppa
    apt update -qq
    apt install -y -qq python3.12 python3.12-venv python3.12-dev python3.12-distutils
fi
PYTHON=python3.12
echo "  $(python3.12 --version)"
echo ""

# ============================================================
# 3. Пользователь hmp (без root-доступа)
# ============================================================
echo -e "${YELLOW}[3/9] Создание пользователя hmp...${NC}"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$SERVICE_USER"
    echo "  Создан: $SERVICE_USER"
fi
echo -e "${GREEN}  OK${NC}"
echo ""

# ============================================================
# 4. PostgreSQL
# ============================================================
echo -e "${YELLOW}[4/9] Настройка PostgreSQL...${NC}"
systemctl start postgresql
systemctl enable postgresql
sleep 2

# Создание БД и пользователя (если ещё нет)
sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename = 'hmp'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER hmp WITH PASSWORD 'hmp_password' SUPERUSER;"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'html_mp'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE html_mp OWNER hmp;"

echo -e "${GREEN}  PostgreSQL готов: postgresql://hmp:hmp_password@127.0.0.1:5432/html_mp${NC}"
echo ""

# ============================================================
# 5. Копирование/обновление проекта
# ============================================================
echo -e "${YELLOW}[5/9] Копирование проекта...${NC}"
if [ ! -d "$PROJECT_DIR" ]; then
    # Если папки нет — клонируем из вашего GitHub
    echo "  Папка не найдена, клонирую из GitHub..."
    sudo -u "$SERVICE_USER" git clone https://github.com/krayushkinad-hash/HTML_MeetingProtokol.git "$PROJECT_DIR"
else
    echo "  Папка существует: $PROJECT_DIR"
    sudo -u "$SERVICE_USER" bash -c "cd $PROJECT_DIR && git pull origin main 2>/dev/null || true"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$PROJECT_DIR"
echo -e "${GREEN}  OK${NC}"
echo ""

# ============================================================
# 6. Backend: venv + зависимости + миграции
# ============================================================
echo -e "${YELLOW}[6/9] Backend venv + pip + миграции...${NC}"
sudo -u "$SERVICE_USER" bash << EOF
set -e
cd $PROJECT_DIR/code/hmp-backend

# Создаём venv если нет
if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
fi

# Активируем и устанавливаем
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements-complete.txt -q
pip install PySocks -q
echo "  Все Python пакеты установлены"

# .env файл
if [ ! -f ".env" ]; then
    cp .env.example .env
    # Генерируем SECRET_KEY
    SK="\$(openssl rand -hex 32)"
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=\$SK|" .env
    echo "  .env создан (SECRET_KEY сгенерирован)"
fi

# Применяем миграции
for m in scripts/migrations/2026_09_2*.py; do
    if [ -f "\$m" ]; then
        \$m 2>/dev/null || true
    fi
done
echo "  Миграции применены"
EOF
echo -e "${GREEN}  OK${NC}"
echo ""

# ============================================================
# 7. systemd сервис для backend
# ============================================================
echo -e "${YELLOW}[7/9] systemd сервис для backend...${NC}"
cat > /etc/systemd/system/hmp-backend.service << EOF
[Unit]
Description=HMP FastAPI Backend
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR/code/hmp-backend
Environment="PATH=$PROJECT_DIR/code/hmp-backend/.venv/bin:/usr/bin"
Environment="PROTOCOL_PATH=$PROJECT_DIR/storage/protocols"
Environment="NO_PROXY=*"
ExecStart=$PROJECT_DIR/code/hmp-backend/.venv/bin/uvicorn app.main:app \\
    --host 0.0.0.0 --port $BACKEND_PORT --workers 1 \\
    --log-level info

Restart=always
RestartSec=10

StandardOutput=append:/var/log/hmp-backend.log
StandardError=append:/var/log/hmp-backend.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hmp-backend
systemctl start hmp-backend
sleep 3

if systemctl is-active --quiet hmp-backend; then
    echo -e "${GREEN}  Backend запущен на http://0.0.0.0:$BACKEND_PORT${NC}"
else
    echo -e "${RED}  Backend не запустился! Проверьте: journalctl -u hmp-backend -n 50${NC}"
fi
echo ""

# ============================================================
# 8. nginx: проксирование
# ============================================================
echo -e "${YELLOW}[8/9] nginx (фронт + прокси на :8000)...${NC}"
cat > /etc/nginx/sites-available/hmp << EOF
# Бэкенд
location /api/ {
    proxy_pass http://127.0.0.1:$BACKEND_PORT;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";

    # Большие файлы
    client_max_body_size 8192M;
    proxy_read_timeout 86400;
    proxy_send_timeout 86400;
}

# Фронтенд (Vanilla JS)
location / {
    root $PROJECT_DIR/code/hmp-frontend/public;
    try_files \$uri \$uri/ /index.html;

    # Без кеша для index.html
    location = /index.html {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        add_header Expires "0";
    }

    location ~* \.(js|css)\$ {
        add_header Cache-Control "no-cache";
    }
}
EOF

ln -sf /etc/nginx/sites-available/hmp /etc/nginx/sites-enabled/hmp
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo -e "${GREEN}  nginx настроен${NC}"
echo ""

# ============================================================
# 9. Firewall
# ============================================================
echo -e "${YELLOW}[9/9] Firewall...${NC}"
if command -v ufw &> /dev/null; then
    ufw allow 80/tcp 2>/dev/null || true
    ufw allow 443/tcp 2>/dev/null || true
    ufw allow $FRONTEND_PORT/tcp 2>/dev/null || true
    ufw allow $BACKEND_PORT/tcp 2>/dev/null || true
    echo -e "${GREEN}  Порты 80, 443, 8000, 5173 открыты${NC}"
fi
echo ""

# ============================================================
# Done
# ============================================================
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN} DEPLOY COMPLETE${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""
echo -e "  Frontend:    http://195.133.77.76/"
echo -e "  Backend API: http://195.133.77.76/api/v1/hmp/"
echo -e "  API docs:    http://195.133.77.76/api/v1/hmp/docs"
echo ""
echo -e "  Логи backend: tail -f /var/log/hmp-backend.log"
echo -e "  Логи systemd: journalctl -u hmp-backend -f"
echo ""
echo -e "  ${YELLOW}Скачать модель Whisper:${NC}"
echo -e "  curl -X POST http://195.133.77.76/api/v1/hmp/whisper/download/base"
echo ""
