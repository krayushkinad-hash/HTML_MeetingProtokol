#!/usr/bin/env bash
# bandit.sh — Python static security analysis for app/.
#
# Reports JSON to security/reports/bandit-YYYY-MM-DD.json
# Filters to medium severity and above (--severity-level medium).
#
# Exit codes:
#   0 = no medium+ issues
#   1 = issues found
#   2 = tool missing
#
# NFR: §14 Threat Model (SAST)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
REPORT_FILE="${REPORT_DIR}/bandit-${DATE}.json"

mkdir -p "${REPORT_DIR}"

if ! command -v bandit >/dev/null 2>&1; then
    cat >&2 <<'EOF'
[ERROR] bandit is not installed.

Install:
  pip install --user bandit
  pipx install bandit

Or add to dev deps:
  pip install -e '.[dev]'
EOF
    exit 2
fi

APP_DIR="${PROJECT_ROOT}/app"
if [[ ! -d "${APP_DIR}" ]]; then
    echo "[ERROR] app/ directory not found at ${APP_DIR}" >&2
    exit 2
fi

echo "[INFO] Running bandit on ${APP_DIR} (medium+ severity)..."
echo "[INFO] Report -> ${REPORT_FILE}"

set +e
bandit -r "${APP_DIR}" \
    --severity-level medium \
    --confidence-level medium \
    --format json \
    --output "${REPORT_FILE}" \
    --quiet
RC=$?
set -e

# bandit returns:
#   0 = no issues
#   1 = issues found
#   2..N = error / config problem
case "${RC}" in
    0)
        echo "[OK] bandit: no medium+ issues."
        exit 0
        ;;
    1)
        echo "[WARN] bandit found medium+ issues. See ${REPORT_FILE}" >&2
        exit 1
        ;;
    *)
        echo "[ERROR] bandit failed (rc=${RC}). See ${REPORT_FILE}" >&2
        exit 2
        ;;
esac