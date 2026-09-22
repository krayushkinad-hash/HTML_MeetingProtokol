"""Fix PostgreSQL password by testing common passwords and updating .env."""
import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path


def get_password_from_container():
    """Try to get POSTGRES_PASSWORD from docker container."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "hmp-postgres", "--format", "{{range .Config.Env}}{{.}}{{println}}{{end}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if line.startswith("POSTGRES_PASSWORD="):
                    pwd = line.replace("POSTGRES_PASSWORD=", "").strip()
                    if pwd:
                        print(f"  Found container password: {pwd}")
                        return pwd
    except Exception as e:
        print(f"  Could not read container env: {e}")
    return None


async def test_postgres_password(pwd):
    """Test specific password for hmp PostgreSQL user."""
    try:
        conn = await asyncpg.connect(
            host="localhost",
            port=5432,
            user="hmp",
            password=pwd,
            database="html_mp",
            timeout=5,
        )
        await conn.close()
        return True
    except Exception as e:
        print(f"  Failed: {type(e).__name__}")
        return False


async def test_all_passwords():
    """Try all common passwords."""
    passwords = [
        "hmp_password",
        "hmp",
        "postgres",
        "password",
        "admin",
        "changeme",
        "",
    ]
    # Add container password if available
    container_pwd = get_password_from_container()
    if container_pwd and container_pwd not in passwords:
        passwords.insert(0, container_pwd)

    for pwd in passwords:
        if await test_postgres_password(pwd):
            print(f"OK: PostgreSQL password is: {pwd!r}")
            return pwd
    print("FAIL: PostgreSQL not accessible with any common password")
    return None


async def main():
    # Get project root from command line or env
    project_root = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PROJECT_DIR")
    if not project_root:
        print("ERROR: PROJECT_DIR not set")
        return 1

    print(f"Project: {project_root}")

    # Test password
    pwd = await test_all_passwords()
    if not pwd:
        return 1

    # Update .env
    env_file = Path(project_root) / ".env"
    env_example = Path(project_root) / ".env.example"

    # Create .env from .env.example if doesn't exist
    if not env_file.exists():
        if env_example.exists():
            import shutil
            shutil.copy(env_example, env_file)
            print(f"Created .env from .env.example")
        else:
            # Create minimal .env
            env_file.write_text(
                f"""DATABASE_URL=postgresql+asyncpg://hmp:{pwd}@localhost:5432/html_mp
SECRET_KEY=change-me-in-production
ENCRYPTION_MASTER_KEY={os.urandom(32).hex()}
HOST=127.0.0.1
PORT=8000
ENV=development
""",
                encoding="utf-8",
            )
            print(f"Created minimal .env")
            return 0

    try:
        content = env_file.read_text(encoding="utf-8")
        # Replace entire DATABASE_URL line with correct one
        new_url = f"DATABASE_URL=postgresql+asyncpg://hmp:{pwd}@localhost:5432/html_mp"
        # Match any DATABASE_URL=postgresql+asyncpg://... line
        new_content = re.sub(
            r"DATABASE_URL=postgresql\+asyncpg://[^\s]+",
            new_url,
            content,
        )
        # Also try replace hmp_password
        new_content = new_content.replace("hmp_password", pwd)
        if new_content != content:
            env_file.write_text(new_content, encoding="utf-8")
            print(f"Updated .env with password: {pwd}")
        else:
            print(f"No change needed (already using {pwd})")
    except Exception as e:
        print(f"WARNING: Could not update .env: {e}")
        return 1

    return 0


if __name__ == "__main__":
    try:
        import asyncpg
    except ImportError:
        print("ERROR: asyncpg not installed. Run install-deps-and-run.bat first.")
        sys.exit(1)

    sys.exit(asyncio.run(main()))
