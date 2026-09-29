#!/usr/bin/env bash
# pip-audit.sh — Dependency vulnerability scan for hmp-backend
#
# Scans Python dependencies against the PyPI Advisory Database
# and writes a JSON report to security/reports/pip-audit-YYYY-MM-DD.json
#
# Exit codes:
#   0 = no known vulnerabilities found
#   1 = vulnerabilities found
#   2 = tool missing / setup error
#
# NFR: §14 Threat Model (supply chain)
# ADR: §14 (Python deps via pip-audit)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
REPORT_FILE="${REPORT_DIR}/pip-audit-${DATE}.json"

mkdir -p "${REPORT_DIR}"

# -- Tool detection ------------------------------------------------------------
if ! command -v pip-audit >/dev/null 2>&1; then
    cat >&2 <<'EOF'
[ERROR] pip-audit is not installed.

Install one of:
  pip install --user pip-audit
  pipx install pip-audit
  uv tool install pip-audit

Or run security/safety.sh as a fallback (uses the `safety` package).
EOF
    exit 2
fi

# -- Optional: detect requirement files ---------------------------------------
REQ_ARGS=()
if [[ -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
    REQ_ARGS+=("-r" "${PROJECT_ROOT}/pyproject.toml")
fi
if [[ -f "${PROJECT_ROOT}/requirements.txt" ]]; then
    REQ_ARGS+=("-r" "${PROJECT_ROOT}/requirements.txt")
fi
if [[ -f "${PROJECT_ROOT}/requirements.lock" ]]; then
    REQ_ARGS+=("-r" "${PROJECT_ROOT}/requirements.lock")
fi

if [[ ${#REQ_ARGS[@]} -eq 0 ]]; then
    echo "[WARN] No pyproject.toml / requirements*.txt found in ${PROJECT_ROOT}" >&2
    echo "[WARN] Falling back to scanning the currently-installed environment." >&2
    REQ_ARGS=()
fi

# -- Run scan ------------------------------------------------------------------
echo "[INFO] Running pip-audit against hmp-backend dependencies..."
echo "[INFO] Report -> ${REPORT_FILE}"

set +e
pip-audit \
    --format json \
    --output "${REPORT_FILE}" \
    "${REQ_ARGS[@]}"
RC=$?
set -e

# Normalize rc (pip-audit returns the count of vulnerable pkgs, capped)
case "${RC}" in
    0)
        echo "[OK] No known vulnerabilities."
        exit 0
        ;;
    1)
        echo "[WARN] Vulnerabilities found. See ${REPORT_FILE}" >&2
        exit 1
        ;;
    *)
        echo "[ERROR] pip-audit failed (rc=${RC}). See ${REPORT_FILE}" >&2
        exit 1
        ;;
esac