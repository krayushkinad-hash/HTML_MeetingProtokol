#!/usr/bin/env bash
# owasp-zap.sh — Dynamic Application Security Test against the running backend.
#
# Runs OWASP ZAP baseline scan via Docker against the host backend at
# http://host.docker.internal:8000. Generates an HTML report.
#
# Exit codes:
#   0 = no High-Risk alerts
#   1 = High-Risk alerts detected
#   2 = tool missing / backend unreachable
#
# NFR: §14 Threat Model (DAST), OWASP API Top 10 (2023)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
TARGET="${TARGET:-http://host.docker.internal:8000}"
REPORT_HTML="${REPORT_DIR}/zap-baseline-${DATE}.html"
REPORT_JSON="${REPORT_DIR}/zap-baseline-${DATE}.json"

mkdir -p "${REPORT_DIR}"

if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] docker is not installed. Install Docker Engine to run this scan." >&2
    exit 2
fi

# -- Pre-flight: backend reachable? -------------------------------------------
echo "[INFO] Checking backend at ${TARGET}/health..."
if ! curl --max-time 5 --fail --silent "${TARGET}/health" >/dev/null 2>&1 \
   && ! curl --max-time 5 --fail --silent "${TARGET}/" >/dev/null 2>&1; then
    echo "[ERROR] Backend at ${TARGET} is unreachable. Start the stack first:" >&2
    echo "        docker compose up -d  (or)  uvicorn app.main:app --port 8000" >&2
    exit 2
fi

# -- Pull image if missing -----------------------------------------------------
if ! docker image inspect owasp/zap2docker-stable >/dev/null 2>&1; then
    echo "[INFO] Pulling owasp/zap2docker-stable..."
    docker pull owasp/zap2docker-stable
fi

# -- Run baseline scan ---------------------------------------------------------
echo "[INFO] Running OWASP ZAP baseline scan against ${TARGET}..."
echo "[INFO] HTML report -> ${REPORT_HTML}"
echo "[INFO] JSON report -> ${REPORT_JSON}"

set +e
docker run --rm \
    --network host \
    -v "${REPORT_DIR}:/zap/wrk:rw" \
    -t owasp/zap2docker-stable \
    zap-baseline.py \
        -t "${TARGET}" \
        -r "/zap/wrk/$(basename "${REPORT_HTML}")" \
        -J "/zap/wrk/$(basename "${REPORT_JSON}")" \
        -I \
        -m 5
RC=$?
set -e

# ZAP exit codes:
#   0 = no warnings
#   2 = warnings only
#   3 = High-Risk alerts
case "${RC}" in
    0|2)
        echo "[OK] ZAP baseline scan complete (rc=${RC}). No HIGH-risk alerts."
        exit 0
        ;;
    3)
        echo "[WARN] ZAP detected HIGH-risk alerts. See ${REPORT_HTML}" >&2
        exit 1
        ;;
    *)
        echo "[ERROR] ZAP scan failed (rc=${RC}). See ${REPORT_HTML}" >&2
        exit 1
        ;;
esac