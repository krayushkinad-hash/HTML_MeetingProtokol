# Security Checklist for Code Review — hmp-backend

> Use this checklist on every PR that touches `app/`, `alembic/`, `Dockerfile`,
> or `pyproject.toml`. Tick each box you verify; comment inline if a control
> does not apply.

Reference: **NFR §14** (Threat Model), **ADR-014** (Security & Cryptography).

Legend: ✅ done · ⚠️ requires attention · 🟡 N/A (justify in PR)

---

## A. Input & Output handling

- [ ] **SQL Injection** — every DB access uses SQLAlchemy ORM / parameterised
      text. ❌ never string-format user input into raw SQL.
      _SQLAlchemy 2.x with `text(":param")` placeholders ✅_
- [ ] **XSS (Reflected)** — backend never returns HTML rendered from user input.
      All responses are JSON (or `FileResponse` for downloads). ✅
- [ ] **XSS (Stored)** — protocol text is stored verbatim but the **frontend**
      is responsible for safe rendering; backend's contract is to return
      strings as JSON and trust the client. ✅
- [ ] **Deserialisation** — Pydantic v2 strict mode; `model_config =
      ConfigDict(extra='forbid')` on all request schemas. ✅
- [ ] **Path Traversal** — file operations under `MEDIA_ROOT` use
      `pathlib.Path.resolve()` + check it is a child of the root. ✅
      _Any new file-serving endpoint must follow the same pattern._
- [ ] **MIME Sniffing** — uploads are sniffed via `python-magic` (or
      Pillow's `Image.verify()` for images) before being persisted. ✅
- [ ] **Size Limits** — every multipart endpoint enforces a max body size
      before reaching the route handler (middleware). ✅

## B. Authentication & Authorisation

- [ ] **JWT Verification** — every protected route uses the `Depends(verify_jwt)`
      dependency. No manual `Authorization` parsing in route bodies. ✅
- [ ] **Single-User Model** — there is exactly one user; `sub == settings.user_id`
      is the only authorisation rule (ADR-014). No role hierarchy. ✅
- [ ] **Token Storage** — tokens are never logged, never echoed in errors.
      Confirmed in middleware logs (`structlog`). ✅
- [ ] **Token Rotation** — see ADR-014 §"Key rotation". `rotate_master_key`
      utility exists; documented runbook is in `docs/RUNBOOK.md`. ✅
- [ ] **CSRF** — N/A (stateless bearer-token API, no cookie auth). 🟡 ✅
- [ ] **Brute-Force Protection** — `slowapi` rate-limiter on `/api/v1/*`.
      `rate-limit-check.sh` enforces a 60-rpm default. ✅

## C. Cryptography

- [ ] **At-rest Encryption** — DB password and LLM keys stored in OS keyring
      or `.env` (development only). DB itself is local SQLite/Postgres on
      the user's machine. ADR-014 specifies AES-256-GCM for any encrypted
      blob the app persists. ✅
- [ ] **In-Transit Encryption** — production deployment must terminate TLS
      at a reverse proxy (Caddy / nginx); the FastAPI process binds to
      `127.0.0.1:8000` only. 🟡 dev / ✅ production deploy
- [ ] **Algorithm Choice** — AES-GCM or ChaCha20-Poly1305 for symmetric;
      HS256 for JWT; SHA-256+ for digests. No MD5, no SHA-1. ✅
- [ ] **Key Length** — JWT HS256 secret ≥ 32 bytes random. ✅
      _See `app/core/config.py` `JWT_SECRET` validator._
- [ ] **Randomness** — use `secrets` module, not `random`. ✅

## D. Configuration & Secrets

- [ ] **No Secrets in Source** — `secrets-scan.sh` (gitleaks) passes. ✅
- [ ] **`.env` Git-Ignored** — `.gitignore` includes `.env` and `.env.*`
      except `.env.example`. ✅
- [ ] **Defaults are Insecure** — the app refuses to start if `JWT_SECRET`
      equals the placeholder. `app/main.py` lifespan asserts this. ✅
- [ ] **Stack Traces in Production** — `debug=False`, custom
      `ProblemDetailsMiddleware` strips traceback (NFR §5.4). ✅
- [ ] **CORS** — `allow_origins` is an explicit list read from settings.
      No `"*"`. ✅
- [ ] **Trusted Hosts** — `uvicorn --host 127.0.0.1`; behind reverse proxy,
      set `TRUSTED_HOSTS` explicitly. 🟡 dev / ✅ prod

## E. HTTP Hardening

- [ ] **HSTS** — reverse proxy sets `Strict-Transport-Security: max-age=63072000; includeSubDomains`. 🟡 dev / ✅ prod
- [ ] **`X-Content-Type-Options: nosniff`** — set in middleware. ✅
- [ ] **`X-Frame-Options: DENY`** — set in middleware. ✅
- [ ] **CSP** — `default-src 'self'`; no `unsafe-inline` in production. ✅
- [ ] **Referrer-Policy** — `strict-origin-when-cross-origin`. ✅
- [ ] **Permissions-Policy** — disables camera, microphone, geolocation
      unless explicitly needed. ✅
- [ ] **Headers verified** — `security/headers-check.sh` passes locally. ✅

## F. Dependency & Supply-chain

- [ ] **Lockfile** — `uv.lock` (or `requirements.lock`) is committed. ✅
- [ ] **`pip-audit` clean** — `security/pip-audit.sh` passes (no HIGH/CRITICAL
      CVEs in deps). ✅
- [ ] **Trivy clean** — `security/trivy.sh` passes for the production image. ✅
- [ ] **Bandit clean** — `security/bandit.sh` reports no medium+ issues. ✅
- [ ] **No Unused Dependencies** — `pip check` passes; deps are removed when
      code paths go away. ✅

## G. Data & Privacy

- [ ] **Logging Hygiene** — no tokens, passwords, audio blobs, or transcript
      text in logs. Review `structlog` bindings. ✅
- [ ] **Error Messages** — generic to the client, full detail in server log
      keyed by `X-Correlation-Id`. ✅
- [ ] **PII Inventory** — only the user's own audio + transcripts + speaker
      embeddings are persisted. Documented in NFR §14. ✅
- [ ] **Data Retention** — TTL on uploads; explicit `DELETE /protocols/{id}`
      cascades to audio + embeddings + tags. ✅
- [ ] **Right-to-be-forgotten (GDPR Art. 17)** — N/A in current scope;
      flagged for re-evaluation if multi-user lands. 🟡

## H. Operational

- [ ] **CI Security Gate** — see `INTEGRATION.md`; PR cannot merge if any
      required scanner fails. ✅
- [ ] **Patch Cadence** — renovate / dependabot weekly for `pyproject.toml`. ✅
- [ ] **Incident Response** — see `docs/RUNBOOK.md` §"Security incidents". ✅
- [ ] **Backups Encrypted** — DB backups encrypted with same master key
      (ADR-014). ✅
- [ ] **Audit Log Retention** — 90 days hot, 1 year cold (NFR §13). ✅

---

## Quick verification commands

```bash
# Static checks
security/bandit.sh
security/secrets-scan.sh

# Dependency / container
security/pip-audit.sh
security/trivy.sh

# Runtime (backend must be running)
security/headers-check.sh
security/cors-check.sh
security/authn-check.sh
security/rate-limit-check.sh
security/owasp-zap.sh

# Everything
security/run-all.sh
```

---

## Revision history

| Date | Author | Change |
|------|--------|--------|
| 2026-09-14 | A. Краюшкин | Initial checklist aligned with NFR §14 / ADR-014 |