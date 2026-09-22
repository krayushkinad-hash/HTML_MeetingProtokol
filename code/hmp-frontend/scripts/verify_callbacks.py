"""Verify that all functions referenced in addEventListener are defined.

US-067 E020 prevention. Run after ANY changes to JS files.

Usage:
    python scripts/verify_callbacks.py verify         # Auto-backup + check
    python scripts/verify_callbacks.py backup         # Manual backup
    python scripts/verify_callbacks.py list           # List backups
    python scripts/verify_callbacks.py restore        # Restore latest

If errors found:
    python scripts/verify_callbacks.py list           # See backups
    diff backup_xxx/file.js src/js/views/file.js      # Compare
    # OR
    python scripts/verify_callbacks.py restore --from backup_xxx
"""
import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

JS_DIR = Path(__file__).parent.parent / "src" / "js"
BACKUP_DIR = Path(__file__).parent.parent / ".backups"


def find_handlers_in_js(js_file):
    """Extract addEventListener handler references from JS file."""
    text = js_file.read_text(encoding="utf-8")
    handlers = []

    # Pattern 1: addEventListener('event', handlerName)
    # Handler name is identifier (a-z_, 0-9) - not arrow function
    for m in re.finditer(
        r"\.addEventListener\(['\"]([\w-]+)['\"],\s*([a-z_][a-z0-9_]*)\)",
        text,
    ):
        handler = m.group(2)
        if handler not in ("async", "await", "function"):
            handlers.append((m.group(1), handler, text[:m.start()].count("\n") + 1))

    # Pattern 2: addEventListener('event', () => handler(...))
    # or: addEventListener('event', async () => handler(...))
    for m in re.finditer(
        r"\.addEventListener\(['\"]([\w-]+)['\"],[^,]*,\s*(?:async\s+)?\(\)\s*=>\s*([a-z_][a-z0-9_]*)\s*\(",
        text,
    ):
        handler = m.group(2)
        if handler not in ("async", "await", "function"):
            handlers.append((m.group(1), handler, text[:m.start()].count("\n") + 1))

    return handlers


def is_function_defined(js_file, func_name):
    """Check if function is defined anywhere in file."""
    text = js_file.read_text(encoding="utf-8")
    patterns = [
        rf"\bfunction\s+{func_name}\s*\(",
        rf"\basync\s+function\s+{func_name}\s*\(",
        rf"\bconst\s+{func_name}\s*=\s*(?:async\s+)?\(",
        rf"\blet\s+{func_name}\s*=\s*(?:async\s+)?\(",
        # class methods: name(args) { ... }
        rf"^\s+{func_name}\s*\([^)]*\)\s*\{{",
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.MULTILINE):
            return True
    return False


def check_handlers_in_file(js_file):
    """Check all handlers in one JS file."""
    handlers = find_handlers_in_js(js_file)
    missing = []

    for event, handler, line_no in handlers:
        if not is_function_defined(js_file, handler):
            missing.append((event, handler, line_no, js_file.name))

    return missing


def check_all_js_files():
    """Check all JS files for missing handler functions."""
    all_missing = []
    files_checked = 0

    for js_file in JS_DIR.rglob("*.js"):
        if "node_modules" in str(js_file):
            continue
        files_checked += 1
        missing = check_handlers_in_file(js_file)
        all_missing.extend(missing)

    return all_missing, files_checked


def create_backup():
    """Create timestamped backup of all JS files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_DIR / f"backup_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    files_backed_up = 0
    for js_file in JS_DIR.rglob("*.js"):
        if "node_modules" in str(js_file):
            continue

        relative = js_file.relative_to(JS_DIR.parent)
        dest = backup_dir / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(js_file, dest)
        files_backed_up += 1

    # Manifest
    manifest = backup_dir / "MANIFEST.txt"
    with open(manifest, "w", encoding="utf-8") as f:
        f.write(
            f"Backup created at {timestamp}\n"
            f"Files: {files_backed_up}\n"
            f"Source: {JS_DIR}\n"
        )

    return backup_dir, files_backed_up


def restore_from_backup(backup_dir):
    """Restore JS files from backup."""
    restored = 0
    for backup_file in backup_dir.rglob("*"):
        if backup_file.is_file() and backup_file.suffix == ".js":
            relative = backup_file.relative_to(backup_dir)
            target = JS_DIR.parent / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_file, target)
            restored += 1
    return restored


def list_backups():
    """List all available backups."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.iterdir(), reverse=True)


def main():
    parser = argparse.ArgumentParser(
        description="Verify all JS callbacks defined + backup/restore (E020 prevention)"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("verify", help="Auto-backup + check all handlers defined")

    backup_p = sub.add_parser("backup", help="Create timestamped backup")
    backup_p.add_argument("--label", help="Optional label")

    restore_p = sub.add_parser("restore", help="Restore from backup")
    restore_p.add_argument("--from", dest="from_backup", required=True,
                           help="Backup name (e.g., backup_20260921_191943)")

    sub.add_parser("list", help="List backups")

    diff_p = sub.add_parser("diff", help="Diff current vs backup")
    diff_p.add_argument("--from", dest="from_backup", required=True,
                        help="Backup name")
    diff_p.add_argument("file", help="JS file relative to src/")

    args = parser.parse_args()

    if args.command == "verify":
        print("=" * 70)
        print("E020 CHECK: All addEventListener callbacks defined?")
        print("=" * 70)

        # Step 1: Auto-backup
        backup_dir, count = create_backup()
        print(f"\n[1/2] Auto-backup created: {backup_dir.name} ({count} files)")

        # Step 2: Verify
        missing, files_checked = check_all_js_files()
        print(f"[2/2] Checked {files_checked} JS files")

        if missing:
            print(f"\n!!! {len(missing)} MISSING HANDLER(S):\n")
            for event, handler, line_no, file_name in missing:
                print(f"  {file_name}:{line_no} — "
                      f"addEventListener('{event}', ...{handler}(...))")
                print(f"    -> function {handler} is NOT defined!")
            print(f"\nFix needed. Compare with backup:")
            print(f"  diff {JS_DIR}/<file>.js .backups/{backup_dir.name}/src/js/<file>.js")
            sys.exit(1)
        else:
            print("\nAll callbacks defined OK")
            sys.exit(0)

    elif args.command == "backup":
        if args.label:
            backup_dir = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.label}"
        else:
            backup_dir, count = create_backup()
            print(f"Backup created: {backup_dir}")
            print(f"Files: {count}")
            return
        backup_dir, count = create_backup()
        print(f"Backup created: {backup_dir}")
        print(f"Files: {count}")

    elif args.command == "list":
        print("Available backups (most recent first):")
        for b in list_backups()[:20]:
            manifest = b / "MANIFEST.txt"
            if manifest.exists():
                first_line = manifest.read_text(encoding="utf-8").split("\n")[0]
                print(f"  {b.name}  ({first_line})")
            else:
                print(f"  {b.name}")

    elif args.command == "restore":
        backup_path = BACKUP_DIR / args.from_backup
        if not backup_path.exists():
            print(f"Backup not found: {backup_path}")
            sys.exit(1)

        count = restore_from_backup(backup_path)
        print(f"Restored {count} files from {backup_path.name}")

    elif args.command == "diff":
        backup_path = BACKUP_DIR / args.from_backup
        if not backup_path.exists():
            print(f"Backup not found")
            sys.exit(1)

        target = JS_DIR.parent / "src" / "js" / args.file
        bkp_file = backup_path / "src" / "js" / args.file

        if not target.exists():
            print(f"Current file not found: {target}")
            sys.exit(1)
        if not bkp_file.exists():
            print(f"Backup file not found: {bkp_file}")
            sys.exit(1)

        # Use system diff
        subprocess_result = subprocess.run(
            ["diff", "-u", str(bkp_file), str(target)],
            capture_output=False,
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
