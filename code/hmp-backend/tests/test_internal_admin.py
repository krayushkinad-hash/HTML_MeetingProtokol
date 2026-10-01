"""E289/E357: тесты routers/admin.py — /admin/clear-data и /admin/stats.

Цель: покрыть оба endpoint'а и их ветки:
- DELETE /admin/clear-data: пустая БД; БД с данными; очистка диска (есть/нет папка);
  reset UserSetting; сбой БД → 500.
- GET /admin/stats: пустая БД; БД с данными (все счётчики).
"""
import uuid

import pytest
from sqlalchemy import select

from app.db.models import (
    Protocol, ProtocolStatus, Speaker, Utterance, Tag, ActionItem,
    Decision, Summary, TranscriptionTask, Screenshot, AudioFile, Folder,
    ProtocolVersion, UserSetting,
)


# ---------------------------------------------------------------------------
# Helpers: local fixtures (avoid buggy conftest sample_decision/sample_action_item)
# ---------------------------------------------------------------------------
@pytest.fixture
def make_protocol(db_session):
    """Фабрика Protocol — нужна для каждого теста, чтобы не зависеть от конфликтующих фикстур."""
    from datetime import datetime, timezone

    async def _factory(title: str = "Test Protocol", status=ProtocolStatus.RECORDING):
        p = Protocol(
            id=uuid.uuid4(),
            title=title,
            status=status,
            date=datetime.now(timezone.utc).date(),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(p)
        await db_session.commit()
        return p

    return _factory


# ============================================================================
# DELETE /admin/clear-data
# ============================================================================

@pytest.mark.asyncio
async def test_clear_data_empty_db(client):
    """DELETE /admin/clear-data на пустой БД — status=cleared, counts=0."""
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cleared"
    # Все счётчики должны быть нулевыми (БД пуста до удаления)
    assert body["deleted_counts"] == {
        "utterances": 0,
        "speakers": 0,
        "tags": 0,
        "action_items": 0,
        "decisions": 0,
        "summaries": 0,
        "transcription_tasks": 0,
        "screenshots": 0,
        "audio_files": 0,
        "folders": 0,
        "protocol_versions": 0,
        "protocols": 0,
    }
    assert body["files_deleted"] == 0
    assert "message" in body


@pytest.mark.asyncio
async def test_clear_data_with_records(client, db_session, make_protocol):
    """DELETE /admin/clear-data на БД с записями — все counts > 0, после — пусто."""
    # Префилл
    p = await make_protocol("Test Protocol 1")
    spk = Speaker(id=uuid.uuid4(), protocol_id=p.id, speaker_label="SPK_A")
    db_session.add(spk)
    utt = Utterance(
        id=uuid.uuid4(),
        protocol_id=p.id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="hi",
    )
    db_session.add(utt)
    tag = Tag(id=uuid.uuid4(), protocol_id=p.id, name="t1")
    db_session.add(tag)
    ai = ActionItem(id=uuid.uuid4(), protocol_id=p.id, task="do it")
    db_session.add(ai)
    dec = Decision(id=uuid.uuid4(), protocol_id=p.id, text="decided")
    db_session.add(dec)
    await db_session.commit()

    # До: stats показывает данные
    pre = await client.get("/api/v1/hmp/admin/stats")
    assert pre.status_code == 200
    pre_body = pre.json()
    assert pre_body["protocols"] >= 1
    assert pre_body["utterances"] >= 1

    # Действие
    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cleared"
    dc = body["deleted_counts"]
    assert dc["protocols"] >= 1
    assert dc["utterances"] >= 1
    assert dc["speakers"] >= 1
    assert dc["decisions"] >= 1
    assert dc["action_items"] >= 1
    assert dc["tags"] >= 1

    # После: БД пуста (по stats)
    post = await client.get("/api/v1/hmp/admin/stats")
    assert post.status_code == 200
    post_body = post.json()
    assert post_body["protocols"] == 0
    assert post_body["utterances"] == 0
    assert post_body["screenshots"] == 0
    assert post_body["folders"] == 0


@pytest.mark.asyncio
async def test_clear_data_resets_user_setting(client, db_session):
    """После clear-data создаётся новая UserSetting (default)."""
    # Удалить существующие настройки и добавить кастомную
    res = await db_session.execute(select(UserSetting))
    for row in res.scalars().all():
        await db_session.delete(row)
    custom = UserSetting(theme="dark", whisper_model="tiny")
    db_session.add(custom)
    await db_session.commit()

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200

    # После очистки — ровно 1 UserSetting (default)
    res = await db_session.execute(select(UserSetting))
    settings = res.scalars().all()
    assert len(settings) == 1
    assert settings[0].id is not None


@pytest.mark.asyncio
async def test_clear_data_removes_protocol_dirs_from_disk(
    client, make_protocol, tmp_path, monkeypatch
):
    """При наличии папок протоколов в protocols_dir — они удаляются (files_deleted > 0)."""
    from app.core.config import get_settings

    settings = get_settings()
    # protocols_path — это @property поверх protocols_dir; патчим поле
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    # Создать две фейковые "папки протоколов" + один файл
    (tmp_path / str(uuid.uuid4())).mkdir()
    (tmp_path / str(uuid.uuid4())).mkdir()
    (tmp_path / "stray.txt").write_text("x")

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200, r.text
    body = r.json()
    # Обе подпапки и файл должны быть учтены
    assert body["files_deleted"] >= 3
    # После — папка пуста
    remaining = list(tmp_path.iterdir())
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_clear_data_handles_missing_protocols_path(
    client, tmp_path, monkeypatch
):
    """Если protocols_path не существует — files_deleted=0, без ошибок."""
    from app.core.config import get_settings

    settings = get_settings()
    nonexistent = tmp_path / "does_not_exist"
    assert not nonexistent.exists()
    monkeypatch.setattr(settings, "protocols_dir", str(nonexistent))

    r = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cleared"
    assert body["files_deleted"] == 0


@pytest.mark.asyncio
async def test_clear_data_handles_unremovable_file(
    client, make_protocol, tmp_path, monkeypatch
):
    """Если unlink файла падает — endpoint продолжает работу, файлы-ошибки просто пропускаются."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "protocols_dir", str(tmp_path))

    # Создать файл, который "нельзя удалить"
    blocked = tmp_path / "blockedadmin.txt"
    blocked.write_text("x")

    # Патчим Path.unlink, чтобы он бросил
    import pathlib as _pl
    real_unlink = _pl.Path.unlink

    def boom_unlink(self, *args, **kwargs):
        if "blockedadmin" in str(self):
            raise OSError("perm denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(_pl.Path, "unlink", boom_unlink)
    try:
        r = await client.delete("/api/v1/hmp/admin/clear-data")
    finally:
        monkeypatch.setattr(_pl.Path, "unlink", real_unlink)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cleared"
    # blocked файл не учтён, но другие могли быть — главное, что 200
    assert isinstance(body["files_deleted"], int)


@pytest.mark.asyncio
async def test_clear_data_db_failure_raises(client):
    """Если execute падает на DELETE — endpoint возвращает 500 (исключение пробрасывается)."""
    from sqlalchemy import delete as _del
    from app.db.session import get_db, AsyncSessionLocal
    from app.main import app

    class _BoomSession:
        def __init__(self, real):
            self._real = real

        async def execute(self, stmt, *args, **kwargs):
            # Падаем только на DELETE-выражениях
            if isinstance(stmt, _del):
                raise RuntimeError("simulated db failure")
            return await self._real.execute(stmt, *args, **kwargs)

        async def commit(self):
            return await self._real.commit()

        async def rollback(self):
            return await self._real.rollback()

        def add(self, obj):
            self._real.add(obj)

    async def _override_get_db():
        async with AsyncSessionLocal() as real:
            boom = _BoomSession(real)
            try:
                yield boom
                await boom.commit()
            except Exception:
                await boom.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    try:
        r = await client.delete("/api/v1/hmp/admin/clear-data")
    finally:
        app.dependency_overrides.clear()

    # Исключение попадает в middleware → 500
    assert r.status_code == 500


# ============================================================================
# GET /admin/stats
# ============================================================================

@pytest.mark.asyncio
async def test_get_stats_empty_db(client):
    """GET /admin/stats на пустой БД — все счётчики 0."""
    r = await client.get("/api/v1/hmp/admin/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "protocols": 0,
        "audio_files": 0,
        "utterances": 0,
        "screenshots": 0,
        "folders": 0,
    }


@pytest.mark.asyncio
async def test_get_stats_with_data(client, db_session, make_protocol):
    """GET /admin/stats с заполненной БД — счётчики корректные."""
    p = await make_protocol("P1")
    spk = Speaker(id=uuid.uuid4(), protocol_id=p.id, speaker_label="S1")
    db_session.add(spk)
    utt = Utterance(
        id=uuid.uuid4(),
        protocol_id=p.id,
        speaker_id=spk.id,
        start_sec=0.0,
        end_sec=1.0,
        text="x",
    )
    db_session.add(utt)
    f = Folder(id=uuid.uuid4(), name="F")
    db_session.add(f)
    s = Screenshot(
        id=uuid.uuid4(),
        protocol_id=p.id,
        timestamp_sec=1.0,
        file_path="/tmp/x.png",
    )
    db_session.add(s)
    await db_session.commit()

    r = await client.get("/api/v1/hmp/admin/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["protocols"] >= 1
    assert body["utterances"] >= 1
    assert body["screenshots"] >= 1
    assert body["folders"] >= 1
    assert body["audio_files"] == 0  # не создавали


@pytest.mark.asyncio
async def test_get_stats_after_partial_clear(client, db_session, make_protocol):
    """stats корректно работает после очистки."""
    p = await make_protocol("Tmp")
    utt = Utterance(
        id=uuid.uuid4(),
        protocol_id=p.id,
        start_sec=0.0,
        end_sec=1.0,
        text="x",
    )
    db_session.add(utt)
    await db_session.commit()

    r1 = await client.get("/api/v1/hmp/admin/stats")
    assert r1.status_code == 200
    assert r1.json()["protocols"] >= 1

    r2 = await client.delete("/api/v1/hmp/admin/clear-data")
    assert r2.status_code == 200

    r3 = await client.get("/api/v1/hmp/admin/stats")
    assert r3.status_code == 200
    assert r3.json()["protocols"] == 0
    assert r3.json()["utterances"] == 0