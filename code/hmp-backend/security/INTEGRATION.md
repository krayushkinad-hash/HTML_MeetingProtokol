# CI/CD Integration — hmp-backend security toolkit

This document explains how the scripts in `security/` are wired into
**GitHub Actions** for pull-request and main-branch workflows.

Reference: **NFR §14**, **ADR-014**, `COMPLIANCE.md`, `SECURITY_CHECKLIST.md`.

---

## 1. Workflow file

Drop this into `.github/workflows/security.yml`:

```yaml
name: security

on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [main]
  schedule:
    # Weekly Monday 03:00 UTC — catches newly disclosed deps vulns
    - cron: "0 3 * * 1"

permissions:
  contents: read

jobs:
  audit:
    name: Security audit
    runs-on: ubuntu-latest
    timeout-minutes: 20

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: hmp
          POSTGRES_PASSWORD: hmp
          POSTGRES_DB: hmp_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U hmp"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install security tooling
        run: |
          python -m pip install --upgrade pip
          pip install pip-audit bandit
          # gitleaks — see https://github.com/gitleaks/gitleaks-action
          # trivy  — see aquasecurity/trivy-action

      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Build image (for Trivy)
        run: docker build -t hmp-backend:ci .

      - uses: aquasecurity/trivy-action@master
        with:
          image-ref: hmp-backend:ci
          severity: HIGH,CRITICAL
          format: json
          output: trivy-results.json

      - name: Upload Trivy results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: trivy-report
          path: trivy-results.json

      - name: Start backend
        run: |
          docker compose up -d
          # Wait until /health is 200 (max 60s)
          for i in $(seq 1 60); do
            if curl -fs http://localhost:8000/health; then break; fi
            sleep 1
          done

      - name: Run security audit suite
        run: bash security/run-all.sh
        env:
          TARGET: http://localhost:8000

      - name: Upload aggregated report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: security-audit-report
          path: security/reports/security-audit-*.md

      - name: Fail CI if HIGH/CRITICAL findings
        if: failure()
        run: |
          echo "::error::Security audit failed — see the security-audit-report artifact."
          exit 1
```

---

## 2. Fail-CI thresholds

`security/run-all.sh` exits non-zero whenever any **required** tool returns
`1` (HIGH severity finding) or `2` (required tool missing). The matrix:

| Tool | Required? | Fail CI on |
|------|:---------:|-----------|
| pip-audit | ✅ | any CVE (HIGH/CRITICAL via PyPI Advisory DB) |
| safety | ⚠️ optional | informational; only runs if pip-audit unavailable |
| bandit | ✅ | any medium+ severity issue |
| secrets-scan | ✅ | any suspected secret |
| trivy | ✅ | any HIGH/CRITICAL image CVE |
| headers-check | ✅ | any required header missing (HSTS, X-Content-Type-Options, X-Frame-Options, CSP) |
| cors-check | ✅ | reflection of attacker origin / wildcard |
| authn-check | ✅ | any protected endpoint reachable without auth |
| rate-limit-check | ✅ | 0/200 requests throttled and not auth-blocked |
| owasp-zap | ⚠️ optional | HIGH-risk ZAP alerts (informational in dev, required on `main`) |

> **Severity escalation rule:** a *medium*-severity check that fails 3 PRs in
> a row is auto-promoted to HIGH and added to the required-fail list.

---

## 3. Local development

Developers should be able to reproduce the CI gate on their laptop:

```bash
# One-off setup
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pip install pip-audit bandit

# Optional — required for full coverage
brew install gitleaks trivy   # or: apt-get install gitleaks trivy
docker pull owasp/zap2docker-stable

# Run the full suite (backend must be up)
docker compose up -d
bash security/run-all.sh
```

Or run individual scanners:

```bash
security/bandit.sh           # SAST
security/pip-audit.sh        # deps
security/secrets-scan.sh     # secrets
security/headers-check.sh    # HTTP headers (no auth required)
security/cors-check.sh       # CORS preflight
security/authn-check.sh      # auth gating
security/rate-limit-check.sh # rate-limit
security/trivy.sh            # image
security/owasp-zap.sh        # DAST (slowest)
```

---

## 4. Suppressing false positives

Inline comments in code:

```python
# bandit disable=B105  (test fixture for password validator)
TEST_PASSWORD = "intentionally-not-a-real-secret"
```

`bandit` flags can be silenced at the file or function level — *never* at
the project level (`.bandit` config is intentionally **not** committed).

For ZAP false positives, use a `.zap.conf` policy file mounted at
`/zap/wrk/.zap.conf` inside the ZAP container. Document every suppression
in the PR description.

---

## 5. Reporting

| Channel | When | Who |
|---------|------|-----|
| PR comment (bot) | every scan | `github-actions[bot]` |
| Weekly digest | Monday 09:00 local | `security-audit-weekly.md` artifact |
| Quarterly review | first Monday of quarter | maintainer sign-off, see `COMPLIANCE.md` §7 |

---

## 6. Future work

- [ ] Cache `pip-audit` advisory DB between runs (5 min TTL) to speed CI
- [ ] Move ZAP baseline to a scheduled nightly job (too slow for every PR)
- [ ] Wire SARIF output from `bandit` into GitHub Code Scanning for inline annotations
- [ ] Add `cargo-audit`-equivalent for any Rust helpers added later
- [ ] Supply-chain: SLSA L3 provenance attestation on the container image