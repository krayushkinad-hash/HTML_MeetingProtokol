"""Check that faster-whisper and ALL transitive deps are importable.

US-005, E055, E056: Validation script for install-faster-whisper.bat.

Usage:
    python scripts/check_whisper_deps.py

Exits 0 if all modules importable, 1 if any are missing.
Prints detailed info to stderr.
"""
import sys
import time
import importlib


REQUIRED_MODULES = [
    ("faster_whisper", None),
    ("ctranslate2", None),
    ("tokenizers", None),
    ("urllib3", None),
    ("requests", None),
    ("huggingface_hub", None),
    ("numpy", None),
]


def check_imports():
    """Check that all required modules can be imported."""
    errors = []
    print("=" * 60, file=sys.stderr)
    print("Importing modules...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    for mod_name, _ in REQUIRED_MODULES:
        try:
            m = importlib.import_module(mod_name)
            version = getattr(m, '__version__', 'unknown')
            print(f"  [OK]  {mod_name:<20s} {version}", file=sys.stderr)
        except ImportError as e:
            print(f"  [FAIL] {mod_name:<20s} {e}", file=sys.stderr)
            errors.append((mod_name, str(e)))

    print("=" * 60, file=sys.stderr)
    if errors:
        print(f"FAILED: {len(errors)} modules", file=sys.stderr)
        for mod, err in errors:
            print(f"  - {mod}: {err}", file=sys.stderr)
        return False

    print(f"OK: all {len(REQUIRED_MODULES)} modules imported", file=sys.stderr)
    return True


def test_model_load():
    """Test that tiny model can be loaded (~30-90 sec on CPU)."""
    print("=" * 60, file=sys.stderr)
    print("Loading tiny model for smoke test...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    start = time.time()
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel('tiny', device='cpu', compute_type='int8')
        elapsed = time.time() - start
        print(f"  [OK] Model loaded in {elapsed:.1f}s", file=sys.stderr)
        return True
    except Exception as e:
        print(f"  [FAIL] {e}", file=sys.stderr)
        return False


def main():
    """Run all checks (or specific mode). Exits 0 if pass, 1 if fail."""
    print("=" * 60, file=sys.stderr)
    print("check_whisper_deps.py", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Python: {sys.executable}", file=sys.stderr)
    print(f"Version: {sys.version}", file=sys.stderr)
    print(f"Prefix: {sys.prefix}", file=sys.stderr)
    print(file=sys.stderr)

    # Parse simple CLI args
    args = sys.argv[1:]
    check_only = "--check-only" in args
    test_model = "--test-model" in args

    # Step 1: imports
    imports_ok = check_imports()
    if not imports_ok:
        sys.exit(1)

    # --check-only: only check imports, no model load
    if check_only:
        sys.exit(0)

    print(file=sys.stderr)

    # Step 2: model load (with timer)
    model_ok = test_model_load()
    if not model_ok:
        print("WARN: Model load failed but imports are OK", file=sys.stderr)
        if test_model:
            # --test-model: fail exit
            sys.exit(1)
        # Default mode: don't fail if model load fails (still OK)
        sys.exit(0)

    print("=" * 60, file=sys.stderr)
    print("ALL CHECKS PASSED", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
