"""Check that all frontend view JS files import what they use.

E060: 'toast is not defined', 'api is not defined', etc.

When we add code that calls `toast.error(...)`, `api.get(...)`, etc.,
we MUST import them. This script catches missing imports.

Skipped false positives:
- `api` is a global injected via index.html (script tag)
- `SETTINGS_CSS` is exported, not used in this file
- exported names (`export const X =`) are not usage

Run:
    python code/hmp-frontend/scripts/check_frontend_imports.py
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
VIEWS_DIR = PROJECT_ROOT / "code" / "hmp-frontend" / "src" / "js" / "views"


def get_imports(text: str) -> set:
    """Extract all imported symbol names from import statements."""
    imports = set()
    for m in re.finditer(
        r"import\s*\{\s*([^}]+)\s*\}\s*from\s*['\"]([^'\"]+)['\"]", text
    ):
        symbols = m.group(1).split(",")
        for s in symbols:
            imports.add(s.strip().split(" as ")[0])
    return imports


def get_exports(text: str) -> set:
    """Extract names declared with `export const X`."""
    return set(re.findall(r"export\s+const\s+(\w+)", text))


def get_lines_in_function(text: str, symbol_name: str) -> list[int]:
    """Get line numbers of usages that are NOT in `export const X =` definition line."""
    usages = []
    for m in re.finditer(rf"\b{re.escape(symbol_name)}\b", text):
        line_no = text[:m.start()].count("\n") + 1
        line_text = text.split("\n")[line_no - 1]
        # Skip export definitions
        if re.match(r"\s*export\s+(const|function|class)\s+", line_text):
            continue
        # Skip import lines
        if line_text.strip().startswith("import "):
            continue
        usages.append(line_no)
    return usages


def check_file(file_path: Path) -> list:
    """Return list of (file_name, line_no, issue) tuples."""
    text = file_path.read_text(encoding="utf-8")
    issues = []

    imports = get_imports(text)
    exports = get_exports(text)

    # Check toast - skip if exported (it's exported by views/settings.js)
    if "toast" not in exports:
        usages = get_lines_in_function(text, "toast")
        # Get only `toast.X` usage lines
        toast_calls = []
        for m in re.finditer(r"\btoast\.\w+", text):
            ln = text[:m.start()].count("\n") + 1
            line_text = text.split("\n")[ln - 1]
            if not line_text.strip().startswith("import "):
                toast_calls.append(ln)

        if toast_calls and "toast" not in imports:
            issues.append(
                (file_path.name, str(toast_calls[0]), "uses toast but not imported")
            )

    # Check api - it MUST be imported for module usage
    api_calls = []
    for m in re.finditer(r"\bapi\.\w+\(", text):
        ln = text[:m.start()].count("\n") + 1
        line_text = text.split("\n")[ln - 1]
        if not line_text.strip().startswith("import "):
            api_calls.append(ln)

    if api_calls and "api" not in imports:
        issues.append(
            (file_path.name, str(api_calls[0]), "uses api but not imported")
        )

    # Check ICONS
    if "ICONS" not in exports:
        icons_calls = []
        for m in re.finditer(r"\bICONS\b", text):
            ln = text[:m.start()].count("\n") + 1
            line_text = text.split("\n")[ln - 1]
            if (
                not line_text.strip().startswith("import ")
                and "ICONS[" not in line_text  # usages like ICONS['home']
            ):
                # Only check declarations
                if "= ICONS" in line_text or "ICONS." in line_text:
                    icons_calls.append(ln)

        if icons_calls and "ICONS" not in imports:
            issues.append(
                (
                    file_path.name,
                    str(icons_calls[0]),
                    "uses ICONS but not imported",
                )
            )

    # SETTINGS_CSS - only check imported if used
    if "SETTINGS_CSS" not in exports:
        # Find places where SETTINGS_CSS is used (not defined)
        scss_usages = []
        for m in re.finditer(r"\bSETTINGS_CSS\b", text):
            ln = text[:m.start()].count("\n") + 1
            line_text = text.split("\n")[ln - 1]
            if not line_text.strip().startswith("import ") and "const SETTINGS_CSS" not in line_text:
                scss_usages.append(ln)

        if scss_usages and "SETTINGS_CSS" not in imports:
            issues.append(
                (
                    file_path.name,
                    str(scss_usages[0]),
                    "uses SETTINGS_CSS but not imported",
                )
            )

    return issues


def main():
    print("=" * 60)
    print("Check frontend view imports (E060)")
    print("=" * 60)

    all_issues = []
    for f in sorted(VIEWS_DIR.glob("*.js")):
        issues = check_file(f)
        all_issues.extend(issues)

    if all_issues:
        print(f"\nFAILED: {len(all_issues)} issues:")
        for fname, line, msg in all_issues:
            print(f"  {fname}:{line} -- {msg}")
        sys.exit(1)

    view_count = sum(1 for _ in VIEWS_DIR.glob("*.js"))
    print(f"\nOK: All {view_count} view files have proper imports")


if __name__ == "__main__":
    main()
