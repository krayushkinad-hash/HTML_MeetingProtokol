# Security Audit Report — 2026-09-14T21:56:53Z

Project: **HTML_MeetingProtokol / hmp-backend**
Threat model: NFR §14, ADR §14

## Summary

| Tool | Severity | Status | Notes |
|------|:--------:|:------:|-------|
| `pip-audit` | high | ⚠️ SKIPPED | tool missing |
| `safety` | low | ⚠️ SKIPPED | tool missing |
| `bandit` | high | ⚠️ SKIPPED | tool missing |
| `secrets-scan` | high | ✅ PASS | clean |
| `trivy` | high | ⚠️ SKIPPED | tool missing |
| `headers-check` | medium | 🚨 ERROR | exit 2 (unknown reason) |
| `cors-check` | high | 📡 UNREACHABLE | backend unreachable |
| `authn-check` | high | ❌ FAIL | issues found |
| `rate-limit-check` | medium | ❌ FAIL | issues found |
| `owasp-zap` | medium | 📡 UNREACHABLE | backend unreachable |

## Verdict

⚠️ **INCOMPLETE** — required scanner could not run. See the table above.

Required but unavailable:
- `pip-audit`: SKIPPED
- `bandit`: SKIPPED
- `trivy`: SKIPPED
- `headers-check`: ERROR
- `cors-check`: UNREACHABLE
- `owasp-zap`: UNREACHABLE

## Per-tool reports

- `pip-audit`: `security/reports/pip-audit-2026-09-14.log`
- `safety`: `security/reports/safety-2026-09-14.log`
- `bandit`: `security/reports/bandit-2026-09-14.log`
- `secrets-scan`: `security/reports/secrets-scan-2026-09-14.log`
- `trivy`: `security/reports/trivy-2026-09-14.log`
- `headers-check`: `security/reports/headers-check-2026-09-14.log`
- `cors-check`: `security/reports/cors-check-2026-09-14.log`
- `authn-check`: `security/reports/authn-check-2026-09-14.log`
- `rate-limit-check`: `security/reports/rate-limit-check-2026-09-14.log`
- `owasp-zap`: `security/reports/owasp-zap-2026-09-14.log`

## References

- NFR §14 (Threat Model)
- ADR-014 (Security & Cryptography)
- COMPLIANCE.md — OWASP API Top 10 (2023), 152-ФЗ
- SECURITY_CHECKLIST.md — code-review checklist
- INTEGRATION.md — CI/CD integration
