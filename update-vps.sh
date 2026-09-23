#!/usr/bin/env bash
# Запускать на сервере: /root/update-vps.sh
# Обновляет проект из GitHub + переустанавливает deps + рестарт сервисов

set -e

PROJECT_DIR="/root/HTML_MeetingProtokol"

echo "============================================================"
echo " HMP Update — $(date)"
echo "============================================================"

# 1. Pull latest
echo "[1/5] git pull..."
cd "$PROJECT_DIR"
sudo -u hmp git fetch origin
sudo -u hmp git reset --hard origin/main
echo "  OK"

# 2. Sync frontend
echo "[2/5] Force-refresh frontend..."
chmod +x code/hmp-frontend/force-refresh-frontend.sh
sudo -u hmp ./code/hmp-frontend/force-refresh-frontend.sh || true
echo "  OK"

# 3. Update backend deps
echo "[3/5] pip install --upgrade..."
cd "$PROJECT_DIR/code/hmp-backend"
sudo -u hmp ./.venv/bin/pip install -r requirements-complete.txt --upgrade -q
sudo -u hmp ./.venv/bin/pip install PySocks --upgrade -q
echo "  OK"

# 4. Применить новые миграции
echo "[4/5] Применить миграции..."
for m in scripts/migrations/2026_09_*.py scripts/migrations/2026_10_*.py; do
    if [ -f "$m" ]; then
        sudo -u hmp ./.venv/bin/python "$m" 2>&1 | grep -v "already exists" || true
    fi
done
echo "  OK"

# 5. Restart
echo "[5/5] Restart сервисов..."
systemctl restart hmp-backend
sleep 3

if systemctl is-active --quiet hmp-backend; then
    echo "============================================================"
    echo " ✅ HMP Backend обновлён и работает"
    echo " http://195.133.77.76/"
    echo "============================================================"
else
    echo " ❌ Backend не запустился!"
    echo " journalctl -u hmp-backend -n 50"
    exit 1
fi
