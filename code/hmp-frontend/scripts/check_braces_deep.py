"""Deep quality check for JS files - syntax + extra close paren detector.

This script uses Node.js for syntax checking (most reliable) and adds
a custom E062 detector for the specific pattern of "extra `});` before
function close" that broke settings.js multiple times.

Usage:
    python code/hmp-frontend/scripts/check_braces_deep.py [files...]

Exit codes:
    0 - all OK
    1 - issues found

Errors detected:
    SYNTAX  - node --check failed (mismatched braces, unclosed blocks)
    EXTRA   - suspicious extra `});` before function close (E062)
    TEMPLATE - odd number of backticks (unclosed template literal)
"""
import re
import subprocess
import sys
from pathlib import Path


def check_js_syntax(file_path):
    """Run node --check, return stderr if any.

    Args:
        file_path: Path to JS file

    Returns:
        Error message string or None if syntax is OK
    """
    try:
        result = subprocess.run(
            ["node", "--check", str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return result.stderr.strip()
        return None
    except FileNotFoundError:
        return "node: command not found"
    except Exception as e:
        return str(e)


def check_extra_close_paren_at_eof(text):
    """Detect extra `});` before function close (E062).

    Real-world buggy pattern that broke settings.js multiple times:

        content.querySelector('#x')?.addEventListener('click', () => {
            doSomething();
        });       <-- extra addEventListener close
                  <-- lost the function-level close
    }              <-- closes renderSettingsView - mismatched

    E223: heuristic с проверкой ГЛУБИНЫ фигурных скобок.
    Валидный `});\\n}` идёт при depth >= 1 (внутри функции).
    Подозрительный — при depth == 0 (глобальный уровень).
    """
    issues = []
    # Match `});` followed by newline and `}`
    pattern = re.compile(r"\}\);\s*\n\s*\}", re.MULTILINE)

    def _brace_depth_before(text, pos):
        """E223: считает глубину { в text[:pos] (без учёта строк/комментов)."""
        depth = 0
        in_str = None  # None | '"' | "'" | '`'
        i = 0
        while i < pos:
            ch = text[i]
            if in_str:
                if ch == '\\' and i + 1 < pos:
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
            elif ch in ('"', "'", '`'):
                in_str = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            i += 1
        return depth

    for match in pattern.finditer(text):
        line_no = text[:match.start()].count("\n") + 1

        # Check what's right after
        after = text[match.end():match.end() + 200].lstrip()

        # Only suspicious if followed by exported function or top-level
        # (not inside a Promise .then().catch() chain)
        if not after.startswith(
            (
                "export function",
                "export async function",
                "export default",
                "export const",
                "export class",
            )
        ):
            continue

        # E223: только для глобального уровня (depth == 0 перед `});`)
        depth_before = _brace_depth_before(text, match.start())
        if depth_before >= 1:
            # Внутри функции — это валидный код, не подозрительный
            continue

        # Strip strings/comments in context (500 chars before)
        ctx = text[max(0, match.start() - 500):match.start()]
        ctx_clean = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', "", ctx)
        ctx_clean = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "", ctx_clean)
        ctx_clean = re.sub(r"`[^`]*`", "", ctx_clean)
        ctx_clean = re.sub(r"//[^\n]*", "", ctx_clean)

        if ctx_clean.count("(") == ctx_clean.count(")"):
            issues.append(
                (line_no, "possible extra `});` before function close (E062)")
            )

    return issues


def check_unclosed_template_literal(text):
    """Detect unclosed template literal (odd number of backticks).

    Args:
        text: JS file content

    Returns:
        List of (line, message) tuples
    """
    issues = []
    bt_count = text.count("`")
    if bt_count % 2 != 0:
        # Find last backtick
        last_bt = text.rfind("`")
        last_line = text[:last_bt].count("\n") + 1
        issues.append(
            (last_line, "unclosed template literal (odd backtick count)")
        )
    return issues


def check_file(file_path):
    """Run all checks on a single file.

    Args:
        file_path: Path to JS file

    Returns:
        List of (level, message) tuples
    """
    issues = []

    # 1. node --check (syntax) - hard fail
    syntax_err = check_js_syntax(file_path)
    if syntax_err:
        issues.append(("SYNTAX", syntax_err))
        return issues  # can't do other checks reliably

    text = file_path.read_text(encoding="utf-8")

    # 2. Extra ); at function end (E062)
    for ln, msg in check_extra_close_paren_at_eof(text):
        issues.append(("EXTRA", f"line {ln} - {msg}"))

    # 3. Unclosed template literal
    for ln, msg in check_unclosed_template_literal(text):
        issues.append(("TEMPLATE", f"line {ln} - {msg}"))

    return issues


def main():
    """Run quality check on all view JS files + client.js."""
    # Path: .../code/hmp-frontend/scripts/check_braces_deep.py
    # We want: .../HTML_MeetingProtokol (project root)
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    views_dir = (
        project_root / "code" / "hmp-frontend" / "src" / "js" / "views"
    )

    if len(sys.argv) > 1:
        files = [Path(f) for f in sys.argv[1:]]
    else:
        files = sorted(views_dir.glob("*.js"))
        client = (
            project_root / "code" / "hmp-frontend" / "src" / "js" / "api" / "client.js"
        )
        if client.exists():
            files.append(client)

    print("=" * 70)
    print("Deep JS Quality Check (E062 - extra `});`, E064 - unclosed)")
    print("=" * 70)
    print()

    total_files = len(files)
    files_with_issues = 0
    total_issues = 0

    for f in files:
        issues = check_file(f)
        if not issues:
            print(f"  [OK] {f.name}")
        else:
            files_with_issues += 1
            total_issues += len(issues)
            print(f"  [FAIL] {f.name}:")
            for level, msg in issues[:5]:
                print(f"    [{level}] {msg[:140]}")
            if len(issues) > 5:
                print(f"    ... ({len(issues) - 5} more)")

    print()
    print("=" * 70)
    print(f"Checked: {total_files} files")
    print(f"Files with issues: {files_with_issues}")
    print(f"Total issues: {total_issues}")
    print("=" * 70)

    if files_with_issues == 0:
        print("\n[OK] All JS files pass deep quality check")
        sys.exit(0)
    else:
        print(f"\n[FAILED] {files_with_issues} file(s) have issues")
        sys.exit(1)


if __name__ == "__main__":
    main()
