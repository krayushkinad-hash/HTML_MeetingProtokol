"""Check that every backend @router endpoint has a corresponding api.methodName in client.js.

E043: 'api.X is not a function' - frontend missing API method.

Run:
    python code/hmp-backend/scripts/check_api_coverage.py
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
BACKEND_ROUTERS = PROJECT_ROOT / "code" / "hmp-backend" / "app" / "routers"
FRONTEND_JS = PROJECT_ROOT / "code" / "hmp-frontend" / "src" / "js"


def get_backend_endpoints():
    """Extract all @router.X from backend code."""
    endpoints = []
    for f in sorted(BACKEND_ROUTERS.glob("*.py")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(
            r'@(?:router|app)\.(get|post|patch|delete|put)\(\s*["\']([^"\']+)["\']',
            text,
        ):
            method = m.group(1).upper()
            path = m.group(2)
            # Map common names to expected frontend methods
            endpoints.append({
                "file": f.stem,
                "method": method,
                "path": path,
                "expected_js": map_path_to_js(method, path),
            })
    return endpoints


def map_path_to_js(method, path):
    """Map backend path to expected frontend method name."""
    # Remove {param} and /api/v1/hmp prefix
    clean = path
    if clean.startswith("/api/v1/hmp/"):
        clean = clean[len("/api/v1/hmp/"):]
    # Normalize params to friendly names
    clean = re.sub(r"\{(\w+)\}", r"By\1", clean)
    # Build method name
    parts = [p for p in clean.split("/") if p and not p.startswith("By")]
    if not parts:
        return f"{method.lower()}"
    name = parts[0]
    # Singular action
    name = re.sub(r"s$", "", name)
    return f"{method.lower()}{name[0].upper()}{name[1:]}" if name else f"{method.lower()}"


def get_frontend_methods():
    """Extract all api.methodName from client.js."""
    client = FRONTEND_JS / "api" / "client.js"
    if not client.exists():
        return set()
    text = client.read_text(encoding="utf-8")
    methods = set()
    # Find all `methodName: ` in api object
    in_api = False
    brace_depth = 0
    for line in text.split("\n"):
        if "export const api" in line:
            in_api = True
        if in_api:
            brace_depth += line.count("{") - line.count("}")
            # Match method name pattern
            m = re.match(r"\s*(\w+):\s*\(?.*?\)?\s*=>?\s*request", line)
            if m:
                methods.add(m.group(1))
    return methods


def main():
    print("=" * 70)
    print("Check API coverage: backend endpoints vs frontend methods")
    print("=" * 70)

    backend = get_backend_endpoints()
    frontend = get_frontend_methods()

    print(f"\nBackend endpoints: {len(backend)}")
    print(f"Frontend methods: {len(frontend)}")

    # Check if frontend methods are used
    missing = []
    matched = 0
    for ep in backend:
        if ep["expected_js"] in frontend:
            matched += 1
        else:
            missing.append(ep)

    print(f"\nMatched: {matched}/{len(backend)}")

    if missing:
        print(f"\n⚠️  Potentially missing frontend methods ({len(missing)}):")
        for ep in missing[:30]:
            print(f"   {ep['method']} {ep['path']} → expected: {ep['expected_js']}")
        if len(missing) > 30:
            print(f"   ... and {len(missing) - 30} more")
        # Don't fail - just warn
        print("\n(Это heuristic — имена могут отличаться)")

    print()
    sys.exit(0)


if __name__ == "__main__":
    main()
