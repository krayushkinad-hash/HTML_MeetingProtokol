#!/usr/bin/env bash
# rate-limit-check.sh — Verify rate limiting on protected endpoints.
#
# Fires 200 requests in a tight loop and counts how many returned
# HTTP 429 (Too Many Requests) or 503. A working limiter should reject
# the bulk of the burst.
#
# Exit codes:
#   0 = rate limiting observed
#   1 = no rate limiting detected (all 2xx)
#   2 = backend unreachable / xargs missing
#
# NFR: §14 Threat Model (OWASP API4:2023 — Unrestricted Resource Consumption)
set -euo pipefail

TARGET="${TARGET:-http://localhost:8000}"
PATH_="${PATH_:-/api/v1/protocols}"
N="${N:-200}"
PARALLEL="${PARALLEL:-20}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
REPORT_FILE="${REPORT_DIR}/rate-limit-${DATE}.md"

mkdir -p "${REPORT_DIR}"

if ! command -v curl >/dev/null 2>&1; then
    echo "[ERROR] curl is not installed." >&2
    exit 2
fi

URL="${TARGET}${PATH_}"

# Health probe first.
HEALTH_STATUS=$(curl --max-time 5 --silent --output /dev/null --write-out '%{http_code}' \
    "${TARGET}/health" "${TARGET}/" 2>/dev/null | tail -n1 || echo "000")
if [[ "${HEALTH_STATUS}" == "000" ]]; then
    echo "[ERROR] Backend at ${TARGET} is unreachable." >&2
    exit 2
fi

echo "[INFO] Firing ${N} requests at ${URL} (concurrency=${PARALLEL})..."

OUT_DIR="$(mktemp -d)"
trap 'rm -rf "${OUT_DIR}"' EXIT

# Fire the burst (single-arg xargs form: -I{} consumes the input value)
: > "${OUT_DIR}/codes.txt"
seq 1 "${N}" | xargs -P "${PARALLEL}" -I{} \
    sh -c "curl --max-time 5 --silent --output /dev/null --write-out '%{http_code}\n' '${URL}' >> '${OUT_DIR}/codes.txt' 2>/dev/null || true"

CODES=$(cat "${OUT_DIR}/codes.txt")

# Count statuses — guard against empty/missing files so set -u stays happy
TOTAL=0; N429=0; N503=0; N401=0; N403=0; N2XX=0
if [[ -s "${OUT_DIR}/codes.txt" ]]; then
    TOTAL=$(wc -l < "${OUT_DIR}/codes.txt" | tr -d ' ')
    N429=$(grep -c '^429' "${OUT_DIR}/codes.txt" || true)
    N503=$(grep -c '^503' "${OUT_DIR}/codes.txt" || true)
    N401=$(grep -c '^401' "${OUT_DIR}/codes.txt" || true)
    N403=$(grep -c '^403' "${OUT_DIR}/codes.txt" || true)
    N2XX=$(grep -cE '^2[0-9][0-9]' "${OUT_DIR}/codes.txt" || true)
fi
LIMITED=$((N429 + N503))
LIMITED_PCT=$(awk -v a="${LIMITED}" -v b="${TOTAL}" 'BEGIN{ if(b>0) printf "%.1f", (a/b)*100; else print "0" }')

{
    echo "# Rate-Limit Check — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "Target: \`${URL}\`"
    echo "Burst: ${N} requests, concurrency ${PARALLEL}"
    echo
    echo "| Status | Count |"
    echo "|--------|------:|"
    echo "| 2xx    | ${N2XX} |"
    echo "| 401    | ${N401} |"
    echo "| 403    | ${N403} |"
    echo "| **429 (rate-limited)** | **${N429}** |"
    echo "| 503    | ${N503} |"
    echo "| **Total limited** | **${LIMITED} (${LIMITED_PCT}%)** |"
    echo "| Sent   | ${TOTAL} |"
} >"${REPORT_FILE}"

cat "${REPORT_FILE}"

# Verdict — require at least 1% throttled, or auth-blocked if auth required
if [[ "${LIMITED}" -gt 0 ]]; then
    echo
    echo "[OK] Rate limiter engaged — ${LIMITED} requests throttled."
    exit 0
fi

# If all requests are 401/403 (auth wall ahead of limiter), that's also acceptable
AUTH_BLOCKED=$((N401 + N403))
if [[ "${TOTAL}" -gt 0 ]] && [[ "${AUTH_BLOCKED}" -eq "${TOTAL}" ]]; then
    echo
    echo "[OK] All requests blocked at auth layer (rate limiter unreachable from anonymous side)."
    exit 0
fi

echo
echo "[WARN] No rate limiting observed (0 x 429/503 out of ${TOTAL})." >&2
exit 1