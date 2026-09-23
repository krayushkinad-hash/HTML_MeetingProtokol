"""
E254: добавление полей remote Whisper в user_setting.
Использует asyncpg напрямую (он точно есть в venv, т.к. SQLAlchemy его использует).

Запуск: python scripts/migrations/2026_09_23_add_remote_whisper_fields.py

Каждый ALTER — ОТДЕЛЬНЫМ соединением, чтобы избежать "closed transaction".
"""
import asyncio
import os
import sys

# Загружаем .env
env_file = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
if os.path.exists(env_file):
    for line in open(env_file, encoding="utf-8"):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

HOST = os.environ.get("POSTGRES_HOST", "127.0.0.1")
PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
USER = os.environ.get("POSTGRES_USER", "hmp")
PASSWORD = os.environ.get("POSTGRES_PASSWORD", "hmp_password")
DB = os.environ.get("POSTGRES_DB", "html_mp")

import asyncpg


STATEMENTS = [
    ('ALTER TABLE user_setting ADD COLUMN IF NOT EXISTS whisper_remote_enabled BOOLEAN NOT NULL DEFAULT false',
     'whisper_remote_enabled'),
    ('ALTER TABLE user_setting ADD COLUMN IF NOT EXISTS whisper_remote_url VARCHAR(255)',
     'whisper_remote_url'),
    ("ALTER TABLE user_setting ADD COLUMN IF NOT EXISTS whisper_remote_path VARCHAR(100) DEFAULT '/transcribe'",
     'whisper_remote_path'),
]


async def main():
    print('=' * 60)
    print('E254: Add remote Whisper fields to user_setting')
    print('=' * 60)
    print(f'DSN: postgresql://{USER}:***@{HOST}:{PORT}/{DB}')

    # Отдельное соединение на каждый ALTER
    for sql_text, name in STATEMENTS:
        try:
            conn = await asyncpg.connect(
                host=HOST, port=PORT, user=USER,
                password=PASSWORD, database=DB,
            )
            try:
                await conn.execute(sql_text)
                print(f'[OK]   added column {name!r}')
            finally:
                await conn.close()
        except asyncpg.DuplicateColumnError:
            print(f'[SKIP] column {name!r} already exists')
        except Exception as e:
            err = str(e).split('\n')[0][:100]
            print(f'[ERR]  column {name!r}: {err}')
            sys.exit(1)

    # Verification
    print()
    print('Verification:')
    conn = await asyncpg.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD, database=DB,
    )
    try:
        rows = await conn.fetch("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'user_setting'
              AND column_name LIKE 'whisper_remote%'
            ORDER BY column_name
        """)
        if not rows:
            print('  ❌ No whisper_remote_* columns found!')
            sys.exit(1)
        for row in rows:
            col, typ, nullable, default = row['column_name'], row['data_type'], row['is_nullable'], row['column_default']
            null_str = 'NULL' if nullable == 'YES' else 'NOT NULL'
            def_str = f' DEFAULT {default}' if default else ''
            print(f'  ✓ {col:25s} {typ:20s} {null_str}{def_str}')
    finally:
        await conn.close()

    print()
    print('[DONE] E254 migration applied successfully')


if __name__ == '__main__':
    asyncio.run(main())
