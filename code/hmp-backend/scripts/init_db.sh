#!/bin/bash
# Initialize database with Alembic migrations
# Usage: ./scripts/init_db.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "📦 Activating virtual environment..."
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "🗄️  Running Alembic migrations..."
alembic upgrade head

echo "✅ Database initialized successfully"
echo ""
echo "Tables created:"
psql "${DATABASE_URL}" -c "\dt" 2>/dev/null || echo "(psql not available, but migrations applied)"
