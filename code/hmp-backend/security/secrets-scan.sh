#!/usr/bin/env bash
# secrets-scan.sh — Detect hard-coded secrets in the working tree.
#
# Prefers gitleaks; falls back to a grep-based heuristic that catches
# common patterns (AWS keys, GitHub tokens, generic api_key/secret pairs).
#
# Exit codes:
#   0 = clean
#   1 = suspected secrets found
#   2 = neither tool available
#
# NFR: §14 Threat Model (secrets in source)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
REPORT_FILE="${REPORT_DIR}/secrets-${DATE}.txt"

mkdir -p "${REPORT_DIR}"

# Always exclude: .git, venv, build artifacts, the reports dir itself
EXCLUDES=(
    --exclude-dir=.git
    --exclude-dir=.venv
    --exclude-dir=venv
    --exclude-dir=__pycache__
    --exclude-dir=.mypy_cache
    --exclude-dir=.pytest_cache
    --exclude-dir=node_modules
    --exclude-dir=reports
    --exclude-dir=dist
    --exclude-dir=build
    --exclude='*.min.js'
    --exclude='*.min.css'
    --exclude='package-lock.json'
    --exclude='poetry.lock'
    --exclude='uv.lock'
    --exclude='.env.example'
)

run_gitleaks() {
    if ! command -v gitleaks >/dev/null 2>&1; then
        return 127
    fi
    echo "[INFO] Running gitleaks..."
    set +e
    gitleaks detect \
        --source "${PROJECT_ROOT}" \
        --report-path "${REPORT_FILE}" \
        --no-banner \
        --redact
    RC=$?
    set -e
    return "${RC}"
}

run_grep_fallback() {
    echo "[INFO] gitleaks not found — running grep fallback..." >&2

    # Patterns that should NEVER appear in committed source.
    PATTERNS=(
        # AWS
        'AKIA[0-9A-Z]{16}'
        'aws_secret_access_key\s*[:=]\s*["'\'']?[A-Za-z0-9/+=]{40}'
        # GitHub
        'ghp_[A-Za-z0-9]{36,}'
        'gho_[A-Za-z0-9]{36,}'
        'github_pat_[A-Za-z0-9_]{82}'
        # OpenAI / Anthropic
        'sk-[A-Za-z0-9]{20,}'
        'sk-ant-[A-Za-z0-9-]{20,}'
        # Slack
        'xox[baprs]-[A-Za-z0-9-]{10,}'
        # Generic high-entropy assignment
        '(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*["'\''][A-Za-z0-9_\-]{16,}["'\'']'
        # PEM private keys
        '-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'
    )

    : > "${REPORT_FILE}"
    echo "# secrets-scan grep fallback — $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${REPORT_FILE}"
    echo "# Scanned: ${PROJECT_ROOT}" >> "${REPORT_FILE}"
    echo "" >> "${REPORT_FILE}"

    local hits=0
    local pat
    for pat in "${PATTERNS[@]}"; do
        # shellcheck disable=SC2086
        if grep -RInE "${EXCLUDES[@]}" "${pat}" "${PROJECT_ROOT}" >> "${REPORT_FILE}" 2>/dev/null; then
            hits=1
        fi
    done

    if [[ "${hits}" -eq 0 ]]; then
        echo "[OK] grep fallback: no suspected secrets."
        : > "${REPORT_FILE}"
        return 0
    fi
    echo "[WARN] grep fallback found suspected secrets. See ${REPORT_FILE}" >&2
    return 1
}

set +e
run_gitleaks
GIT_RC=$?
set -e

if [[ "${GIT_RC}" -eq 127 ]]; then
    set +e
    run_grep_fallback
    RC=$?
    set -e
    exit "${RC}"
fi

case "${GIT_RC}" in
    0)
        echo "[OK] gitleaks: no secrets."
        exit 0
        ;;
    1)
        echo "[WARN] gitleaks found leaks. See ${REPORT_FILE}" >&2
        exit 1
        ;;
    *)
        echo "[ERROR] gitleaks failed (rc=${GIT_RC})." >&2
        exit 1
        ;;
esac