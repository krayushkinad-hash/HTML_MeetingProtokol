"""Test all API endpoints."""
import asyncio
import sys
from pathlib import Path

import httpx


BASE_URL = "http://127.0.0.1:8000"


async def test_endpoint(client, method, path, **kwargs):
    """Test single endpoint."""
    try:
        response = await client.request(method, f"{BASE_URL}{path}", **kwargs, timeout=5)
        status = response.status_code
        # Color codes
        if status < 300:
            icon = "OK"
            color = "\033[32m"
        elif status < 500:
            icon = "???"
            color = "\033[33m"
        else:
            icon = "ERR"
            color = "\033[31m"
        reset = "\033[0m"
        print(f"  {color}{icon:3}{reset} {method:6} {path:50} {status}")
        return True
    except Exception as e:
        print(f"  ERR  {method:6} {path:50} {type(e).__name__}")
        return False


async def main():
    print("=" * 80)
    print(" API Endpoints Test")
    print("=" * 80)
    print()

    async with httpx.AsyncClient() as client:
        # Health
        print("--- Health ---")
        await test_endpoint(client, "GET", "/health")
        await test_endpoint(client, "GET", "/health/deep")

        # Protocols
        print("\n--- Protocols ---")
        await test_endpoint(client, "GET", "/api/v1/hmp/protocols")
        await test_endpoint(client, "GET", "/api/v1/hmp/protocols?limit=10")

        # Get first protocol
        try:
            r = await client.get(f"{BASE_URL}/api/v1/hmp/protocols?limit=1")
            if r.status_code == 200:
                data = r.json()
                if data:
                    pid = data[0].get("id") or data[0].get("protocol_id")
                    print(f"\n--- Protocol {pid} ---")
                    await test_endpoint(client, "GET", f"/api/v1/hmp/protocols/{pid}")
                    await test_endpoint(client, "GET", f"/api/v1/hmp/protocols/{pid}/tags")
                    await test_endpoint(client, "GET", f"/api/v1/hmp/protocols/{pid}/action-items")
                    await test_endpoint(client, "GET", f"/api/v1/hmp/protocols/{pid}/summary")
                    await test_endpoint(client, "GET", f"/api/v1/hmp/speakers?protocol_id={pid}")
                    await test_endpoint(client, "GET", f"/api/v1/hmp/utterances?protocol_id={pid}&limit=50")
                    await test_endpoint(client, "GET", "/api/v1/hmp/calendar?month=2026-09")
        except Exception as e:
            print(f"  Could not get protocols list: {e}")

        # User settings
        print("\n--- User Settings ---")
        await test_endpoint(client, "GET", "/api/v1/hmp/user-setting")

        # Dictionary
        print("\n--- Dictionary ---")
        await test_endpoint(client, "GET", "/api/v1/hmp/dictionary")

        # Search
        print("\n--- Search ---")
        await test_endpoint(client, "GET", "/api/v1/hmp/search?q=test")

    print()
    print("=" * 80)
    print(" DONE")
    print("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(1)
