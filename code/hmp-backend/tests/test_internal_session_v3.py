"""E294 v3: Additional targeted branch coverage for app/db/session.py.

Focuses on column-type SQL builder branches, NOT NULL, DEFAULT quoting,
ALTER TABLE error rollback, audio_file source.* migration, stuck transcription
with results, auto_migration_warning at table level, and reset_db full path.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

import app.db.session as session_module
from app.db.session import _safe_url


# ============================================================================
# Helpers
# ============================================================================

class _FakeConn:
    """Records all executed SQL; configurable column existence."""
    def __init__(self, *, column_exists=False, alter_raises=False):
        self.executed = []
        self.column_exists = column_exists
        self.alter_raises = alter_raises
        self.commit_calls = 0
        self.rollback_calls = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append(sql)
        if "information_schema.columns" in sql:
            return MagicMock(first=lambda: (1,) if self.column_exists else None)
        if "ALTER TABLE" in sql and self.alter_raises:
            raise RuntimeError("DDL forbidden")
        return MagicMock()

    async def run_sync(self, *a, **k):
        return None

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        self.rollback_calls += 1


class _FakeBeginCM:
    def __init__(self, conn):
        self._conn = conn
    async def __aenter__(self):
        return self._conn
    async def __aexit__(self, *a):
        return False


def _make_engine(conn):
    engine = MagicMock()
    engine.begin = MagicMock(return_value=_FakeBeginCM(conn))
    engine.dispose = AsyncMock()
    return engine


def _make_sessionmaker(session):
    sm = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    sm.return_value = ctx
    return sm


def _patch_postgres(monkeypatch):
    from app.core.config import settings as _s
    monkeypatch.setattr(_s, "database_url", "postgresql+asyncpg://u:p@h/d", raising=False)
    monkeypatch.setattr(_s, "reset_db", False, raising=False)


def _patch_inspect_with(monkeypatch, fake_columns):
    """Patch sqlalchemy.inspect to return a fake mapper with given columns."""
    import sqlalchemy
    class _FakeMapper:
        def __init__(self, cols):
            self.columns = cols
    monkeypatch.setattr(sqlalchemy, "inspect",
                        lambda _model: _FakeMapper(fake_columns))


# ============================================================================
# 1. Column-type branches — Integer / BigInteger / Float / Text
# ============================================================================

class TestColumnTypeIntegerBigIntFloatText:
    @pytest.mark.asyncio
    async def test_integer_column_type(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        class C:
            key = "n_col"
            type = MagicMock(); type.configure_mock(**{"__class__.__name__": "Integer"})
            type.length = None
            nullable = True
        # Use a simpler approach — set __class__.__name__ explicitly
        IntegerLike = type("Integer", (), {})
        c = MagicMock(); c.key = "n_col"; c.type = IntegerLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        alter = [s for s in conn.executed if "ALTER TABLE" in s]
        assert any("INTEGER" in s for s in alter)

    @pytest.mark.asyncio
    async def test_biginteger_column_type(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        BigIntLike = type("BigInteger", (), {})
        c = MagicMock(); c.key = "big_col"; c.type = BigIntLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        alter = [s for s in conn.executed if "ALTER TABLE" in s]
        assert any("BIGINT" in s for s in alter)

    @pytest.mark.asyncio
    async def test_float_column_type(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        FloatLike = type("Float", (), {})
        c = MagicMock(); c.key = "f_col"; c.type = FloatLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        alter = [s for s in conn.executed if "ALTER TABLE" in s]
        assert any("DOUBLE PRECISION" in s for s in alter)

    @pytest.mark.asyncio
    async def test_text_column_type(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        TextLike = type("Text", (), {})
        c = MagicMock(); c.key = "t_col"; c.type = TextLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        alter = [s for s in conn.executed if "ALTER TABLE" in s]
        assert any("TEXT" in s for s in alter)


# ============================================================================
# 2. Boolean / DateTime / Date / UUID / unknown-fallback branches
# ============================================================================

class TestColumnTypeBoolDateUuidFallback:
    @pytest.mark.asyncio
    async def test_boolean_column_type(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        BoolLike = type("Boolean", (), {})
        c = MagicMock(); c.key = "b_col"; c.type = BoolLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        assert any("BOOLEAN" in s for s in conn.executed if "ALTER TABLE" in s)

    @pytest.mark.asyncio
    async def test_datetime_column_type(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        DTLike = type("DateTime", (), {})
        c = MagicMock(); c.key = "dt_col"; c.type = DTLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        assert any("TIMESTAMP WITH TIME ZONE" in s for s in conn.executed if "ALTER TABLE" in s)

    @pytest.mark.asyncio
    async def test_date_column_type(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        DateLike = type("Date", (), {})
        c = MagicMock(); c.key = "d_col"; c.type = DateLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        assert any('"DATE"' in s or " DATE" in s for s in conn.executed if "ALTER TABLE" in s)

    @pytest.mark.asyncio
    async def test_uuid_column_type(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        UUIDLike = type("UUID", (), {})
        c = MagicMock(); c.key = "u_col"; c.type = UUIDLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        assert any("UUID" in s for s in conn.executed if "ALTER TABLE" in s)

    @pytest.mark.asyncio
    async def test_unknown_type_falls_back_to_text(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        WeirdLike = type("WeirdProprietary", (), {})
        c = MagicMock(); c.key = "w_col"; c.type = WeirdLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        alter = [s for s in conn.executed if "ALTER TABLE" in s]
        assert any("TEXT" in s for s in alter)


# ============================================================================
# 3. NOT NULL + DEFAULT quoting branches
# ============================================================================

class TestColumnNotNullAndDefault:
    @pytest.mark.asyncio
    async def test_not_null_branch(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        IntLike = type("Integer", (), {})
        c = MagicMock(); c.key = "req_col"; c.type = IntLike(); c.nullable = False
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        alter = [s for s in conn.executed if "ALTER TABLE" in s]
        assert any("NOT NULL" in s for s in alter)

    @pytest.mark.asyncio
    async def test_default_unquoted_keyword(self, monkeypatch):
        """DEFAULT current_timestamp (no quotes needed — it's a keyword)."""
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        IntLike = type("Integer", (), {})
        c = MagicMock(); c.key = "ts_col"; c.type = IntLike(); c.nullable = True
        c.type.length = None
        sd = MagicMock()
        sd.arg = "current_timestamp"
        c.server_default = sd
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        alter = [s for s in conn.executed if "ALTER TABLE" in s]
        assert any("DEFAULT current_timestamp" in s for s in alter)

    @pytest.mark.asyncio
    async def test_default_literal_string_gets_quoted(self, monkeypatch):
        """A plain string DEFAULT must be wrapped in single quotes."""
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        StrLike = type("String", (), {})
        c = MagicMock(); c.key = "d_col"; c.type = StrLike(); c.nullable = True
        c.type.length = 32
        sd = MagicMock(); sd.arg = "default-value"
        c.server_default = sd
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        alter = [s for s in conn.executed if "ALTER TABLE" in s]
        assert any("DEFAULT 'default-value'" in s for s in alter)

    @pytest.mark.asyncio
    async def test_default_string_with_apostrophe_escaped(self, monkeypatch):
        """Single quotes inside DEFAULT literal must be doubled."""
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        StrLike = type("String", (), {})
        c = MagicMock(); c.key = "q_col"; c.type = StrLike(); c.nullable = True
        c.type.length = 64
        sd = MagicMock(); sd.arg = "O'Brien"
        c.server_default = sd
        _patch_inspect_with(monkeypatch, [c])

        await session_module.init_db()
        alter = [s for s in conn.executed if "ALTER TABLE" in s]
        assert any("DEFAULT 'O''Brien'" in s for s in alter)


# ============================================================================
# 4. ALTER TABLE failure → per-column rollback
# ============================================================================

class TestAlterTablePerColumnRollback:
    @pytest.mark.asyncio
    async def test_alter_failure_triggers_rollback(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=False, alter_raises=True)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        # Provide at least one model whose columns will be inspected and trigger ALTER
        IntLike = type("Integer", (), {})
        c = MagicMock(); c.key = "x"; c.type = IntLike(); c.nullable = True
        c.type.length = None
        _patch_inspect_with(monkeypatch, [c])

        # Must NOT raise — error caught and rolled back per column
        await session_module.init_db()
        # At least one rollback call from column_add_failed branch
        assert conn.rollback_calls >= 1


# ============================================================================
# 5. audio_file migration — source.* pattern (US-070)
# ============================================================================

class TestAudioFileSourcePatternMigration:
    @pytest.mark.asyncio
    async def test_source_pattern_renames_to_sibling(self, monkeypatch, tmp_path):
        _patch_postgres(monkeypatch)
        # Connection that says columns exist so we skip ALTER
        conn = _FakeConn(column_exists=True)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))

        # Set up a temp dir with source.mp4 + one sibling real file
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        source = audio_dir / "source.mp4"
        source.write_bytes(b"\x00")
        real = audio_dir / "meeting_2026.mp3"
        real.write_bytes(b"\x00")

        # Build a fake AudioFile ORM object
        af = MagicMock()
        af.file_path = str(source)

        # Two AsyncSessionLocal calls:
        # 1) SELECT count(*) → 1 (skip insert)
        # 2) SELECT AudioFile → return [af]
        sess1 = MagicMock()
        sess1.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 1))
        sess2 = MagicMock()
        sess2.execute = AsyncMock(return_value=MagicMock(
            scalars=lambda: MagicMock(all=lambda: [af])
        ))
        sess2.commit = AsyncMock()

        sessions = [sess1, sess2]
        sm = MagicMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(side_effect=lambda: sessions.pop(0))
        ctx.__aexit__ = AsyncMock(return_value=False)
        sm.return_value = ctx
        monkeypatch.setattr(session_module, "AsyncSessionLocal", sm)

        await session_module.init_db()

        # file_path must now be rewritten to the sibling real file
        assert af.file_path == str(real)
        # commit() was called because migrated > 0
        sess2.commit.assert_awaited()


# ============================================================================
# 6. auto_migration_warning at table level (line 261)
# ============================================================================

class TestAutoMigrationWarning:
    @pytest.mark.asyncio
    async def test_table_inspection_raises_continues(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=True)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))
        monkeypatch.setattr(session_module, "AsyncSessionLocal", _make_sessionmaker(MagicMock()))

        # Make sqlalchemy.inspect raise so the per-table try/except triggers
        import sqlalchemy
        def _raising_inspect(_model):
            raise RuntimeError("mapper error")
        monkeypatch.setattr(sqlalchemy, "inspect", _raising_inspect)

        # Must NOT raise — outer try/except logs warning + rolls back
        await session_module.init_db()
        # rollback was called by the outer except
        assert conn.rollback_calls >= 1


# ============================================================================
# 7. stuck transcription reset — finds IDs
# ============================================================================

class TestStuckTranscriptionFound:
    @pytest.mark.asyncio
    async def test_stuck_transcriptions_found_commits(self, monkeypatch):
        _patch_postgres(monkeypatch)
        conn = _FakeConn(column_exists=True)
        monkeypatch.setattr(session_module, "engine", _make_engine(conn))

        # init_db makes 3 AsyncSessionLocal() calls:
        #   1) SELECT count(*) FROM user_setting
        #   2) SELECT AudioFile (migration)
        #   3) UPDATE Protocol returning IDs
        sess_count = MagicMock()
        sess_count.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 1))

        sess_audio = MagicMock()
        sess_audio.execute = AsyncMock(return_value=MagicMock(
            scalars=lambda: MagicMock(all=lambda: [])
        ))

        sess_stuck = MagicMock()
        upd_result = MagicMock()
        upd_result.fetchall = MagicMock(return_value=[(1,), (2,)])
        sess_stuck.execute = AsyncMock(return_value=upd_result)
        sess_stuck.commit = AsyncMock()

        sessions = [sess_count, sess_audio, sess_stuck]
        sm = MagicMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(side_effect=lambda: sessions.pop(0))
        ctx.__aexit__ = AsyncMock(return_value=False)
        sm.return_value = ctx
        monkeypatch.setattr(session_module, "AsyncSessionLocal", sm)

        await session_module.init_db()
        # commit was called because stuck_ids was truthy
        sess_stuck.commit.assert_awaited()


# ============================================================================
# 8. _safe_url additional corner cases
# ============================================================================

class TestSafeUrlExtra:
    def test_safe_url_empty_after_at(self):
        """URL with empty part after @ — returns the trailing part."""
        assert _safe_url("user:pwd@") == ""

    def test_safe_url_only_at(self):
        assert _safe_url("@") == ""

    def test_safe_url_path_only_no_creds(self):
        """URL with no credentials, with double slash."""
        assert _safe_url("postgresql://dbname") == "dbname"