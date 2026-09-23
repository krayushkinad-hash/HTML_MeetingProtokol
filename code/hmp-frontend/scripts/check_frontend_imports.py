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


def _check_identifier(file_path, text, imports, exports, name):
    """E224: общая проверка идентификатора — используется но не импортирован/не экспортирован."""
    if name in exports:
        return []
    usages = []
    for m in re.finditer(rf"\b{name}\b", text):
        ln = text[:m.start()].count("\n") + 1
        line_text = text.split("\n")[ln - 1]
        if (
            not line_text.strip().startswith("import ")
            and not line_text.strip().startswith("//")
            and f"const {name}" not in line_text
            and f"function {name}" not in line_text
            and f"let {name}" not in line_text
        ):
            usages.append(ln)
    if usages and name not in imports:
        return [(file_path.name, str(usages[0]), f"uses {name} but not imported")]
    return []


def check_file(file_path):
    """Check that all globals used are imported or defined."""
    text = file_path.read_text(encoding="utf-8")
    issues = []

    imports = get_imports(text)
    exports = get_exports(text)

    # E224: проверяем основные утилиты
    # Список можно расширять (escapeHtml, formatTime, ...)
    for util in ("toast", "api", "ICONS", "SETTINGS_CSS"):
        issues.extend(_check_identifier(file_path, text, imports, exports, util))

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
