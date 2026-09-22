#!/usr/bin/env bash
#
# run-all.sh — последовательный прогон всех k6-нагрузочных тестов.
#
# Поведение:
#   • Прогоняет тесты в разумном порядке: smoke → read → search → upload
#     → transcribe_status → spike → stress → soak.
#   • Каждый тест пишет summary в tests/load/results/<test-name>.log
#     и (если в тесте есть handleSummary) JSON в tests/load/results/<test-name>.json.
#   • Печатает сводный отчёт; exit-code 0 только если ВСЕ thresholds passed.
#
# Использование:
#   ./tests/load/scripts/run-all.sh
#   BASE_URL=https://staging.example.com ./tests/load/scripts/run-all.sh
#   ./tests/load/scripts/run-all.sh --skip-soak        # пропустить 10-мин soak
#   ./tests/load/scripts/run-all.sh --skip-stress       # пропустить 5-мин stress
#
# Зависимости: k6 (https://k6.io/docs/getting-started/installation/).

set -u

# ---- конфиг ---------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOAD_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${LOAD_DIR}/results"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
mkdir -p "${RESULTS_DIR}"

SKIP_SOAK=0
SKIP_STRESS=0
for arg in "$@"; do
  case "${arg}" in
    --skip-soak)   SKIP_SOAK=1 ;;
    --skip-stress) SKIP_STRESS=1 ;;
    -h|--help)
      grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed -E 's/^# ?//'
      exit 0
      ;;
    *)
      echo "Unknown arg: ${arg}" >&2; exit 2 ;;
  esac
done

# ---- утилиты --------------------------------------------------------------

if ! command -v k6 >/dev/null 2>&1; then
  echo "❌ k6 не найден в PATH. Установите: https://k6.io/docs/getting-started/installation/" >&2
  exit 127
fi

# Цветной вывод
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
  C_RESET=; C_RED=; C_GREEN=; C_YELLOW=; C_BLUE=
fi

log()   { printf '%s==>%s %s\n' "${C_BLUE}"   "${C_RESET}" "$*"; }
ok()    { printf '%s ✓ %s\n' "${C_GREEN}" "$*"; }
warn()  { printf '%s ⚠ %s\n' "${C_YELLOW}" "$*"; }
fail()  { printf '%s ✗ %s\n' "${C_RED}"   "$*"; }

# Запустить один k6-тест; вернуть exit-code k6.
run_test() {
  local name="$1" file="$2" extra_log="$3"
  local log_file="${RESULTS_DIR}/${name}.log"
  log "Running ${name} (${file})"
  log "  log → ${log_file}"

  # shellcheck disable=SC2086
  BASE_URL="${BASE_URL}" k6 run "${extra_log}" "${LOAD_DIR}/${file}" \
    | tee "${log_file}"
  local rc=${PIPESTATUS[0]}
  echo
  if [[ ${rc} -eq 0 ]]; then
    ok "${name} thresholds passed"
  else
    fail "${name} failed (exit-code ${rc})"
  fi
  return ${rc}
}

# ---- прогон ---------------------------------------------------------------

declare -a SUITES=(
  "smoke:smoke.js"
  "api_read:api_read.js"
  "api_search:api_search.js"
  "api_upload:api_upload.js"
  "transcribe_status:transcribe_status.js"
)
declare -a RESULTS=()

# 1) быстрая проверка доступности бэкенда
log "Health probe: ${BASE_URL}/health"
if curl -fsS -o /dev/null --max-time 5 "${BASE_URL}/health"; then
  ok "/health responded"
else
  warn "/health probe failed — proceeding anyway (some endpoints may 404)"
fi

# 2) seed данных
log "Seeding 10 protocols via setup.js"
BASE_URL="${BASE_URL}" k6 run --quiet "${LOAD_DIR}/setup.js" \
  | tee "${RESULTS_DIR}/setup.log" >/dev/null 2>&1
SEED_RC=${PIPESTATUS[0]}
if [[ ${SEED_RC} -eq 0 ]]; then
  ok "setup.js complete"
else
  warn "setup.js exited with ${SEED_RC} — continuing"
fi

# 3) основные suites
for entry in "${SUITES[@]}"; do
  name="${entry%%:*}"
  file="${entry#*:}"
  if run_test "${name}" "${file}"; then
    RESULTS+=("PASS ${name}")
  else
    RESULTS+=("FAIL ${name}")
  fi
done

# 4) опциональные тяжёлые suites
if [[ ${SKIP_SPIKE:-0} -eq 0 ]]; then
  if run_test "spike" "spike.js"; then
    RESULTS+=("PASS spike")
  else
    RESULTS+=("FAIL spike")
  fi
fi

if [[ ${SKIP_STRESS} -eq 0 ]]; then
  if run_test "stress" "stress.js"; then
    RESULTS+=("PASS stress")
  else
    RESULTS+=("FAIL stress")
  fi
fi

if [[ ${SKIP_SOAK} -eq 0 ]]; then
  if run_test "soak" "soak.js"; then
    RESULTS+=("PASS soak")
  else
    RESULTS+=("FAIL soak")
  fi
fi

# ---- итог -----------------------------------------------------------------

echo
log "Summary"
printf '  %s\n' "${RESULTS[@]}"

FAILED=$(printf '%s\n' "${RESULTS[@]}" | grep -c '^FAIL' || true)
PASSED=$(printf '%s\n' "${RESULTS[@]}" | grep -c '^PASS' || true)

echo
if [[ ${FAILED} -eq 0 ]]; then
  ok "All ${PASSED} suites passed thresholds. Reports → ${RESULTS_DIR}/"
  exit 0
else
  fail "${FAILED}/${#RESULTS[@]} suites failed thresholds. See ${RESULTS_DIR}/"
  exit 1
fi