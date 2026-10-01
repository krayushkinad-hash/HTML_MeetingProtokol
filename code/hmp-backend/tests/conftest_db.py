"""PostgreSQL helpers for integration tests.

This module provides opt-in helpers for tests that REQUIRE a real PostgreSQL
database. By default these tests SKIP if no PostgreSQL is reachable — so the
default `pytest` run on developer machines still works.

Usage:

    from tests.conftest_db import postgres_required, get_test_db_url

    @pytest.mark.integration
    async def test_real_postgres(postgres_required):
        # ... uses real DB
        ...

To create the test DB once on a machine:

    bash scripts/init_test_db.sh
"""
from __future__ import annotations

import asyncio
import os
import socket
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_TEST_DB_HOST = os.environ.get("HMP_TEST_DB_HOST", "localhost")
DEFAULT_TEST_DB_PORT = int(os.environ.get("HMP_TEST_DB_PORT", "5432"))
DEFAULT_TEST_DB_USER = os.environ.get("HMP_TEST_DB_USER", "hmp")
DEFAULT_TEST_DB_PASSWORD = os.environ.get("HMP_TEST_DB_PASSWORD", "hmp_password")
DEFAULT_TEST_DB_NAME = os.environ.get("HMP_TEST_DB_NAME", "html_mp_test")


def get_test_db_url(
    host: str = DEFAULT_TEST_DB_HOST,
    port: int = DEFAULT_TEST_DB_PORT,
    user: str = DEFAULT_TEST_DB_USER,
    password: str = DEFAULT_TEST_DB_PASSWORD,
    database: str = DEFAULT_TEST_DB_NAME,
) -> str:
    """Return the asyncpg URL for the test database.

    Default: postgresql+asyncpg://hmp:hmp_password@localhost:5432/html_mp_test
    """
    return (
        f"postgresql+asyncpg://{user}:{password}"
        f"@{host}:{port}/{database}"
    )


# ---------------------------------------------------------------------------
# Reachability probe (cheap — TCP connect, no auth)
# ---------------------------------------------------------------------------
def _can_connect(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if a TCP connection to (host, port) succeeds.

    This is intentionally cheap — full auth + SELECT 1 happens in the
    `postgres_required` fixture itself.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def postgres_required() -> str:
    """Skip the test unless PostgreSQL is reachable.

    Returns the test DB URL on success; raises pytest.skip() otherwise.

    Mark every test that uses this with @pytest.mark.integration so the
    `pytest -m "not integration"` shorthand works.
    """
    url = get_test_db_url()
    host = DEFAULT_TEST_DB_HOST
    port = DEFAULT_TEST_DB_PORT

    if not _can_connect(host, port):
        pytest.skip(f"PostgreSQL not reachable at {host}:{port}")

    # Try a real auth'd round-trip to make sure credentials work too.
    try:
        import asyncpg  # local import — keep optional dep lazy

        async def _probe():
            conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
            await conn.execute("SELECT 1")
            await conn.close()

        asyncio.run(_probe())
    except ImportError:
        pytest.skip("asyncpg not installed — cannot verify PostgreSQL auth")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL probe failed: {exc}")

    return url


@pytest.fixture
def test_db_url() -> str:
    """Just return the test DB URL without any connectivity check.

    Useful for tests that need the URL string but do their own connection
    management (e.g. unit tests for URL parsing).
    """
    return get_test_db_url()
