# Compliance Status — hmp-backend

Last reviewed: **2026-09-14**
Owner: Алексей Краюшкин
Scope: `hmp-backend/` (FastAPI + SQLAlchemy + PostgreSQL 15)
Related: **NFR §14** (Threat Model), **ADR-014** (Security & Cryptography)

This document maps the application to recognised compliance / best-practice
frameworks and tracks the implementation status of each control.

> **Threat-model assumption (single-user desktop app):**
> hmp-backend runs as a personal tool on `localhost` behind a single-user
> bearer-token API. It is *not* exposed to the public internet. Controls
> below are calibrated for that posture; deviations from enterprise SaaS
> baselines are **intentional** and called out explicitly.

---

## 1. OWASP API Security Top 10 (2023)

| # | Risk | Status | Where it's addressed |
|---|------|:------:|---------------------|
| API1 | Broken Object-Level Authorization | 🟡 N/A* | Single-user app — no per-object ownership |
| API2 | Broken Authentication | ✅ | JWT (HS256), `pyjwt`, single-user; see `authn-check.sh` |
| API3 | Broken Object-Property-Level Authorization | 🟡 N/A* | Schema-locked via Pydantic v2 — no mass-assignment |
| API4 | Unrestricted Resource Consumption | ✅ | `slowapi` rate-limiter (planned); `rate-limit-check.sh` probes |
| API5 | Broken Function-Level Authorization | 🟡 N/A* | Single-user — no role hierarchy |
| API6 | Unrestricted Access to Sensitive Business Flows | 🟡 N/A* | No multi-tenant flows |
| API7 | Server-Side Request Forgery | ✅ | Outbound URLs are pinned to LLM provider; no user-supplied URL is fetched |
| API8 | Security Misconfiguration | ✅ | `headers-check.sh`, `cors-check.sh`, env-driven config |
| API9 | Improper Inventory Management | ✅ | OpenAPI auto-generated at `/docs` & `/openapi.json` |
| API10 | Unsafe Consumption of APIs | ✅ | LLM responses parsed as JSON only; no HTML rendering |

\* N/A is justified — these threats assume multi-user or role-based access
which the product spec (single local user, ADR-014) explicitly excludes.

---

## 2. OWASP ASVS (Application Security Verification Standard) — selected controls

| Section | Level | Status | Notes |
|---------|:-----:|:------:|-------|
| V1 — Architecture | L2 | ✅ | ADRs 001, 002, 005, 011, 014 |
| V2 — Authentication | L2 | ✅ | JWT bearer + AES-256-GCM key-at-rest (ADR-014) |
| V3 — Session Management | L2 | ✅ | Stateless JWT, 30-min TTL |
| V4 — Access Control | L2 | 🟡 N/A* | Single-user |
| V5 — Validation / Sanitisation | L2 | ✅ | Pydantic v2 strict; SQLAlchemy parameterised queries |
| V6 — Cryptography | L2 | ✅ | `cryptography` ≥43 (AES-GCM, SHA-256); TLS 1.2+ in transit |
| V7 — Error Handling & Logging | L2 | ✅ | RFC 7807 problem details (NFR §5.4); `structlog`, no PII in logs |
| V8 — Data Protection | L2 | ✅ | DB password via env var; secrets in OS keyring recommended |
| V9 — Communication Security | L2 | 🟡 | TLS termination at reverse-proxy in production; localhost OK in dev |
| V10 — Malicious Code | L2 | ✅ | `secrets-scan.sh`, `bandit.sh`, code review |
| V11 — Business Logic | L2 | ✅ | State machine for protocol lifecycle (US-007) |
| V12 — Files & Resources | L2 | ✅ | Upload validation: MIME sniff + size cap |
| V13 — API & Web Service | L2 | ✅ | OpenAPI published; rate limiting via `slowapi` |
| V14 — Configuration | L2 | ✅ | `.env.example` checked in; real `.env` git-ignored |

---

## 3. Russian Federation — 152-ФЗ «О персональных данных»

**Status: ✅ Covered (within intended scope).**

| Article (typical mapping) | Requirement | Implementation |
|---------------------------|-------------|----------------|
| ст. 5 — принципы обработки | Purpose limitation, data minimisation | App stores only meeting audio/text the user themselves records; no third-party PII flows |
| ст. 6 — основания обработки | Lawful basis | User's own data on user's own machine — ст. 6 ч. 1 п. 1 (consent) is implicit |
| ст. 7 — конфиденциальность | Access control | Single-user model + JWT bearer (ADR-014) |
| ст. 9 — согласие субъекта | Consent | Not applicable (data subject = data operator) |
| ст. 19 — меры защиты | Technical & organisational measures | See checklist below; AES-256-GCM at rest (ADR-014), TLS in transit |
| ст. 22 — уведомление Роскомнадзора | Notification | **N/A** — data is not collected from external subjects |

> **Note.** Because hmp-backend processes *only* the user's own recordings,
> there is no obligation under ст. 22 to register with Roskomnadzor. If a
> future feature ingests data about third parties (e.g. transcripts of
> meetings with attendees), this assessment must be re-opened.

---

## 4. GDPR (Regulation (EU) 2016/679)

**Status: 🟡 N/A — out of jurisdiction by design.**

GDPR applies when a controller/processor is established in the EU or
targets EU data subjects. hmp-backend is:

- a desktop tool run on the user's own hardware,
- with no telemetry, no analytics, no third-party data sharing beyond
  user-selected LLM providers (configured explicitly by the user).

Personal data stays on-device. If a feature change adds cross-border
processing, GDPR Art. 44 et seq. must be re-evaluated.

---

## 5. WCAG 2.1 AA — accessibility

**Status: 🟡 Backend N/A — client concern.**

hmp-backend is a JSON API. WCAG does not apply at the HTTP layer beyond:

| Guideline | Status | Where |
|-----------|:------:|-------|
| 1.1 Text Alternatives | 🟡 | Frontend renders audio via `<track>` captions |
| 1.4 Distinguishable | 🟡 | Frontend theming; CSP allows `prefers-color-scheme` |
| 2.1 Keyboard | 🟡 | Frontend |
| 4.1 Compatible (parsing) | ✅ | All responses are valid JSON or RFC 7807 problem details |

The companion frontend repo (`hmp-frontend/`) inherits the WCAG
obligation and must implement the marked 🟡 items.

---

## 6. NIST SP 800-53 (selected controls)

| Control | Title | Status |
|---------|-------|:------:|
| AC-2 | Account Management | 🟡 N/A — single-user |
| AC-3 | Access Enforcement | ✅ | JWT verify middleware |
| AU-2 | Audit Events | ✅ | `structlog` JSON logs (NFR §13) |
| IA-2 | Identification & Auth | ✅ | JWT (HS256) |
| SC-8 | Transmission Confidentiality | 🟡 | TLS at reverse proxy |
| SC-13 | Cryptographic Protection | ✅ | AES-256-GCM (ADR-014) |
| SI-10 | Information Input Validation | ✅ | Pydantic v2 strict mode |
| SI-11 | Error Handling | ✅ | RFC 7807 (NFR §5.4) |

---

## 7. Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Tech Lead | Алексей Краюшкин | 2026-09-14 | (this doc) |

This document must be reviewed and re-signed:

- on any change to the threat model (NFR §14),
- on adoption of any multi-user / multi-tenant feature,
- annually at minimum.