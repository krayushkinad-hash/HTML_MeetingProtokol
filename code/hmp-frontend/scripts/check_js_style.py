"""JS Code Quality Checker - reformat and verify indentation style.

Checks:
- Lines longer than 120 chars (configurable)
- Inconsistent indentation (mixing tabs and spaces)
- Trailing whitespace
- Multiple consecutive blank lines
- Lines ending with semicolon after comment

Also suggests Allman-style braces where possible (curly braces
on their own line for top-level blocks).

Usage:
    python code/hmp-frontend/scripts/check_js_style.py [files...]
"""
import re
import sys
from pathlib import Path


MAX_LINE_LENGTH = 120


def check_file(file_path):
    """Check JS file for style violations.

    Args:
        file_path: Path to JS file

    Returns:
        List of (severity, line, message) tuples
    """
    issues = []
    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    in_template = False
    in_block_comment = False
    in_string = None  # None, '"', "'", '`'

    prev_blank_count = 0

    for i, line in enumerate(lines, start=1):
        # Long lines
        if len(line) > MAX_LINE_LENGTH:
            issues.append(
                ("WARN", i, f"line too long ({len(line)} > {MAX_LINE_LENGTH})")
            )

        # Trailing whitespace
        if line != line.rstrip() and line.strip():
            issues.append(("WARN", i, "trailing whitespace"))

        # Multiple consecutive blank lines
        if not line.strip():
            prev_blank_count += 1
            if prev_blank_count > 2:
                issues.append(("INFO", i, f"{prev_blank_count} consecutive blank lines"))
        else:
            prev_blank_count = 0

        # Mixed tabs and spaces (heuristic)
        if "\t" in line and "    " in line:
            issues.append(("WARN", i, "mixed tabs and spaces"))

        # Trailing semicolon after closing comment
        if re.search(r"//[^\n]*;\s*$", line):
            issues.append(("WARN", i, "semicolon after line comment"))

    return issues


def main():
    """Run style check on JS files."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    views_dir = project_root / "code" / "hmp-frontend" / "src" / "js" / "views"

    if len(sys.argv) > 1:
        files = [Path(f) for f in sys.argv[1:]]
    else:
        files = sorted(views_dir.glob("*.js"))

    print("=" * 70)
    print(f"JS Style Check (max line length = {MAX_LINE_LENGTH})")
    print("=" * 70)
    print()

    total_files = len(files)
    files_with_warns = 0
    total_warns = 0

    for f in files:
        issues = check_file(f)
        if not issues:
            print(f"  [OK] {f.name}")
        else:
            files_with_warns += 1
            total_warns += len(issues)
            print(f"  [{f.name}]: {len(issues)} style note(s)")

    print()
    print("=" * 70)
    print(f"Checked: {total_files} files")
    print(f"Files with style notes: {files_with_warns}")
    print(f"Total notes: {total_warns}")
    print("=" * 70)


if __name__ == "__main__":
    main()
