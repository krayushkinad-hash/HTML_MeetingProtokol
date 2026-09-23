#!/usr/bin/env bash
# Синхронизировать src/ → public/src/ (для VPS)

set -e
FRONTEND_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$FRONTEND_DIR/src" ]; then
    echo "  [SKIP] src/ not found: $FRONTEND_DIR/src"
    exit 0
fi

cd "$FRONTEND_DIR"

# Копируем актуальные файлы
cp -r src/* public/src/ 2>/dev/null || true

echo "Frontend synced: src/ → public/src/"
