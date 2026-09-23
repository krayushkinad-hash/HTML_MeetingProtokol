"""Comprehensive catalog of ALL Python modules used by HMP backend.

HMP uses a layered architecture:
1. Core web framework (FastAPI/Starlette/Uvicorn)
2. Database (SQLAlchemy/asyncpg/aiosqlite)
3. Validation (Pydantic)
4. HTTP clients (httpx + transitive)
5. External APIs (OpenAI-compatible)
6. Whisper transcription (faster_whisper + ctranslate2)
7. Model downloads (huggingface_hub + transitive)
8. Authentication (PyJWT/bcrypt)
9. Document generation (python-docx + Pillow)
10. Utilities (structlog/tenacity/orjson)

Each entry maps:
- import_name: how to import in Python
- pip_name: how to install via pip
- description: what it does
- category: which layer
- required: True (backend won't start) / False (optional)
"""
import sys
from pathlib import Path

# Each tuple: (import_name, pip_name, description, category, required)
ALL_MODULES = [
    # ================================================================
    # LAYER 1: Core Web Framework
    # ================================================================
    ("fastapi", "fastapi==0.115.6", "FastAPI web framework", "core", True),
    ("uvicorn", "uvicorn==0.32.0", "ASGI server", "core", True),
    ("starlette", "starlette==0.41.3", "ASGI toolkit (FastAPI base)", "core", True),
    ("websockets", "websockets==13.1", "WebSocket support", "core", False),
    ("watchfiles", "watchfiles==0.24.0", "File watcher (uvicorn --reload)", "core", False),
    ("httptools", "httptools==0.6.4", "HTTP parsing (uvicorn)", "core", False),
    ("anyio", "anyio==4.4.0", "Async I/O abstraction (E065)", "core", True),
    ("sniffio", "sniffio==1.3.1", "Async library detection (E065)", "core", True),
    ("h11", "h11==0.16.0", "HTTP/1.1 protocol (E065)", "core", True),

    # ================================================================
    # LAYER 2: Database
    # ================================================================
    ("sqlalchemy", "sqlalchemy==2.0.36", "SQLAlchemy ORM", "db", True),
    ("asyncpg", "asyncpg==0.30.0", "Async PostgreSQL driver", "db", True),
    ("aiosqlite", "aiosqlite==0.20.0", "Async SQLite driver", "db", False),
    ("alembic", "alembic==1.13.3", "DB migrations", "db", False),
    ("greenlet", "greenlet==3.1.1", "Lightweight concurrency (SQLAlchemy)", "db", True),

    # ================================================================
    # LAYER 3: Data Validation
    # ================================================================
    ("pydantic", "pydantic==2.9.2", "Data validation", "validation", True),
    ("pydantic_settings", "pydantic-settings==2.6.1", "Settings management", "validation", True),
    ("pydantic_core", "pydantic-core==2.23.4", "Pydantic core (Rust)", "validation", True),
    ("annotated_types", "annotated-types==0.7.0", "Annotated types for Pydantic", "validation", False),
    ("typing_extensions", "typing-extensions==4.13.2", "Backported typing", "validation", True),
    ("typing_inspection", "typing-inspection==0.4.0", "Runtime type inspection", "validation", False),
    ("email_validator", "email-validator==2.2.0", "Email validation", "validation", False),

    # ================================================================
    # LAYER 4: HTTP Client Stack (E065, E066)
    # ================================================================
    ("httpx", "httpx==0.27.2", "HTTP client", "http", True),
    ("httpcore", "httpcore==1.0.5", "HTTP core (E065)", "http", True),
    ("urllib3", "urllib3==2.2.3", "HTTP client (E066)", "http", True),
    ("certifi", "certifi==2024.8.30", "SSL certificates (E066)", "http", True),
    ("charset_normalizer", "charset-normalizer==3.4.2", "Encoding detection (E066)", "http", True),
    ("idna", "idna==3.10", "IDNA encoding", "http", True),
    ("requests", "requests==2.32.3", "HTTP for Humans", "http", False),
    ("urllib", None, "Standard library", "http", True),  # stdlib, no install

    # ================================================================
    # LAYER 5: External APIs (OpenAI-compatible)
    # ================================================================
    ("openai", "openai>=1.50.0,<2.0.0", "OpenAI SDK (LLM providers)", "ai", False),
    ("tiktoken", "tiktoken==0.8.0", "OpenAI tokenizer", "ai", False),
    ("distro", "distro==1.9.0", "OS detection (openai dep)", "ai", False),
    ("jiter", "jiter==0.8.2", "JSON parser (openai dep)", "ai", False),

    # ================================================================
    # LAYER 6: Whisper Transcription
    # ================================================================
    ("faster_whisper", "faster-whisper==1.0.3", "Whisper transcription", "whisper", True),
    # ctranslate2 is a C++ library, imported via faster_whisper, but has Python bindings
    # Its pip package is 'ctranslate2'

    # ================================================================
    # LAYER 7: Model Downloads (HuggingFace Hub)
    # ================================================================
    ("huggingface_hub", "huggingface-hub>=0.20.0,<1.0.0", "Model downloads (US-058)", "hf", True),
    ("filelock", "filelock>=3.13.0", "File locking (hf_hub dep)", "hf", True),
    ("fsspec", "fsspec>=2024.6.0", "Filesystem interface (hf_hub dep)", "hf", True),
    ("packaging", "packaging>=24.0", "Version parsing (hf_hub dep)", "hf", True),
    ("yaml", "pyyaml>=6.0", "YAML parsing (hf_hub dep)", "hf", True),

    # ================================================================
    # LAYER 8: Authentication & Security
    # ================================================================
    ("jwt", "PyJWT==2.9.0", "JWT tokens", "auth", True),
    ("bcrypt", "bcrypt==4.2.1", "Password hashing", "auth", True),
    ("argon2", "argon2-cffi==23.1.0", "Argon2 password hashing", "auth", False),
    ("cryptography", "cryptography==43.0.1", "Cryptographic primitives", "auth", True),
    ("pycparser", "pycparser==2.22", "C parser (cryptography dep)", "auth", False),
    ("cffi", "cffi==1.17.1", "C Foreign Function Interface (cryptography dep)", "auth", False),

    # ================================================================
    # LAYER 9: Document Generation
    # ================================================================
    ("docx", "python-docx==1.1.2", "DOCX export", "docs", True),
    ("docxcompose", "docxcompose", "DOCX composition", "docs", False),
    ("PIL", "Pillow==10.4.0", "Image processing", "docs", True),
    ("lxml", "lxml==5.3.0", "XML parsing (python-docx dep)", "docs", True),

    # ================================================================
    # LAYER 10: Utilities
    # ================================================================
    ("structlog", "structlog==24.4.0", "Structured logging", "utils", True),
    ("tenacity", "tenacity==9.0.0", "Retry logic", "utils", True),
    ("orjson", "orjson==3.10.7", "Fast JSON parser", "utils", True),
    ("dotenv", "python-dotenv==1.0.1", ".env file loader", "utils", True),
    ("click", "click==8.1.7", "CLI framework", "utils", False),
    ("colorama", "colorama==0.4.6", "Cross-platform colored output", "utils", False),
    ("psutil", "psutil==5.9.8", "System/process utilities", "utils", True),
    ("python_dateutil", "python-dateutil==2.9.0", "Date parsing", "utils", False),
    ("pywin32", "pywin32==310", "Windows API (Windows only)", "utils", False),
    ("pyparsing", "pyparsing==3.2.3", "Parsing library", "utils", False),
    ("six", "six==1.16.0", "Python 2/3 compat", "utils", False),
    ("iniconfig", "iniconfig==2.0.0", "INI parsing (pytest)", "utils", False),
    ("pluggy", "pluggy==1.5.0", "Plugin system (pytest)", "utils", False),
    ("exceptiongroup", "exceptiongroup==1.2.2", "Backport exception groups", "utils", False),
    ("MarkupSafe", "MarkupSafe==3.0.2", "Safe HTML escaping (Jinja2 dep)", "utils", False),
    ("annotated_doc", "annotated-doc==0.0.3", "Annotated documentation (pydantic)", "utils", False),

    # ================================================================
    # LAYER 11: Optional - Web Server
    # ================================================================
    ("fastapi_utils", "fastapi-utils==0.7.0", "FastAPI utilities", "utils", False),
    ("itsdangerous", "itsdangerous==2.2.0", "Signing (Starlette sessions)", "utils", False),
    ("Jinja2", "Jinja2==3.1.4", "Templating (Starlette)", "utils", False),

    # ================================================================
    # LAYER 12: FastAPI extras
    # ================================================================
    ("multipart", "python-multipart==0.0.18", "Multipart form parsing", "fastapi", True),
]


def check_all():
    """Check each module can be imported.

    Returns:
        Tuple of (missing, present, optional_missing)
    """
    missing = []
    present = []
    optional_missing = []

    for import_name, _pip, _desc, _cat, required in ALL_MODULES:
        try:
            __import__(import_name)
            present.append((import_name, _cat, required))
        except ImportError as e:
            if required:
                missing.append((import_name, _cat, str(e)))
            else:
                optional_missing.append((import_name, _cat))

    return missing, present, optional_missing


def generate_pip_commands(missing):
    """Generate pip install commands for all missing modules."""
    seen = set()
    commands = []

    for import_name, _cat, _err in missing:
        # Find pip name
        pip_name = None
        for i, p, _d, _c, _r in ALL_MODULES:
            if i == import_name and p:
                pip_name = p.split("==")[0].split(">=")[0].split("<")[0]
                break

        if pip_name and pip_name not in seen:
            seen.add(pip_name)
            commands.append(f"pip install {pip_name}")

    return commands


def main():
    """Run comprehensive module check."""
    print("=" * 78)
    print("Comprehensive HMP Backend Module Check (E065/E066)")
    print("=" * 78)
    print()

    missing, present, optional_missing = check_all()

    # Group by category
    by_cat = {}
    for name, cat, required in present:
        by_cat.setdefault(cat, []).append((name, required, True))

    for name, cat, err in missing:
        by_cat.setdefault(cat, []).append((name, True, False))

    # Print by layer
    cat_order = [
        "core", "db", "validation", "http", "ai",
        "whisper", "hf", "auth", "docs", "utils", "fastapi",
    ]

    cat_names = {
        "core": "Layer 1: Core Web Framework",
        "db": "Layer 2: Database",
        "validation": "Layer 3: Data Validation",
        "http": "Layer 4: HTTP Client Stack",
        "ai": "Layer 5: External APIs (OpenAI)",
        "whisper": "Layer 6: Whisper Transcription",
        "hf": "Layer 7: Model Downloads (HuggingFace)",
        "auth": "Layer 8: Authentication & Security",
        "docs": "Layer 9: Document Generation",
        "utils": "Layer 10: Utilities",
        "fastapi": "Layer 11: FastAPI Extras",
    }

    for cat in cat_order:
        items = by_cat.get(cat, [])
        if not items:
            continue
        print(f"\n--- {cat_names.get(cat, cat)} ---")
        for name, required, ok in sorted(items, key=lambda x: x[0]):
            if ok:
                mark = "✓" if required else "○"
                print(f"  {mark} {name:25s}  ({'required' if required else 'optional'})")
            else:
                print(f"  ✗ {name:25s}  MISSING (required)")

    print()
    print("=" * 78)
    print(f"Total required: {len([m for m in present if m[2]])} present + {len(missing)} missing")
    print(f"Total optional: {len([m for m in present if not m[2]])} present + {len(optional_missing)} missing")
    print("=" * 78)

    if missing:
        print()
        print("[FAIL] Required modules missing!")
        print()
        print("FIX: Run these pip install commands:")
        for cmd in generate_pip_commands(missing):
            print(f"  {cmd}")
        sys.exit(1)
    else:
        print()
        print("[OK] All required modules importable")
        if optional_missing:
            print(f"  ({len(optional_missing)} optional modules missing - non-critical)")
        sys.exit(0)


if __name__ == "__main__":
    main()
