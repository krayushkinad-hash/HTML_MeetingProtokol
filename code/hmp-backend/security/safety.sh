#!/usr/bin/env bash
# safety.sh — Fallback dependency vulnerability scanner (uses `safety`).
#
# Use this when pip-audit is unavailable. Reports go to
# security/reports/safety-YYYY-MM-DD.json
#
# Exit codes:
#   0 = no known vulnerabilities
#   1 = vulnerabilities found
#   2 = tool missing
#
# NFR: §14 Threat Model (supply chain)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
REPORT_FILE="${REPORT_DIR}/safety-${DATE}.json"

mkdir -p "${REPORT_DIR}"

if ! command -v safety >/dev/null 2>&1; then
    cat >&2 <<'EOF'
[ERROR] `safety` is not installed.

Install:
  pip install --user safety
  pipx install safety

Note: safety 3.x requires an API key for the full database. You can also
run security/pip-audit.sh instead (PyPI Advisory DB, no key needed).
EOF
    exit 2
fi

REQ_ARGS=()
if [[ -f "${PROJECT_ROOT}/requirements.txt" ]]; then
    REQ_ARGS+=("--file" "${PROJECT_ROOT}/requirements.txt")
elif [[ -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
    echo "[INFO] pyproject.toml found — scanning the live environment." >&2
fi

echo "[INFO] Running safety check..."
echo "[INFO] Report -> ${REPORT_FILE}"

set +e
# `safety check --json` writes a JSON report to stdout in safety 2.x; in 3.x
# the API-key-less command is `safety scan --output json`.
if safety --version 2>/dev/null | awk -F. '{ if ($1 >= 3) exit 0; else exit 1 }'; then
    safety scan --output json "${REQ_ARGS[@]}" >"${REPORT_FILE}" 2>&1
else
    safety check --json "${REQ_ARGS[@]}" >"${REPORT_FILE}" 2>&1 || true
fi
RC=$?
set -e

case "${RC}" in
    0)
        echo "[OK] No known vulnerabilities (safety)."
        exit 0
        ;;
    64|65)
        echo "[WARN] Vulnerabilities reported. See ${REPORT_FILE}" >&2
        exit 1
        ;;
    *)
        echo "[ERROR] safety exited with ${RC}. See ${REPORT_FILE}" >&2
        exit 1
        ;;
esac