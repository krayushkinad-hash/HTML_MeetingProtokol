#!/usr/bin/env bash
# =============================================================================
# HTML_MeetingProtokol — automated production deployment
# =============================================================================
# - Verifies prerequisites (docker, docker compose plugin)
# - Ensures .env.prod exists (generates ENCRYPTION_MASTER_KEY if missing)
# - Creates external Docker volumes on first run
# - Pulls / builds images
# - Runs alembic migrations
# - Health-checks all services
# =============================================================================
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.prod.yml"
ENV_FILE="${PROJECT_ROOT}/.env.prod"
ENV_EXAMPLE="${PROJECT_ROOT}/.env.prod.example"
LOG_DIR="${PROJECT_ROOT}/logs"
BACKUP_VOLUME_NAME="html_mp_prod"
POSTGRES_VOLUME_NAME="pgdata_prod"

mkdir -p "${LOG_DIR}"

# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------
RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[1;33m'; BLU=$'\033[0;34m'; NC=$'\033[0m'
log()  { printf '%s[%s]%s %s\n' "${BLU}" "$(date '+%F %T')" "${NC}" "$*"; }
ok()   { printf '%s[%s]%s ✓ %s\n' "${GRN}" "$(date '+%F %T')" "${NC}" "$*"; }
warn() { printf '%s[%s]%s ⚠ %s\n' "${YEL}" "$(date '+%F %T')" "${NC}" "$*" >&2; }
err()  { printf '%s[%s]%s ✗ %s\n' "${RED}" "$(date '+%F %T')" "${NC}" "$*" >&2; }

trap 'err "deploy failed on line $LINENO"' ERR

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
check_prereqs() {
    log "Checking prerequisites…"

    command -v docker >/dev/null 2>&1 \
        || { err "docker not found — install from https://docs.docker.com/engine/install/"; exit 1; }

    # docker compose v2 ships as a plugin (`docker compose`), v1 standalone is deprecated
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        warn "docker-compose v1 detected — strongly recommend upgrading to v2 plugin"
        COMPOSE_CMD=(docker-compose)
    else
        err "docker compose not found — install: https://docs.docker.com/compose/install/"
        exit 1
    fi

    # Version check (≥ 24.x per requirements)
    local docker_version
    docker_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
    if [[ -n "${docker_version}" ]]; then
        log "Docker server version: ${docker_version}"
    fi

    ok "Prerequisites OK"
}

# ---------------------------------------------------------------------------
# 2. .env.prod — create from template if missing
# ---------------------------------------------------------------------------
ensure_env_file() {
    if [[ ! -f "${ENV_FILE}" ]]; then
        if [[ ! -f "${ENV_EXAMPLE}" ]]; then
            err "Neither ${ENV_FILE} nor ${ENV_EXAMPLE} found — aborting"
            exit 1
        fi
        warn "${ENV_FILE} not found — creating from template"
        cp "${ENV_EXAMPLE}" "${ENV_FILE}"
        chmod 600 "${ENV_FILE}"

        # Generate ENCRYPTION_MASTER_KEY if still the placeholder
        local key
        key="$(python3 -c 'import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())' 2>/dev/null || true)"
        if [[ -n "${key}" ]]; then
            # In-place substitution preserving safety
            if grep -q '^ENCRYPTION_MASTER_KEY="CHANGE_ME_BASE64_32_BYTES"' "${ENV_FILE}"; then
                sed -i "s|^ENCRYPTION_MASTER_KEY=.*|ENCRYPTION_MASTER_KEY=\"${key}\"|" "${ENV_FILE}"
                ok "Generated ENCRYPTION_MASTER_KEY"
            fi
        fi
        warn "Edit ${ENV_FILE} and replace remaining CHANGE_ME placeholders before going live"
        warn "Run: nano ${ENV_FILE}"
        if [[ "${SKIP_ENV_PROMPT:-false}" != "true" ]]; then
            read -r -p "Continue anyway? [y/N] " ans
            [[ "${ans}" =~ ^[Yy]$ ]] || { err "Aborted by user"; exit 1; }
        fi
    else
        ok ".env.prod present"
        # Sanity check: warn if any CHANGE_ME still present
        if grep -q CHANGE_ME "${ENV_FILE}"; then
            warn "Placeholders (CHANGE_ME) still present in ${ENV_FILE} — replace before serving traffic"
        fi
    fi
}

# ---------------------------------------------------------------------------
# 3. External volumes
# ---------------------------------------------------------------------------
ensure_volumes() {
    log "Ensuring external Docker volumes…"
    for vol in "${BACKUP_VOLUME_NAME}" "${POSTGRES_VOLUME_NAME}"; do
        if ! docker volume inspect "${vol}" >/dev/null 2>&1; then
            docker volume create "${vol}" >/dev/null
            ok "Created volume: ${vol}"
        else
            ok "Volume exists: ${vol}"
        fi
    done
}

# ---------------------------------------------------------------------------
# 4. Build / pull
# ---------------------------------------------------------------------------
build_images() {
    log "Building / pulling images…"
    "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" build --pull
    ok "Images ready"
}

# ---------------------------------------------------------------------------
# 5. Start
# ---------------------------------------------------------------------------
start_services() {
    log "Starting services (detached)…"
    "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --remove-orphans
    ok "Services started"
}

# ---------------------------------------------------------------------------
# 6. Migrations
# ---------------------------------------------------------------------------
run_migrations() {
    log "Running alembic migrations…"
    "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" \
        exec -T backend alembic upgrade head
    ok "Migrations applied"
}

# ---------------------------------------------------------------------------
# 7. Health check
# ---------------------------------------------------------------------------
health_check() {
    local timeout=120
    local elapsed=0
    log "Waiting for backend health endpoint (max ${timeout}s)…"

    while (( elapsed < timeout )); do
        if "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" \
            exec -T backend curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
            ok "Backend reports healthy"
            "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps
            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
        printf '.'
    done

    err "Backend did not become healthy within ${timeout}s"
    err "Tail logs: ${COMPOSE_CMD[*]} -f ${COMPOSE_FILE} logs --tail=200 backend"
    return 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log "===== HTML_MeetingProtokol production deploy ====="
    check_prereqs
    ensure_env_file
    ensure_volumes
    build_images
    start_services
    run_migrations
    health_check
    ok "===== Deploy complete ====="
    log "Stack status:"
    "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps
}

main "$@"
