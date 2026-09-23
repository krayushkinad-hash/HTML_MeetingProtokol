"""Check that all required packages are importable.

US-065: After running install-deps-and-run.bat, the venv should have
ALL transitive dependencies installed. If `pip install --no-deps`
was used, httpcore/h11/sniffio/anyio/huggingface_hub_extras might be
missing.

Usage:
    python code/hmp-backend/scripts/check_required_packages.py

Exit codes:
    0 - all required packages import OK
    1 - some packages missing (list printed)
"""
import sys
from pathlib import Path

# All packages that MUST be importable for HMP backend
# Critical: backend will not start without these
REQUIRED_PACKAGES = [
    # Core
    ("fastapi", "FastAPI web framework"),
    ("uvicorn", "ASGI server"),
    ("pydantic", "Data validation"),
    ("pydantic_settings", "Settings management"),
    ("asyncpg", "Async PostgreSQL driver"),
    ("sqlalchemy", "ORM"),
    # HTTP client (httpx + transitive)
    ("httpx", "HTTP client"),
    ("httpcore", "HTTP core (E065 - required by httpx)"),
    ("h11", "HTTP/1.1 protocol (E065)"),
    ("urllib3", "HTTP client (E066 - required by requests)"),
    ("certifi", "SSL certificates (required by urllib3)"),
    ("charset_normalizer", "Encoding detection (required by requests)"),
    ("idna", "IDNA encoding (required by requests)"),
    ("sniffio", "Async library detection (E065)"),
    ("anyio", "Async wrapper (E065)"),
    # Whisper
    ("faster_whisper", "Whisper transcription"),
    # HuggingFace Hub + transitive deps (E065)
    ("huggingface_hub", "Model downloads (US-058)"),
    ("filelock", "File locking (huggingface_hub dep)"),
    ("fsspec", "Filesystem interface (huggingface_hub dep)"),
    ("packaging", "Version parsing (huggingface_hub dep)"),
    ("yaml", "YAML parsing (huggingface_hub dep)"),
    # File formats
    ("docx", "python-docx for DOCX export"),
    ("PIL", "Pillow for image processing"),
    ("lxml", "XML parsing for DOCX"),
    # OpenAI-compatible API
    ("openai", "OpenAI client (LLM providers)"),
    # Auth
    ("jwt", "PyJWT"),
    ("bcrypt", "Password hashing"),
    # Utilities
    ("structlog", "Structured logging"),
    ("tenacity", "Retry logic"),
    ("orjson", "Fast JSON parser"),
]

# Optional but recommended
OPTIONAL_PACKAGES = [
    ("uvicorn", None),  # shown if installed
]


def check_packages():
    """Check each required package can be imported.

    Returns:
        (missing, present) - lists of tuples
    """
    missing = []
    present = []

    for pkg_name, description in REQUIRED_PACKAGES:
        try:
            __import__(pkg_name)
            present.append((pkg_name, description))
        except ImportError as e:
            missing.append((pkg_name, str(e)))

    return missing, present


def get_install_commands(missing):
    """Generate pip install commands for missing packages.

    Returns:
        List of (pkg_name, install_command) tuples
    """
    commands = []
    for pkg_name, _ in missing:
        # Map import name to pip name
        pip_name = {
            "PIL": "Pillow",
            "docx": "python-docx",
            "yaml": "PyYAML",
            "jwt": "PyJWT",
            "faster_whisper": "faster-whisper",
        }.get(pkg_name, pkg_name.replace("_", "-"))

        commands.append(
            (pkg_name, f"pip install --index-url https://pypi.org/simple/ {pip_name}")
        )

    return commands


def main():
    """Check all required packages and report."""
    print("=" * 70)
    print("Required Packages Check (E065 - transitive deps)")
    print("=" * 70)
    print()

    missing, present = check_packages()

    print(f"Total required: {len(REQUIRED_PACKAGES)}")
    print(f"Present: {len(present)}")
    print(f"Missing: {len(missing)}")
    print()

    if present:
        print("[OK] Available packages:")
        for pkg, desc in present:
            print(f"  + {pkg:25s}  {desc or ''}")

    if missing:
        print()
        print("[FAIL] Missing packages:")
        for pkg, error in missing:
            print(f"  - {pkg:25s}  ERROR: {error}")

        print()
        print("=" * 70)
        print("FIX: Run these commands:")
        print("=" * 70)
        for pkg, cmd in get_install_commands(missing):
            print(f"  {cmd}")

        sys.exit(1)
    else:
        print()
        print("[OK] All required packages are importable")
        sys.exit(0)


if __name__ == "__main__":
    main()
