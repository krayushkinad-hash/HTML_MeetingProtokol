#!/usr/bin/env bash
# =============================================================================
# HTML_MeetingProtokol — restore script
# =============================================================================
# Usage:  ./scripts/restore.sh <db_dump.sql.gz> [files_snapshot_dir]
#   - Restores Postgres from a gzip-compressed pg_dump file
#   - Optionally restores the protocols file tree
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.prod.yml"
ENV_FILE="${PROJECT_ROOT}/.env.prod"

DB_FILE="${1:-}"
FILES_SRC="${2:-}"

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-hmp-postgres-prod}"
POSTGRES_USER_VALUE="${POSTGRES_USER:-hmp}"
POSTGRES_DB_VALUE="${POSTGRES_DB:-html_mp}"
PROTOCOLS_DEST="${PROTOCOLS_DEST:-/var/lib/docker/volumes/html_mp_prod/_data/protocols}"

RED=$'\033[0;31m'; YEL=$'\033[1;33m'; GRN=$'\033[0;32m'; NC=$'\033[0m'
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
warn() { printf '%s[%s] WARN: %s%s\n' "${YEL}" "$(date '+%F %T')" "$*" "${NC}" >&2; }
err() { printf '%s[%s] ERROR: %s%s\n' "${RED}" "$(date '+%F %T')" "$*" "${NC}" >&2; }
ok()  { printf '%s[%s] ✓ %s%s\n' "${GRN}" "$(date '+%F %T')" "$*" "${NC}"; }

trap 'err "restore failed on line $LINENO"' ERR

# ---------------------------------------------------------------------------
# Validate args
# ---------------------------------------------------------------------------
[[ -z "${DB_FILE}" ]] && {
    err "Usage: $0 <db_dump.sql.gz> [files_snapshot_dir]"
    exit 1
}

[[ -f "${DB_FILE}" ]] || { err "DB dump not found: ${DB_FILE}"; exit 1; }

if [[ -n "${FILES_SRC}" && ! -d "${FILES_SRC}" ]]; then
    err "Files snapshot not found: ${FILES_SRC}"; exit 1
fi

[[ -f "${COMPOSE_FILE}" ]] || { err "Compose file not found: ${COMPOSE_FILE}"; exit 1; }

COMPOSE_CMD=(docker compose -f "${COMPOSE_FILE}")
[[ -f "${ENV_FILE}" ]] && COMPOSE_CMD+=(--env-file "${ENV_FILE}")

# ---------------------------------------------------------------------------
# Confirm destructive action
# ---------------------------------------------------------------------------
warn "This will OVERWRITE the current database!"
read -r -p "Type 'RESTORE' to continue: " ans
[[ "${ans}" == "RESTORE" ]] || { err "Aborted"; exit 1; }

# ---------------------------------------------------------------------------
# 1. Stop the backend to release DB connections
# ---------------------------------------------------------------------------
log "Stopping backend container…"
"${COMPOSE_CMD[@]}" stop backend || true

# ---------------------------------------------------------------------------
# 2. Restore DB
# ---------------------------------------------------------------------------
log "Restoring DB from ${DB_FILE}…"
gunzip -c "${DB_FILE}" \
    | "${COMPOSE_CMD[@]}" exec -T "${POSTGRES_CONTAINER}" \
        psql -U "${POSTGRES_USER_VALUE}" -d "${POSTGRES_DB_VALUE}" \
             -v ON_ERROR_STOP=1 --single-transaction
ok "Database restored"

# ---------------------------------------------------------------------------
# 3. Restore files (optional)
# ---------------------------------------------------------------------------
if [[ -n "${FILES_SRC}" ]]; then
    log "Restoring files from ${FILES_SRC} → ${PROTOCOLS_DEST}…"
    mkdir -p "${PROTOCOLS_DEST}"
    rsync -a --delete "${FILES_SRC}/" "${PROTOCOLS_DEST}/"
    ok "Files restored"
else
    warn "No files snapshot provided — skipping file restore"
fi

# ---------------------------------------------------------------------------
# 4. Restart backend
# ---------------------------------------------------------------------------
log "Starting backend…"
"${COMPOSE_CMD[@]}" start backend
ok "Restore complete"
