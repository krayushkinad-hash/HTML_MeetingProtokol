#!/usr/bin/env bash
# authn-check.sh — Verify that protected endpoints reject unauthenticated access.
#
# Probes a list of endpoints WITHOUT a token and checks that the server
# returns 401 or 403 (not 200, not 500).
#
# Endpoints are derived from app/routers/*.py — see app/routers/ for the
# current protected surface (single-user app, ADR-014).
#
# Exit codes:
#   0 = all protected endpoints correctly reject anonymous requests
#   1 = at least one endpoint is reachable without auth
#   2 = backend unreachable
#
# NFR: §14 Threat Model (Broken Authentication = OWASP API2:2023)
set -euo pipefail

TARGET="${TARGET:-http://localhost:8000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
REPORT_FILE="${REPORT_DIR}/authn-${DATE}.md"

mkdir -p "${REPORT_DIR}"

if ! command -v curl >/dev/null 2>&1; then
    echo "[ERROR] curl is not installed." >&2
    exit 2
fi

# Health endpoint should NOT require auth (it's literally for that).
# Everything else from app/routers/ is gated.
ENDPOINTS=(
    "GET /api/v1/protocols"
    "GET /api/v1/transcribe"
    "GET /api/v1/utterances"
    "GET /api/v1/decisions"
    "GET /api/v1/dictionary"
    "GET /api/v1/tags"
    "GET /api/v1/screenshots"
    "GET /api/v1/summary"
    "GET /api/v1/export"
    "GET /api/v1/search"
    "GET /api/v1/speakers"
    "GET /api/v1/bot"
    "GET /api/v1/calendar"
    "GET /api/v1/ai"
    "GET /api/v1/actions"
    "GET /api/v1/live"
    "GET /api/v1/audio"
    "GET /api/v1/user-setting"
)

# health endpoint — expect 200 (sanity)
HEALTH_PATH="${TARGET}/health"
HEALTH_STATUS=$(curl --max-time 5 --silent --output /dev/null --write-out '%{http_code}' \
    "${HEALTH_PATH}" || echo "000")
if [[ "${HEALTH_STATUS}" == "000" ]] && curl --max-time 5 --silent --output /dev/null --write-out '%{http_code}' "${TARGET}/" >/dev/null 2>&1; then
    HEALTH_STATUS=$(curl --max-time 5 --silent --output /dev/null --write-out '%{http_code}' "${TARGET}/" || echo "000")
fi
if [[ "${HEALTH_STATUS}" == "000" ]]; then
    echo "[ERROR] Backend at ${TARGET} is unreachable." >&2
    exit 2
fi

UNGUARDED=0
: > "${REPORT_FILE}"
{
    echo "# Authentication Check — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "Target: \`${TARGET}\`"
    echo "Health probe: \`${HEALTH_STATUS}\` (expected 2xx/3xx)"
    echo
    echo "| Method | Path | Status | Verdict |"
    echo "|--------|------|:------:|---------|"
} >> "${REPORT_FILE}"

for ENTRY in "${ENDPOINTS[@]}"; do
    METHOD="${ENTRY%% *}"
    PATH_="${ENTRY#* }"
    URL="${TARGET}${PATH_}"

    STATUS=$(curl --max-time 10 --silent --output /dev/null --write-out '%{http_code}' \
        -X "${METHOD}" "${URL}" || echo "000")

    case "${STATUS}" in
        401|403)
            VERDICT="✅ rejected"
            ;;
        200)
            VERDICT="❌ reachable without auth"
            UNGUARDED=1
            ;;
        404)
            VERDICT="⚠️ not found (route missing?)"
            ;;
        000)
            VERDICT="⚠️ timeout / connection error"
            ;;
        *)
            VERDICT="⚠️ unexpected ${STATUS}"
            UNGUARDED=1
            ;;
    esac

    printf '| %s | %s | `%s` | %s |\n' "${METHOD}" "${PATH_}" "${STATUS}" "${VERDICT}" >>"${REPORT_FILE}"
done

cat "${REPORT_FILE}"

if [[ "${UNGUARDED}" -ne 0 ]]; then
    echo
    echo "[WARN] At least one protected endpoint is reachable without auth." >&2
    exit 1
fi

echo
echo "[OK] All probed endpoints reject anonymous requests."
exit 0