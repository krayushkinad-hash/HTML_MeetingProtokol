#!/usr/bin/env bash
# cors-check.sh — Verify that the backend does NOT reflect arbitrary origins.
#
# Sends preflight OPTIONS requests with various Origin headers and
# confirms the server only echoes allowed origins (or none at all).
#
# Exit codes:
#   0 = CORS configured correctly
#   1 = unsafe CORS configuration detected
#   2 = backend unreachable
#
# NFR: §14 Threat Model (CORS misconfiguration = OWASP API5:2023)
set -euo pipefail

TARGET="${TARGET:-http://localhost:8000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
REPORT_FILE="${REPORT_DIR}/cors-${DATE}.md"

mkdir -p "${REPORT_DIR}"

if ! command -v curl >/dev/null 2>&1; then
    echo "[ERROR] curl is not installed." >&2
    exit 2
fi

# Pick an endpoint — any routable path works for OPTIONS
ENDPOINT="${ENDPOINT:-${TARGET}/api/v1/protocols}"
echo "[INFO] Probing CORS on ${ENDPOINT}..."

# Pre-flight: ensure backend is reachable
if ! curl --max-time 5 --silent --output /dev/null --write-out '%{http_code}' \
    -X OPTIONS "${ENDPOINT}" -H "Origin: http://probe.local" -H "Access-Control-Request-Method: GET" >/dev/null 2>&1; then
    if ! curl --max-time 5 --silent --output /dev/null --write-out '%{http_code}' "${TARGET}/health" >/dev/null 2>&1 \
       && ! curl --max-time 5 --silent --output /dev/null --write-out '%{http_code}' "${TARGET}/" >/dev/null 2>&1; then
        echo "[ERROR] Backend at ${TARGET} is unreachable. Start it first." >&2
        exit 2
    fi
fi

# Origins to test
ORIGINS=(
    "http://evil.com"
    "https://attacker.example"
    "null"
    "http://localhost:3000"   # legitimate dev origin (likely allowed)
)

fail() {
    echo "${1}" | tee -a "${REPORT_FILE}" >&2
    exit 1
}

: > "${REPORT_FILE}"
{
    echo "# CORS Configuration Check — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "Target: \`${ENDPOINT}\`"
    echo
    echo "| Origin | ACAO header | Verdict |"
    echo "|--------|-------------|---------|"
} >> "${REPORT_FILE}"

UNSAFE=0
for ORIGIN in "${ORIGINS[@]}"; do
    RAW=$(curl --max-time 10 --silent --show-error -i \
        -X OPTIONS \
        -H "Origin: ${ORIGIN}" \
        -H "Access-Control-Request-Method: GET" \
        -H "Access-Control-Request-Headers: Authorization" \
        "${ENDPOINT}" || true)

    # HTTP status
    STATUS=$(printf '%s\n' "${RAW}" | head -n1 | awk '{print $2}')
    # ACAO header
    ACAO=$(printf '%s\n' "${RAW}" | tr '[:upper:]' '[:lower:]' \
        | grep '^access-control-allow-origin:' | head -n1 \
        | sed -e 's/^access-control-allow-origin:[[:space:]]*//' -e 's/[[:space:]]*$//')

    if [[ -z "${ACAO}" ]]; then
        VERDICT="✅ no CORS header"
        ROW="| \`${ORIGIN}\` | _(absent)_ | ${VERDICT} |"
        printf '%s\n' "${ROW}" >>"${REPORT_FILE}"
        continue
    fi

    # If ACAO echoes the requested origin → wildcard / reflection vulnerability
    case "${ACAO,,}" in
        "*")
            VERDICT="⚠️ wildcard (review)"
            if [[ "${ORIGIN}" == "null" ]]; then
                VERDICT="❌ wildcard allows null origin"
                UNSAFE=1
            fi
            ;;
        "${ORIGIN,,}")
            if [[ "${ORIGIN}" == "http://evil.com" ]] || [[ "${ORIGIN}" == "https://attacker.example" ]]; then
                VERDICT="❌ reflected attacker origin"
                UNSAFE=1
            else
                VERDICT="✅ allowed"
            fi
            ;;
        "null")
            if [[ "${ORIGIN}" != "null" ]]; then
                VERDICT="⚠️ echoed null"
            else
                VERDICT="⚠️ null origin allowed"
                UNSAFE=1
            fi
            ;;
        *)
            VERDICT="✅ explicit allow"
            ;;
    esac

    printf '| `%s` | `%s` | %s |\n' "${ORIGIN}" "${ACAO}" "${VERDICT}" >>"${REPORT_FILE}"
done

{
    echo
    echo "## Recommendations"
    echo
    echo "- Allow only an explicit list of trusted origins (no wildcard in production)."
    echo "- Do NOT reflect the request's \`Origin\` header blindly."
    echo "- Set \`Access-Control-Allow-Credentials: true\` only with a non-wildcard ACAO."
} >>"${REPORT_FILE}"

cat "${REPORT_FILE}"

if [[ "${UNSAFE}" -ne 0 ]]; then
    echo
    echo "[WARN] Unsafe CORS behaviour detected. Report: ${REPORT_FILE}" >&2
    exit 1
fi

echo
echo "[OK] CORS configuration looks safe."
exit 0