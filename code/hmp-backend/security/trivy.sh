#!/usr/bin/env bash
# trivy.sh — Docker image vulnerability scan (HIGH/CRITICAL only).
#
# Builds hmp-backend:latest if missing, then scans with Trivy.
# Reports to security/reports/trivy-YYYY-MM-DD.json
#
# Exit codes:
#   0 = no HIGH/CRITICAL findings
#   1 = HIGH/CRITICAL vulnerabilities found
#   2 = tool missing
#
# NFR: §14 Threat Model (container supply chain)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPORT_DIR="${SCRIPT_DIR}/reports"
DATE="$(date +%Y-%m-%d)"
IMAGE="${IMAGE:-hmp-backend:latest}"
REPORT_FILE="${REPORT_DIR}/trivy-${DATE}.json"

mkdir -p "${REPORT_DIR}"

if ! command -v trivy >/dev/null 2>&1; then
    cat >&2 <<'EOF'
[ERROR] trivy is not installed.

Install one of:
  # Debian/Ubuntu
  sudo apt-get install -y wget gnupg lsb-release
  wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo gpg --dearmor -o /usr/share/keyrings/trivy.gpg
  echo "deb [signed-by=/usr/share/keyrings/trivy.gpg] https://aquasecurity.github.io/trivy-repo/deb $(lsb_release -sc) main" | sudo tee /etc/apt/sources.list.d/trivy.list
  sudo apt-get update && sudo apt-get install -y trivy

  # Or use the Docker image:
  alias trivy='docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest'
EOF
    exit 2
fi

# -- Ensure the image exists ---------------------------------------------------
if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    if [[ -f "${PROJECT_ROOT}/Dockerfile" ]]; then
        echo "[INFO] Image ${IMAGE} not found — building from Dockerfile..."
        docker build -t "${IMAGE}" "${PROJECT_ROOT}"
    else
        echo "[ERROR] Image ${IMAGE} not found and no Dockerfile at ${PROJECT_ROOT}." >&2
        exit 2
    fi
fi

echo "[INFO] Scanning ${IMAGE} (severity=HIGH,CRITICAL)..."
echo "[INFO] Report -> ${REPORT_FILE}"

set +e
trivy image \
    --severity HIGH,CRITICAL \
    --format json \
    --output "${REPORT_FILE}" \
    --quiet \
    "${IMAGE}"
RC=$?
set -e

case "${RC}" in
    0)
        echo "[OK] No HIGH/CRITICAL vulnerabilities."
        exit 0
        ;;
    *)
        echo "[WARN] Vulnerabilities found (rc=${RC}). See ${REPORT_FILE}" >&2
        exit 1
        ;;
esac