# HTML_MeetingProtokol — Production Deployment Guide

This document walks through deploying the HMP backend to a Linux server (Ubuntu 22.04 LTS or Astra Linux 1.7+), fronted by Caddy for automatic HTTPS.

> **Architecture**
>
> ```
>   Internet
>      │   :80 / :443
>      ▼
>   ┌──────────────┐
>   │    Caddy     │  reverse proxy + auto-TLS (Let's Encrypt)
>   └──────┬───────┘
>          │
>   ┌──────┴───────┐
>   ▼              ▼
>  nginx        FastAPI backend (uvicorn)
>  (SPA)             │
>   │                ▼
>   │           PostgreSQL 15
>   └─► files volume `html_mp_prod`
> ```

---

## 1. Server preparation

### 1.1 Hardware requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU       | 4 cores | 8 cores (Whisper benefits from AVX2) |
| RAM       | 8 GB    | 16 GB (4 GB cap for backend + 1 GB Postgres + OS) |
| Disk      | 80 GB   | 200 GB SSD (audio + protocols grow fast) |
| Network   | 100 Mbps| 1 Gbps |

### 1.2 OS — Ubuntu 22.04 LTS

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git ufw rsync
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

### 1.3 OS — Astra Linux 1.7

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y curl git ufw rsync
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

> Astra's apt repos may carry older Docker. Use Docker's official static binaries or the convenience script below — it works on Debian-derived distros including Astra.

---

## 2. Install Docker Engine + Compose plugin

```bash
# Remove old versions if any
sudo apt remove -y docker docker-engine docker.io containerd runc || true

# Add Docker's official GPG key + repo (Ubuntu)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
   https://download.docker.com/linux/ubuntu \
   $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
   sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
                    docker-buildx-plugin docker-compose-plugin

# Add your user to the docker group (logout/login after)
sudo usermod -aG docker $USER

# Verify
docker --version          # ≥ 24.x
docker compose version    # ≥ v2.x
```

---

## 3. Create the `hmp` service account (only for systemd install)

If you also want the option of running the backend under systemd (no Docker):

```bash
sudo groupadd --system hmp
sudo useradd  --system --gid hmp \
    --home /var/lib/hmp --shell /usr/sbin/nologin \
    --comment "HMP backend" hmp

sudo mkdir -p /opt/hmp-backend /var/lib/hmp/.html_mp/protocols /var/log/hmp /etc/hmp
sudo chown -R hmp:hmp /var/lib/hmp /var/log/hmp /etc/hmp /opt/hmp-backend
```

---

## 4. Clone the project

```bash
sudo mkdir -p /opt/hmp-backend
sudo chown $USER:$USER /opt/hmp-backend
cd /opt/hmp-backend

# Replace with your repo URL
git clone https://github.com/your-org/hmp-backend.git .
cd hmp-backend
```

---

## 5. Configure `.env.prod`

```bash
cp .env.prod.example .env.prod
chmod 600 .env.prod
sudo chown $USER:$USER .env.prod
```

Edit the file and replace every `CHANGE_ME` placeholder:

```bash
nano .env.prod
```

Critical values:

| Variable | What to put |
|----------|-------------|
| `POSTGRES_PASSWORD` | 32+ char random string (`openssl rand -base64 32`) |
| `ENCRYPTION_MASTER_KEY` | base64 32-byte key — `scripts/deploy.sh` generates this if you let it |
| `HUGGINGFACE_TOKEN`   | from <https://huggingface.co/settings/tokens> |
| `HERMES_API_KEY` / `GIGACHAT_TOKEN` | provider keys |
| `CORS_ORIGINS` | `["https://your-domain.example.com"]` |
| `HMP_DOMAIN`   | the public hostname (used by Caddy for ACME) |
| `HMP_ACME_EMAIL` | contact for Let's Encrypt expiry warnings |

> **Never commit `.env.prod`.** It is already covered by the project `.gitignore`.

---

## 6. Create external volumes

```bash
docker volume create pgdata_prod
docker volume create html_mp_prod
```

These are declared `external: true` in `docker-compose.prod.yml` so data survives `compose down`.

---

## 7. Deploy

### Option A — Docker Compose (recommended)

```bash
./scripts/deploy.sh
```

The script:

1. Verifies Docker / compose
2. Creates `.env.prod` from template if missing and generates `ENCRYPTION_MASTER_KEY`
3. Builds the `Dockerfile.prod` multi-stage image
4. Starts the stack detached
5. Runs `alembic upgrade head` inside the backend container
6. Polls `/health` for up to 2 minutes

For subsequent deploys after a code change:

```bash
make prod-deploy          # or ./scripts/deploy.sh
```

### Option B — systemd (bare-metal uvicorn)

Use this only if you cannot run Docker in your environment.

```bash
# 1. Install Python deps in a venv
python3.11 -m venv /opt/hmp-backend/.venv
sudo -u hmp /opt/hmp-backend/.venv/bin/pip install -e .

# 2. Drop the env file
sudo cp .env.prod /etc/hmp/backend.env
sudo chown hmp:hmp /etc/hmp/backend.env
sudo chmod 600 /etc/hmp/backend.env

# 3. Install the unit
sudo cp systemd/hmp-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hmp-backend

# 4. Watch logs
sudo journalctl -u hmp-backend -f
```

When using systemd, also deploy PostgreSQL + Caddy separately (e.g. via Debian packages, a separate VM, or the `postgres` + `caddy` services from the compose file).

---

## 8. Verify

```bash
# Container health
make ps
docker compose -f docker-compose.prod.yml ps

# Backend health (via Caddy)
curl -fsS https://hmp.example.com/health

# Direct backend health (inside container)
docker exec hmp-backend-prod curl -fsS http://127.0.0.1:8000/health
```

---

## 9. Backup strategy

### 9.1 What we back up

| Source | Destination | Tool |
|--------|-------------|------|
| PostgreSQL (`html_mp` DB) | `/backup/db/<date>.sql.gz` | `pg_dump` + `gzip` |
| `html_mp_prod` volume (`/home/hmp/.html_mp/protocols/`) | `/backup/files/<date>/` | `rsync` (hardlinked, space-efficient) |

### 9.2 Run manually

```bash
sudo ./scripts/backup.sh
```

### 9.3 Automate via cron

```bash
sudo crontab -e
```

```
# Nightly backup at 02:30, then prune anything > 7 days
30 2 * * * /opt/hmp-backend/hmp-backend/scripts/backup.sh >> /var/log/hmp/backup.log 2>&1

# Optional: weekly upload to S3 via rclone (configure REMOTE_NAME/REMOTE_PATH env)
0 4 * * 0 REMOTE_NAME=s3 REMOTE_PATH=hmp-backups /opt/hmp-backend/hmp-backend/scripts/backup.sh >> /var/log/hmp/backup.log 2>&1
```

### 9.4 Restore

```bash
make restore DB=/backup/db/2026-09-14.sql.gz FILES=/backup/files/2026-09-14_023001
```

The script will:

1. Stop the backend container (release DB locks)
2. Drop & restore the DB via `psql --single-transaction`
3. Restore files via `rsync`
4. Restart the backend

You'll be prompted to type `RESTORE` to confirm.

---

## 10. Updating

```bash
cd /opt/hmp-backend/hmp-backend
git pull
make prod-deploy   # rebuilds image, runs alembic, health-checks
```

Alembic migrations are **idempotent** — running `upgrade head` on an up-to-date schema is a no-op.

---

## 11. Troubleshooting

| Symptom | Check |
|---------|-------|
| `ERROR: pooler: backend reports UNREACHABLE` | `docker compose -f docker-compose.prod.yml logs backend` |
| Caddy ACME fails | DNS A/AAAA must point at the server before `docker compose up`. Check `dig hmp.example.com`. |
| `ENCRYPTION_MASTER_KEY` warnings in logs | The placeholder value is invalid — re-generate and `docker compose restart backend` |
| Backend OOM-killed | `docker inspect hmp-backend-prod | grep -i memory` — 4G cap is hardcoded; bump in `docker-compose.prod.yml` if needed |
| Postgres fails to start after restore | Check `docker logs hmp-postgres-prod` — usually a permission issue on the `pgdata_prod` volume (`chown -R 999:999` for the postgres user) |

---

## 12. Security checklist

- [ ] `.env.prod` is `chmod 600`, owned by deploy user
- [ ] All `CHANGE_ME` placeholders replaced
- [ ] `POSTGRES_PASSWORD` ≥ 32 chars, random
- [ ] Firewall allows only 22, 80, 443
- [ ] SSH uses key auth (no passwords)
- [ ] Auto security updates enabled (`unattended-upgrades` on Ubuntu)
- [ ] Backups verified by a periodic restore drill (e.g. monthly)
- [ ] Logs shipped off-host (journald + syslog forwarder)
- [ ] Domain validated in HSTS preload list (optional)
