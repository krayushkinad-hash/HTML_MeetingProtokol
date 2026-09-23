#!/usr/bin/env bash
# run-all.sh — Run the full security audit suite and produce an aggregated report.
#
# Invokes (in order):
#   1. pip-audit.sh        — Dependency SCA
#   2. safety.sh          — Dependency SCA (fallback, optional)
#   3. bandit.sh          — Python SAST
#   4. secrets-scan.sh    — Secrets in source
#   5. trivy.sh           — Container image scan
#   6. headers-check.sh   — HTTP security headers
#   7. cors-check.sh      — CORS configuration
#   8. authn-check.sh     — Authentication gating
#   9. rate-limit-check.sh — Rate limiting
#  10. owasp-zap.sh       — DAST (slowest; run last)
#
# Aggregates exit codes and writes:
#   security/reports/security-audit-YYYY-MM-DD.md
#
# Exit codes:
#   0 = no HIGH/CRITICAL findings
#   1 = at least one HIGH/CRITICAL finding
#   2 = required tool missing (pip-audit, bandit, curl…)
#
# NFR: §14 Threat Model — full audit run
set -uo pipefail   # intentionally NOT `set -e`: we want to keep going

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
SUMMARY="${REPORT_DIR}/security-audit-${DATE}.md"

mkdir -p "${REPORT_DIR}"

# -- Pretty status helpers ----------------------------------------------------
RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YLW=$'\033[0;33m'; CYN=$'\033[0;36m'; OFF=$'\033[0m'
log_info()  { printf '%s[INFO]%s %s\n'  "${CYN}" "${OFF}" "$*"; }
log_ok()    { printf '%s[ OK ]%s %s\n'  "${GRN}" "${OFF}" "$*"; }
log_warn()  { printf '%s[WARN]%s %s\n'  "${YLW}" "${OFF}" "$*" >&2; }
log_err()   { printf '%s[FAIL]%s %s\n'  "${RED}" "${OFF}" "$*" >&2; }
log_skip()  { printf '%s[SKIP]%s %s\n'  "${YLW}" "${OFF}" "$*"; }

# -- Runners ------------------------------------------------------------------
# Each runner: name, script path, severity (high|medium|low|info), action-on-missing (skip|fail)
declare -a RUNNERS=(
    "pip-audit|${SCRIPT_DIR}/pip-audit.sh|high|fail"
    "safety|${SCRIPT_DIR}/safety.sh|low|skip"
    "bandit|${SCRIPT_DIR}/bandit.sh|high|fail"
    "secrets-scan|${SCRIPT_DIR}/secrets-scan.sh|high|fail"
    "trivy|${SCRIPT_DIR}/trivy.sh|high|fail"
    "headers-check|${SCRIPT_DIR}/headers-check.sh|medium|fail"
    "cors-check|${SCRIPT_DIR}/cors-check.sh|high|fail"
    "authn-check|${SCRIPT_DIR}/authn-check.sh|high|fail"
    "rate-limit-check|${SCRIPT_DIR}/rate-limit-check.sh|medium|fail"
    "owasp-zap|${SCRIPT_DIR}/owasp-zap.sh|medium|fail"
)

# Per-tool results — keyed by name, values: status, severity, message
declare -A STATUS
declare -A SEVERITY
declare -A MESSAGE

# Aggregate failure codes (return-code sum, capped)
WORST_RC=0
MISSING_REQUIRED=0

run_one() {
    local name="$1" script="$2" sev="$3" on_missing="$4"
    log_info "Running ${name}..."

    if [[ ! -x "${script}" ]]; then
        log_warn "${name}: script not executable (run: chmod +x ${script})"
        STATUS["${name}"]="ERROR"; SEVERITY["${name}"]="${sev}"
        MESSAGE["${name}"]="script not executable"
        return 0
    fi

    # Capture both stdout & stderr to per-tool log
    local log_file="${REPORT_DIR}/${name}-${DATE}.log"
    set +e
    "${script}" >"${log_file}" 2>&1
    local rc=$?
    set -u
    # `set -e` was intentionally disabled for the suite; re-enable per-call.
    set -e

    SEVERITY["${name}"]="${sev}"

    case "${rc}" in
        0)
            STATUS["${name}"]="PASS"
            MESSAGE["${name}"]="clean"
            log_ok "${name}: PASS"
            ;;
        1)
            STATUS["${name}"]="FAIL"
            MESSAGE["${name}"]="issues found"
            if [[ "${sev}" == "high" ]]; then
                WORST_RC=1
            fi
            log_warn "${name}: FAIL (high-severity findings)"
            ;;
        2)
            # rc=2 means either: (a) a required CLI binary is missing,
            # or (b) the backend itself is unreachable (network). Inspect
            # the log to differentiate.
            if grep -qE '\[ERROR\].*not installed|\[ERROR\].*curl is not installed|\[ERROR\].*docker is not installed|\[ERROR\].*pip-audit is not installed|\[ERROR\].*trivy is not installed|\[ERROR\].*bandit is not installed|\[ERROR\].*safety is not installed|\[ERROR\].*gitleaks is not installed' "${log_file}"; then
                STATUS["${name}"]="SKIPPED"
                MESSAGE["${name}"]="tool missing"
                if [[ "${on_missing}" == "fail" ]]; then
                    MISSING_REQUIRED=1
                    WORST_RC=2
                fi
                log_skip "${name}: tool missing (see ${log_file} for install instructions)"
            elif grep -qE 'unreachable|is unreachable|No response|connection (refused|error)|Failed to connect' "${log_file}"; then
                STATUS["${name}"]="UNREACHABLE"
                MESSAGE["${name}"]="backend unreachable"
                if [[ "${on_missing}" == "fail" ]]; then
                    MISSING_REQUIRED=1
                    WORST_RC=2
                fi
                log_skip "${name}: backend unreachable (see ${log_file})"
            else
                STATUS["${name}"]="ERROR"
                MESSAGE["${name}"]="exit 2 (unknown reason)"
                log_err "${name}: rc=2 (see ${log_file})"
            fi
            ;;
        *)
            STATUS["${name}"]="ERROR"
            MESSAGE["${name}"]="unexpected exit code ${rc}"
            log_err "${name}: rc=${rc}"
            if [[ "${sev}" == "high" ]]; then WORST_RC=1; fi
            ;;
    esac
}

# Iterate runners
for entry in "${RUNNERS[@]}"; do
    IFS='|' read -r name script sev on_missing <<<"${entry}"
    run_one "${name}" "${script}" "${sev}" "${on_missing}"
done

# -- Aggregate report ----------------------------------------------------------
{
    echo "# Security Audit Report — ${TIMESTAMP}"
    echo
    echo "Project: **HTML_MeetingProtokol / hmp-backend**"
    echo "Threat model: NFR §14, ADR §14"
    echo
    echo "## Summary"
    echo
    echo "| Tool | Severity | Status | Notes |"
    echo "|------|:--------:|:------:|-------|"

    for entry in "${RUNNERS[@]}"; do
        IFS='|' read -r name _ sev _ <<<"${entry}"
        status="${STATUS[${name}]:-N/A}"
        msg="${MESSAGE[${name}]:-}"
        # Map status to emoji
        case "${status}" in
            PASS) icon="✅" ;;
            FAIL) icon="❌" ;;
            SKIPPED) icon="⚠️" ;;
            UNREACHABLE) icon="📡" ;;
            ERROR) icon="🚨" ;;
            *) icon="❔" ;;
        esac
        printf '| `%s` | %s | %s %s | %s |\n' "${name}" "${sev}" "${icon}" "${status}" "${msg}"
    done

    echo
    echo "## Verdict"
    echo
    if [[ "${WORST_RC}" -eq 0 ]]; then
        echo "✅ **PASS** — no HIGH/CRITICAL findings."
    elif [[ "${WORST_RC}" -eq 2 ]]; then
        echo "⚠️ **INCOMPLETE** — required scanner could not run. See the table above."
        echo
        echo "Required but unavailable:"
        for entry in "${RUNNERS[@]}"; do
            IFS='|' read -r name _ sev on_missing <<<"${entry}"
            if [[ "${on_missing}" == "fail" ]]; then
                local_status="${STATUS[${name}]:-}"
                case "${local_status}" in
                    SKIPPED|UNREACHABLE|ERROR)
                        echo "- \`${name}\`: ${local_status}"
                        ;;
                esac
            fi
        done
    else
        echo "❌ **FAIL** — HIGH/CRITICAL findings present. See per-tool logs."
    fi

    echo
    echo "## Per-tool reports"
    echo
    for entry in "${RUNNERS[@]}"; do
        IFS='|' read -r name _ _ _ <<<"${entry}"
        echo "- \`${name}\`: \`security/reports/${name}-${DATE}.log\`"
    done

    echo
    echo "## References"
    echo
    echo "- NFR §14 (Threat Model)"
    echo "- ADR-014 (Security & Cryptography)"
    echo "- COMPLIANCE.md — OWASP API Top 10 (2023), 152-ФЗ"
    echo "- SECURITY_CHECKLIST.md — code-review checklist"
    echo "- INTEGRATION.md — CI/CD integration"
} > "${SUMMARY}"

echo
echo "============================================================"
echo "Security audit complete."
echo "Aggregated report: ${SUMMARY}"
echo "============================================================"
cat "${SUMMARY}"

exit "${WORST_RC}"