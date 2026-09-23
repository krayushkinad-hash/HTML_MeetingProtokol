#!/usr/bin/env bash
# headers-check.sh — Verify security headers on the backend root URL.
#
# Checks:
#   - Strict-Transport-Security (HSTS)
#   - X-Content-Type-Options: nosniff
#   - X-Frame-Options: DENY (or CSP frame-ancestors)
#   - Content-Security-Policy
#   - Referrer-Policy
#   - Permissions-Policy
#
# Exit codes:
#   0 = all required headers present
#   1 = missing required header(s)
#   2 = backend unreachable / curl missing
#
# NFR: §14 Threat Model (HTTP hardening)
set -euo pipefail

TARGET="${TARGET:-http://localhost:8000/}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
REPORT_FILE="${REPORT_DIR}/headers-${DATE}.md"

mkdir -p "${REPORT_DIR}"

if ! command -v curl >/dev/null 2>&1; then
    echo "[ERROR] curl is not installed." >&2
    exit 2
fi

echo "[INFO] Probing ${TARGET} ..."

# Capture headers (curl -I does HEAD; -D - writes to stdout regardless)
HEADERS="$(curl --max-time 10 --silent --show-error -D - -o /dev/null "${TARGET}" || true)"
if [[ -z "${HEADERS}" ]]; then
    echo "[ERROR] No response from ${TARGET}. Is the backend running?" >&2
    exit 2
fi

# Normalise case (HTTP/2 lower-cases header names; HTTP/1.1 keeps title-case).
HEADERS_LOWER="$(printf '%s\n' "${HEADERS}" | tr '[:upper:]' '[:lower:]')"

check_header() {
    local name="$1"; shift
    local required="${1:-required}"  # required|optional
    if printf '%s\n' "${HEADERS_LOWER}" | grep -q "^${name,,}:"; then
        printf '| %s | ✅ | %s |\n' "${name}" "${required}"
        return 0
    fi
    printf '| %s | ❌ | %s |\n' "${name}" "${required}"
    return 1
}

MISSING=0
{
    echo "# Security Headers Check — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "Target: \`${TARGET}\`"
    echo
    echo "| Header | Status | Required |"
    echo "|--------|:------:|----------|"
    check_header "Strict-Transport-Security"            "required"  || MISSING=1
    check_header "X-Content-Type-Options"                "required"  || MISSING=1
    check_header "X-Frame-Options"                      "required"  || MISSING=1
    check_header "Content-Security-Policy"               "required"  || MISSING=1
    check_header "Referrer-Policy"                       "recommended" || true
    check_header "Permissions-Policy"                    "recommended" || true
    check_header "Cross-Origin-Opener-Policy"            "recommended" || true
} >"${REPORT_FILE}"

# Append raw response for forensics
{
    echo
    echo "## Raw response headers"
    echo
    echo '```http'
    printf '%s\n' "${HEADERS}"
    echo '```'
} >>"${REPORT_FILE}"

cat "${REPORT_FILE}"

if [[ "${MISSING}" -ne 0 ]]; then
    echo
    echo "[WARN] One or more required security headers are missing. Report: ${REPORT_FILE}" >&2
    exit 1
fi

echo
echo "[OK] All required security headers present."
exit 0