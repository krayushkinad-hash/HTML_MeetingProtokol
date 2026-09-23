"""Test that all required imports work for backend."""
import sys


def test_imports():
    modules = [
        "fastapi",
        "uvicorn",
        "starlette",
        "click",
        "pydantic",
        "pydantic_core",
        "pydantic_settings",
        "asyncpg",
        "sqlalchemy",
        "aiosqlite",
        "lxml",
        "PIL",
        "docx",  # python-docx
        "anyio",
        "typing_inspection",
        "annotated_doc",
    ]
    versions = {
        "fastapi": "0.115.6",
        "pydantic": "2.9.2",
        "pydantic_core": "2.23.4",
        "starlette": "0.41.3",
    }
    failed = []
    for mod in modules:
        try:
            __import__(mod)
            print(f"  [OK] {mod}")
        except ImportError as e:
            print(f"  [FAIL] {mod}: {e}")
            failed.append(mod)

    # Check versions
    print("\nVersions:")
    for mod, expected in versions.items():
        try:
            actual_mod = __import__(mod)
            actual = getattr(actual_mod, "__version__", "?")
            status = "[OK]" if actual.startswith(expected) else "[WARN]"
            print(f"  {status} {mod}: {actual} (expected {expected})")
        except Exception as e:
            print(f"  [FAIL] {mod}: {e}")

    if failed:
        print(f"\nFAILED modules: {', '.join(failed)}")
        return 1
    print("\nAll imports OK")
    return 0


if __name__ == "__main__":
    sys.exit(test_imports())
