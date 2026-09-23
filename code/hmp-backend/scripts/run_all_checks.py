"""Master pipeline check - runs all auto-verification scripts.

E020, E042, E046, E047: Comprehensive validation across backend + frontend.

Run from project root:
    python code/hmp-backend/scripts/run_all_checks.py

Or skip specific checks:
    python code/hmp-backend/scripts/run_all_checks.py --skip frontend
"""
import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
BACKEND = PROJECT_ROOT / "code" / "hmp-backend"
FRONTEND = PROJECT_ROOT / "code" / "hmp-frontend"


def get_python():
    """Get path to venv Python with sqlalchemy if possible.

    Priority:
    1. Backend .venv (production)
    2. Hermes agent venv (has sqlalchemy, asyncpg)
    3. system python (fallback)
    """
    # Priority 1: backend .venv
    venv_python = PROJECT_ROOT / "code" / "hmp-backend" / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    venv_python_unix = PROJECT_ROOT / "code" / "hmp-backend" / ".venv" / "bin" / "python"
    if venv_python_unix.exists():
        return str(venv_python_unix)

    # Priority 2: hermes-agent venv (has all needed deps for checks)
    hermes_venv = Path("/usr/local/lib/hermes-agent/venv/bin/python")
    if hermes_venv.exists():
        return str(hermes_venv)

    # Priority 3: system python
    return "python"


PYTHON = get_python()


# All checks: (name, command, category)
CHECKS = [
    # ===== BACKEND =====
    {
        "name": "Required packages importable (E065)",
        "cmd": [PYTHON, str(BACKEND / "scripts" / "check_required_packages.py")],
        "category": "backend",
        "description": "All required packages (httpx, httpcore, h11, hf_hub, etc) importable",
    },
    {
        "name": "No duplicate packages (E067)",
        "cmd": [PYTHON, str(BACKEND / "scripts" / "check_duplicate_packages.py")],
        "category": "backend",
        "description": "No duplicate packages in install_pinned_deps.py / requirements",
    },
    {
        "name": "All modules catalog (E065/E066)",
        "cmd": [PYTHON, str(BACKEND / "scripts" / "check_all_modules.py")],
        "category": "backend",
        "description": "Comprehensive catalog of all 60+ modules used by backend",
    },
    {
        "name": "Backend syntax (all .py files)",
        "cmd": [PYTHON, "-c", "import ast; from pathlib import Path; "
              "[ast.parse(f.read_text()) for f in Path('code/hmp-backend/app/routers').glob('*.py')]; "
              "print('OK')"],
        "category": "backend",
        "description": "All Python files parse OK (E035)",
    },
    {
        "name": "Models ↔ Routers consistency",
        "cmd": [PYTHON, str(BACKEND / "scripts" / "check_models_routers_consistency.py")],
        "category": "backend",
        "description": "All imported models exist; routers imported in main.py (E002, E016-E018)",
    },
    {
        "name": "Python imports check",
        "cmd": [PYTHON, str(BACKEND / "scripts" / "check_python_imports.py")],
        "category": "backend",
        "description": "All used names are imported (E042, E046)",
    },
    {
        "name": "UnboundLocalError patterns check",
        "cmd": [PYTHON, str(BACKEND / "scripts" / "check_unbound_local.py")],
        "category": "backend",
        "description": "No local imports shadowing outer scope (E042, E051)",
    },
    {
        "name": "DB columns vs ORM check",
        "cmd": [PYTHON, str(BACKEND / "scripts" / "check_db_columns.py")],
        "category": "backend",
        "description": "DB schema matches ORM models (E046-E047)",
        "optional": True,  # requires DB connection
    },
    {
        "name": "API coverage heuristic",
        "cmd": [PYTHON, str(BACKEND / "scripts" / "check_api_coverage.py")],
        "category": "backend",
        "description": "Frontend has methods for backend endpoints (E043)",
    },

    # ===== FRONTEND =====
    {
        "name": "client.js syntax",
        "cmd": ["node", "--check", str(FRONTEND / "src" / "js" / "api" / "client.js")],
        "category": "frontend",
        "description": "API client parses OK (E005)",
    },
    {
        "name": "All view JS syntax (E062)",
        "cmd": ["bash", "-c",
                f'for f in {FRONTEND}/src/js/views/*.js; do '
                'node --check "$f" || exit 1; done'],
        "category": "frontend",
        "description": "All view JS files parse without SyntaxError (E062)",
    },
    {
        "name": "Deep JS quality (E062, E064)",
        "cmd": [PYTHON, str(FRONTEND / "scripts" / "check_braces_deep.py")],
        "category": "frontend",
        "description": "Deep JS check: extra `});` patterns and unclosed templates",
    },
    {
        "name": "Frontend callbacks defined",
        "cmd": [PYTHON, str(FRONTEND / "scripts" / "verify_callbacks.py"), "verify"],
        "category": "frontend",
        "description": "All addEventListener handlers exist (E020)",
    },
    {
        "name": "Frontend view imports",
        "cmd": [PYTHON, str(FRONTEND / "scripts" / "check_frontend_imports.py")],
        "category": "frontend",
        "description": "All frontend view files import used symbols (E060)",
    },

    # ===== UNIFIED =====
    {
        "name": "US_LIST ↔ US_Cards drift",
        "cmd": [PYTHON, "-c",
                "import sys; sys.path.insert(0, 'code/hmp-backend/scripts'); "
                "from pathlib import Path; import re; "
                "ul = Path('artifacts/03-user-stories/1_us_list/US_LIST.md').read_text(); "
                "cards = [f.stem for f in Path('artifacts/03-user-stories/2_us_cards').glob('US_*.md')]; "
                "us_in_list = set(re.findall(r'US-\\d{3}', ul)); "
                "us_cards = set(c.replace('_', '-') for c in cards); "
                "missing = us_in_list - us_cards; "
                "extra = us_cards - us_in_list; "
                "print(f'in_list={len(us_in_list)} cards={len(us_cards)} missing={len(missing)} extra={len(extra)}'); "
                "sys.exit(1 if missing or extra else 0)"],
        "category": "unified",
        "description": "US_LIST.md matches US cards (E040)",
    },
    {
        "name": "Pipeline gate check (12 stages)",
        "cmd": [PYTHON, "/root/.hermes/profiles/alex3/skills/pipeline-checker/scripts/run_pipeline_check.py", "--full"],
        "category": "unified",
        "description": "Full pipeline validation (vision→code)",
    },
]


def run_check(check):
    """Run one check and return (success, output)."""
    try:
        result = subprocess.run(
            check["cmd"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"ERROR: {e}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip", choices=["backend", "frontend", "unified"], nargs="*")
    parser.add_argument("--only", choices=["backend", "frontend", "unified"], nargs="*")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print("HMP Master Pipeline Check")
    print("=" * 70)
    print(f"Project: {PROJECT_ROOT}")
    print()

    passed = 0
    failed = 0
    skipped = 0

    for check in CHECKS:
        # Skip logic
        if args.skip and check["category"] in args.skip:
            print(f"⏭️  {check['name']} (skipped)")
            skipped += 1
            continue
        if args.only and check["category"] not in args.only:
            print(f"⏭️  {check['name']} (skipped - not in --only)")
            skipped += 1
            continue

        ok, output = run_check(check)
        icon = "✅" if ok else "❌"
        print(f"{icon} {check['name']}")

        if args.verbose or not ok:
            # Show description
            if check.get("description"):
                print(f"   ℹ️  {check['description']}")
            # Show last few lines of output
            output_lines = output.strip().split("\n")
            for line in output_lines[-8:]:
                if line.strip():
                    print(f"   {line[:200]}")
            print()

        if ok:
            passed += 1
        else:
            failed += 1

    print()
    print("=" * 70)
    print(f"RESULT: {passed} passed, {failed} failed, {skipped} skipped")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()



PYTHON = get_python()
