"""Verify api/client.js is not corrupted by patch (E005 check).

Checks the file structure for E005 (patch() inserted object-literal inside request()).

Run: python scripts/verify_client_js.py
"""
import re
import subprocess
import sys
from pathlib import Path

CLIENT_FILE = Path(__file__).parent.parent / "src" / "js" / "api" / "client.js"


def check_syntax():
    result = subprocess.run(
        ["node", "--check", str(CLIENT_FILE)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("X Syntax error:")
        print(result.stderr)
        return False
    print("OK Syntax OK")
    return True


def check_fetch_call_exists():
    """Check that fetch() is called inside request() function body."""
    text = CLIENT_FILE.read_text(encoding="utf-8")
    # Find request() function
    m = re.search(r"async function request\(([^)]*)\)\s*\{", text)
    if not m:
        print("X request() not found")
        return False
    func_start = m.end()
    # Find closing brace by tracking depth
    depth = 1
    pos = func_start
    while depth > 0 and pos < len(text):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
        pos += 1
    func_body = text[func_start:pos]
    if "await fetch(" not in func_body:
        print("X fetch() not in request() — broken!")
        return False
    print("OK fetch() in request()")
    return True


def check_api_methods_outside_request():
    """Verify api methods are OUTSIDE request() function (not inside)."""
    text = CLIENT_FILE.read_text(encoding="utf-8")
    # Find request() bounds
    m = re.search(r"async function request\(([^)]*)\)\s*\{", text)
    if not m:
        return False
    func_start = m.end()
    depth = 1
    pos = func_start
    while depth > 0 and pos < len(text):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
        pos += 1
    func_end = pos

    # Find api object block
    api_block_match = re.search(r"export const api\s*=\s*\{", text)
    if not api_block_match:
        print("X api object not found")
        return False
    api_start = api_block_match.end()

    # Count api method names
    api_methods = re.findall(r"^\s*(\w+):\s*\(.*?\)", text[api_start:], re.MULTILINE)

    # Check that api block comes AFTER request() function
    if api_start < func_end:
        print(f"X api object starts INSIDE request() (E005!)")
        print(f"   request() ends at {func_end}, api starts at {api_start}")
        return False

    print(f"OK api block is after request() ({len(api_methods)} methods found)")
    return True


def check_api_base():
    text = CLIENT_FILE.read_text(encoding="utf-8")
    m = re.search(r"const API_BASE\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not m:
        print("X API_BASE not defined")
        return False
    url = m.group(1)
    if not url.startswith("http"):
        print(f"X API_BASE invalid: {url}")
        return False
    print(f"OK API_BASE = {url}")
    return True


def main():
    print("=" * 70)
    print("Verify api/client.js structure (E005 prevention)")
    print("=" * 70)

    results = [
        check_syntax(),
        check_fetch_call_exists(),
        check_api_methods_outside_request(),
        check_api_base(),
    ]

    print()
    if all(results):
        print("ALL CHECKS PASSED")
        sys.exit(0)
    else:
        print("!!! CHECKS FAILED — file may be corrupted !!!")
        print("Probably E005 — patch() inserted code inside wrong place.")
        sys.exit(1)


if __name__ == "__main__":
    main()
