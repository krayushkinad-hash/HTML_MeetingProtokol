"""Check for duplicate package entries in pinned deps list.

When adding new packages to install_pinned_deps.py or
requirements-minimal.txt, sometimes the same package is added twice
(with different versions, or accidentally twice).

This script:
1. Reads install_pinned_deps.py and checks for duplicate (pkg, version)
2. Reads requirements-minimal.txt and checks for duplicates
3. Reads requirements-complete.txt and checks for duplicates

Usage:
    python code/hmp-backend/scripts/check_duplicate_packages.py

Exit codes:
    0 - no duplicates
    1 - duplicates found (with remediation hints)
"""
import re
import sys
from pathlib import Path


def check_duplicates_in_pinned_script(script_path):
    """Check install_pinned_deps.py for duplicate package entries.

    Returns:
        List of (pkg_name, version, line_no) tuples
    """
    text = script_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    seen = {}  # pkg -> (version, line_no)
    duplicates = []

    for i, line in enumerate(lines, start=1):
        # Match (pkg, version) tuples
        m = re.search(r'\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)', line)
        if m:
            pkg, ver = m.group(1), m.group(2)
            if pkg in seen:
                prev_ver, prev_line = seen[pkg]
                duplicates.append(
                    (pkg, [ver, prev_ver], sorted([i, prev_line]))
                )
            else:
                seen[pkg] = (ver, i)

    return duplicates


def check_duplicates_in_requirements(req_path):
    """Check requirements*.txt for duplicate package lines.

    Returns:
        List of (pkg_name, line_no_list) tuples
    """
    if not req_path.exists():
        return []

    text = req_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    seen = {}
    duplicates = []

    for i, line in enumerate(lines, start=1):
        # Skip comments and blank
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        # Get package name (before ==, >=, <=, >, <, ~=, !=)
        pkg = re.split(r"[><=!~]", line_stripped)[0].strip()
        if not pkg:
            continue

        if pkg in seen:
            duplicates.append((pkg, sorted([seen[pkg], i])))
        else:
            seen[pkg] = i

    return duplicates


def check_internal_consistency(script_path, req_path, complete_path):
    """Check that packages in script are also in requirements files.

    Returns:
        List of (pkg, where) tuples for inconsistencies
    """
    issues = []

    # Read pinned script packages
    script_pkgs = set()
    if script_path.exists():
        text = script_path.read_text(encoding="utf-8")
        for m in re.findall(r'\(\s*["\']([^"\']+)["\']\s*,', text):
            script_pkgs.add(m)

    # Read requirements-minimal
    req_pkgs = set()
    if req_path.exists():
        for line in req_path.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg = re.split(r"[><=!~]", line)[0].strip()
            if pkg:
                req_pkgs.add(pkg)

    # Packages in script but not in requirements-minimal
    for pkg in script_pkgs:
        # Normalize: pydantic-settings matches pydantic-settings in reqs
        req_name = pkg.lower().replace("_", "-")
        in_req = any(req_name == r.lower().replace("_", "-") for r in req_pkgs)
        if not in_req:
            issues.append((pkg, "missing from requirements-minimal.txt"))

    return issues


def main():
    """Check for duplicates in all package files."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    backend = project_root / "code" / "hmp-backend"

    script = backend / ".." / ".." / "scripts" / "install_pinned_deps.py"
    req_minimal = backend / "requirements-minimal.txt"
    req_complete = backend / "requirements-complete.txt"

    print("=" * 70)
    print("Duplicate Package Check (E067)")
    print("=" * 70)
    print()

    total_issues = 0

    # 1. Check install_pinned_deps.py
    if script.exists():
        dups = check_duplicates_in_pinned_script(script)
        if dups:
            print(f"[FAIL] {script.name}:")
            for pkg, versions, line_nos in dups:
                print(f"  - {pkg} duplicated")
                for v, ln in zip(versions, line_nos):
                    print(f"      line {ln}: ({pkg}, {v})")
            total_issues += len(dups)
        else:
            print(f"[OK] {script.name}: no duplicates")

    # 2. Check requirements-minimal.txt
    dups = check_duplicates_in_requirements(req_minimal)
    if dups:
        print(f"\n[FAIL] {req_minimal.name}:")
        for pkg, line_nos in dups:
            print(f"  - {pkg} at lines {line_nos}")
        total_issues += len(dups)
    else:
        print(f"\n[OK] {req_minimal.name}: no duplicates")

    # 3. Check requirements-complete.txt
    dups = check_duplicates_in_requirements(req_complete)
    if dups:
        print(f"\n[FAIL] {req_complete.name}:")
        for pkg, line_nos in dups:
            print(f"  - {pkg} at lines {line_nos}")
        total_issues += len(dups)
    else:
        print(f"\n[OK] {req_complete.name}: no duplicates")

    # 4. Cross-check consistency
    consistency = check_internal_consistency(script, req_minimal, req_complete)
    if consistency:
        print("\n[WARN] Inconsistencies (packages in script but not in requirements):")
        for pkg, where in consistency:
            print(f"  - {pkg}: {where}")

    print()
    print("=" * 70)
    print(f"Total duplicate issues: {total_issues}")
    print("=" * 70)

    if total_issues == 0:
        print("\n[OK] No duplicate packages found")
        sys.exit(0)
    else:
        print(f"\n[FAILED] {total_issues} duplicate(s) found")
        print("\nFIX: Open the file and remove duplicate entries.")
        print("For install_pinned_deps.py, find lines like:")
        print('    ("anyio", "4.4.0"),')
        print('    ("anyio", "4.6.2"),  <-- DELETE this duplicate')
        sys.exit(1)


if __name__ == "__main__":
    main()
