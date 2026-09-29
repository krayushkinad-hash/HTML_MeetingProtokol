#!/usr/bin/env bash
# =============================================================================
# HTML_MeetingProtokol — backup script
# =============================================================================
#   - pg_dump of the running Postgres container → /backup/<date>.sql.gz
#   - rsync of the html_mp_prod volume mount (/home/hmp/.html_mp) → /backup/files/
#   - Local retention: 7 days
#   - Optional remote sync via rclone (if REMOTE_NAME is set in env)
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.prod.yml"
ENV_FILE="${PROJECT_ROOT}/.env.prod"

BACKUP_ROOT="${BACKUP_ROOT:-/backup}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
DATE="$(date +%F)"
TS="$(date +%F_%H%M%S)"
DB_DUMP_FILE="${BACKUP_ROOT}/db/${DATE}.sql.gz"
FILES_DEST="${BACKUP_ROOT}/files"

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-hmp-postgres-prod}"
POSTGRES_USER_VALUE="${POSTGRES_USER:-hmp}"
POSTGRES_DB_VALUE="${POSTGRES_DB:-html_mp}"

mkdir -p "${BACKUP_ROOT}/db" "${FILES_DEST}"

log()  { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
err()  { printf '[%s] ERROR: %s\n' "$(date '+%F %T')" "$*" >&2; }
trap 'err "backup failed on line $LINENO"' ERR

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------
[[ -f "${COMPOSE_FILE}" ]] || { err "Compose file not found: ${COMPOSE_FILE}"; exit 1; }

COMPOSE_CMD=(docker compose)
COMPOSE_CMD+=(-f "${COMPOSE_FILE}")
[[ -f "${ENV_FILE}" ]] && COMPOSE_CMD+=(--env-file "${ENV_FILE}")

# ---------------------------------------------------------------------------
# 1. DB dump
# ---------------------------------------------------------------------------
log "Dumping PostgreSQL database…"
# Use pg_dump inside the postgres container; pipe through gzip
"${COMPOSE_CMD[@]}" exec -T "${POSTGRES_CONTAINER}" \
    pg_dump -U "${POSTGRES_USER_VALUE}" -d "${POSTGRES_DB_VALUE}" \
        --no-owner --no-privileges --clean --if-exists \
    | gzip -9 > "${DB_DUMP_FILE}"
log "DB dump written: ${DB_DUMP_FILE} ($(du -h "${DB_DUMP_FILE}" | cut -f1))"

# ---------------------------------------------------------------------------
# 2. Files — sync protocols from the html_mp_prod volume mount
# ---------------------------------------------------------------------------
log "Syncing protocol files…"
PROTOCOLS_SRC="${PROTOCOLS_SRC:-/var/lib/docker/volumes/html_mp_prod/_data/protocols}"

if [[ -d "${PROTOCOLS_SRC}" ]]; then
    rsync -a --delete \
          --link-dest="${FILES_DEST}/latest" \
          "${PROTOCOLS_SRC}/" \
          "${FILES_DEST}/${TS}/"
    # Update "latest" hardlink farm
    rm -f "${FILES_DEST}/latest"
    ln -s "${TS}" "${FILES_DEST}/latest"
    log "Files synced: ${FILES_DEST}/${TS}/"
else
    log "WARN: protocols source not found at ${PROTOCOLS_SRC} — skipping file sync"
fi

# ---------------------------------------------------------------------------
# 3. Retention — local 7 days
# ---------------------------------------------------------------------------
log "Pruning backups older than ${BACKUP_RETENTION_DAYS} days…"
find "${BACKUP_ROOT}/db" -type f -name '*.sql.gz' -mtime +"${BACKUP_RETENTION_DAYS}" -delete -print || true
find "${BACKUP_ROOT}/files" -mindepth 1 -maxdepth 1 -type d \
     -mtime +"${BACKUP_RETENTION_DAYS}" -exec rm -rf {} + -print 2>/dev/null || true
log "Retention applied"

# ---------------------------------------------------------------------------
# 4. Optional remote sync (rclone)
# ---------------------------------------------------------------------------
if [[ -n "${REMOTE_NAME:-}" && -n "${REMOTE_PATH:-}" ]]; then
    log "Syncing to remote rclone target ${REMOTE_NAME}:${REMOTE_PATH}…"
    rclone sync "${BACKUP_ROOT}/" "${REMOTE_NAME}:${REMOTE_PATH}/" \
        --progress --transfers 4 --checkers 8 \
        --log-file "${BACKUP_ROOT}/rclone-${DATE}.log"
    log "Remote sync complete"
fi

# ---------------------------------------------------------------------------
# 5. Summary
# ---------------------------------------------------------------------------
log "Backup complete. Local artefacts:"
du -sh "${BACKUP_ROOT}/db" "${FILES_DEST}" 2>/dev/null || true
echo "---"
ls -lh "${BACKUP_ROOT}/db" | tail -5
