"""Install all pinned dependencies via Python (bypasses bat issues)."""
import subprocess
import sys
from pathlib import Path

print("=" * 60)
print(" Install pinned dependencies (Python script)")
print("=" * 60)
print()

# Find venv python
backend_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("C:/HTML_Protokol/code/hmp-backend")
venv_python = backend_dir / ".venv" / "Scripts" / "python.exe"

if not venv_python.exists():
    print(f"ERROR: venv not found at {venv_python}")
    sys.exit(1)

print(f"Using: {venv_python}")
print()

# Pinned dependencies (name, version)
deps = [
    ("fastapi", "0.115.6"),
    ("uvicorn", "0.32.0"),
    ("pydantic", "2.9.2"),
    ("pydantic_core", "2.23.4"),
    ("pydantic-settings", "2.6.1"),
    ("python-multipart", "0.0.18"),
    ("sqlalchemy", "2.0.36"),
    ("asyncpg", "0.30.0"),
    ("aiosqlite", "0.20.0"),
    ("cryptography", "43.0.1"),
    ("pyjwt", "2.9.0"),
    ("httpx", "0.27.2"),
    ("httpcore", "1.0.5"),
    ("h11", "0.16.0"),
    ("urllib3", "2.2.3"),
    ("sniffio", "1.3.1"),
    ("anyio", "4.4.0"),
    ("huggingface-hub", "0.24.7"),
    ("filelock", "3.15.4"),
    ("fsspec", "2024.9.0"),
    ("packaging", "24.1"),
    ("pyyaml", "6.0.2"),
    ("python-docx", "1.1.2"),
    ("Pillow", "10.4.0"),
    ("structlog", "24.4.0"),
    ("psutil", "5.9.8"),
    ("tenacity", "9.0.0"),
    ("orjson", "3.10.7"),
    ("faster-whisper", "1.0.3"),
    ("ctranslate2", "4.6.0"),
    ("tokenizers", "0.20.0"),
    ("python-dateutil", "2.9.0"),
    ("annotated_doc", "0.0.3"),
    ("annotated-types", "0.7.0"),
    ("click", "8.1.7"),
    ("httptools", "0.6.4"),
    ("starlette", "0.41.3"),
    ("websockets", "13.1"),
    ("watchfiles", "0.24.0"),
    ("python-dotenv", "1.0.1"),
    ("greenlet", "3.1.1"),
    ("tiktoken", "0.8.0"),
    ("distro", "1.9.0"),
    ("jiter", "0.8.2"),
    ("pycparser", "2.22"),
    ("cffi", "1.17.1"),
    ("pyparsing", "3.2.3"),
    ("iniconfig", "2.0.0"),
    ("pluggy", "1.5.0"),
    ("exceptiongroup", "1.2.2"),
    ("MarkupSafe", "3.0.2"),
    ("Jinja2", "3.1.4"),
    ("six", "1.16.0"),
    ("idna", "3.10"),
    ("certifi", "2024.8.30"),
    ("charset-normalizer", "3.4.2"),
    ("requests", "2.32.3"),
    ("bcrypt", "4.2.1"),
    ("argon2-cffi", "23.1.0"),
    ("colorama", "0.4.6"),
    ("pywin32", "310"),
    ("fastapi-utils", "0.7.0"),
    ("email-validator", "2.2.0"),
    ("itsdangerous", "2.2.0"),
    ("typing_extensions", "4.13.2"),
    ("typing-inspection", "0.4.0"),
    ("async_timeout", "4.0.3"),
    ("lxml", "5.3.0"),
    ("numpy", "1.26.4"),
]

total = len(deps)
print(f"Total packages: {total}")
print()

installed = 0
failed = []
for i, (pkg, ver) in enumerate(deps, 1):
    # E063: handle specifiers with operator (>=, >, <=, <) AND plain versions
    # If ver starts with operator, don't add ==
    if ver.startswith((">=", "<=", "!=", "==", ">", "<", "~=")):
        spec = f"{pkg}{ver}"  # already has operator
    else:
        spec = f"{pkg}=={ver}"  # plain version, add ==
    print(f"  [{i}/{total}] Installing {spec} ...", end=" ", flush=True)
    result = subprocess.run(
        [str(venv_python), "-m", "pip", "install",
         "--quiet", "--no-cache-dir", "--no-deps",
         "--index-url", "https://pypi.org/simple/",
         spec],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("OK", flush=True)
        installed += 1
    else:
        print(f"FAILED: {result.stderr[:200]}", flush=True)
        failed.append(spec)

print()
print(f"Step 1 complete: {installed} installed, {len(failed)} failed")
print()

# E063 retry: failed packages without --no-deps (lets pip resolve)
if failed:
    print(f"Retrying {len(failed)} failed packages WITH dependencies...")
    print()
    retry_ok = 0
    for spec in failed[:]:
        print(f"  Retry {spec}...", end=" ", flush=True)
        result = subprocess.run(
            [str(venv_python), "-m", "pip", "install",
             "--quiet", "--no-cache-dir",
             "--index-url", "https://pypi.org/simple/",
             spec],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("OK", flush=True)
            failed.remove(spec)
            retry_ok += 1
        else:
            print(f"FAILED: {result.stderr[:200]}", flush=True)
    print()
    print(f"Retry complete: {retry_ok} recovered")
    print()

# Install critical packages WITH dependencies
print("Installing critical packages WITH dependencies...")
critical = [
    "fastapi==0.115.6",
    "pydantic==2.9.2",
    "pydantic-settings==2.6.1",
    "asyncpg==0.30.0",
    "sqlalchemy==2.0.36",
]
for spec in critical:
    print(f"  Installing {spec} with deps...", flush=True)
    subprocess.run(
        [str(venv_python), "-m", "pip", "install",
         "--quiet", "--no-cache-dir",
         "--index-url", "https://pypi.org/simple/",
         spec],
        capture_output=True, text=True
    )

print()
print("=" * 60)
print(f" DONE: {installed} packages installed")
print("=" * 60)
if failed:
    print(f"Failed: {failed}")
print()
print("=" * 60)
print("Validating all required packages importable (E065)...")
print("=" * 60)
# Run comprehensive module check
check_script = str(Path(__file__).parent.parent / "code" / "hmp-backend" / "scripts" / "check_all_modules.py")
result = subprocess.run(
    [str(venv_python), check_script],
    capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print("=" * 60)
    print("AUTO-FIX: Installing missing critical packages...")
    print("=" * 60)
    # Install ALL transitive deps that may be missing
    deps_to_install = [
        # HTTP stack (E065, E066)
        "httpx", "httpcore", "h11", "sniffio", "anyio",
        "urllib3", "certifi", "charset-normalizer", "idna",
        # Whisper (E055)
        "faster-whisper", "ctranslate2", "tokenizers",
        # HuggingFace (E065)
        "huggingface-hub", "filelock", "fsspec", "packaging", "pyyaml",
        # DB
        "sqlalchemy", "asyncpg", "aiosqlite", "greenlet",
        # Validation
        "pydantic", "pydantic-core", "pydantic-settings",
        # Utilities
        "structlog", "tenacity", "orjson", "python-dotenv",
        "psutil", "python-dateutil", "python-multipart",
        # File formats
        "pillow", "python-docx", "lxml",
        # Auth
        "PyJWT", "bcrypt", "cryptography",
        # Core
        "fastapi", "uvicorn", "starlette", "click",
    ]
    # AUTO-FIX with verbose output (no --quiet) so user can see errors
    result = subprocess.run(
        [str(venv_python), "-m", "pip", "install",
         "--no-cache-dir",
         "--index-url", "https://pypi.org/simple/",
         *deps_to_install],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("PIP INSTALL ERROR (showing stderr):")
        print(result.stderr[:1000])
        print("Last lines of stdout:")
        print(result.stdout[-500:])
    print()
    print("Re-checking...")
    result = subprocess.run(
        [str(venv_python), check_script],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print("WARNING: Still missing modules!")
        print("Run install-deps-and-run.bat again to retry")
    else:
        print("OK: All required modules are now importable!")

print()
print("Now run: restart.bat")
