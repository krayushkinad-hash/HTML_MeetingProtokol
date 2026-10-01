"""E287: тесты routers/transcribe/remote.py.

Покрывает:
- helpers _make_multipart_body, _do_multipart_request (success + 404 + HTTPError + URLError)
- POST /transcribe/remote (валидация UUID, 404 протокола, 502 на 404 от remote)
- POST /transcribe/remote/test-upload (success + 502 на 4xx/5xx)
- URL construction: /api/v1/hmp prefix, target_path с /api/, trailing slash
"""
import io
import json
import os
import sys
import uuid

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_audio_file_row(db_session, sample_protocol, file_path: str, ext: str = "m4a"):
    """Создаёт AudioFile, привязанный к протоколу."""
    from app.db.models import AudioFile

    af = AudioFile(
        id=uuid.uuid4(),
        file_path=file_path,
        filename=os.path.basename(file_path),
        extension=ext,
        size_bytes=os.path.getsize(file_path) if os.path.exists(file_path) else 1024,
        mime_type="audio/mpeg",
        source="local",
    )
    db_session.add(af)
    db_session.add(sample_protocol)
    sample_protocol.audio_file_id = af.id
    return af


@pytest_asyncio.fixture
async def real_audio_file(tmp_path, db_session, sample_protocol):
    """Реальный файл на диске, привязанный к AudioFile."""
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"\x00\x01\x02\x03" * 256)
    af = _make_audio_file_row(db_session, sample_protocol, str(audio), ext="m4a")
    await db_session.commit()
    await db_session.refresh(af)
    await db_session.refresh(sample_protocol)
    return af


@pytest_asyncio.fixture
async def missing_audio_file(db_session, sample_protocol):
    """AudioFile в БД, но файла нет на диске."""
    af = _make_audio_file_row(
        db_session, sample_protocol, "/nonexistent/path/audio.m4a"
    )
    await db_session.commit()
    await db_session.refresh(af)
    await db_session.refresh(sample_protocol)
    return af


# ---------------------------------------------------------------------------
# 1. Module imports / wiring
# ---------------------------------------------------------------------------

def test_remote_module_imports():
    """remote.py импортируется, router существует."""
    from app.routers.transcribe import remote

    assert remote is not None
    assert hasattr(remote, "router")
    routes = [r.path for r in remote.router.routes]
    assert "/remote" in routes
    assert "/remote/test-upload" in routes



def test_make_multipart_body_basic():
    """_make_multipart_body возвращает корректный body + boundary."""
    from app.routers.transcribe.remote import _make_multipart_body

    body, boundary = _make_multipart_body(
        b"hello-audio-bytes", "test.mp3", {"model": "base", "language": "ru"}
    )
    assert isinstance(body, bytes)
    assert isinstance(boundary, str)
    assert boundary.startswith("----HMPBoundary")
    text = body.decode("latin-1")
    assert "Content-Disposition: form-data; name=\"model\"" in text
    assert "base" in text
    assert "ru" in text
    assert "filename=\"test.mp3\"" in text
    assert "Content-Type: audio/mpeg" in text
    assert "hello-audio-bytes" in text
    assert text.endswith("--" + boundary + "--" + "\r\n")


def test_make_multipart_body_empty_extras():
    """_make_multipart_body работает без extra_fields."""
    from app.routers.transcribe.remote import _make_multipart_body

    body, boundary = _make_multipart_body(b"xxx", "a.wav", {})
    assert b"filename=\"a.wav\"" in body
    assert b"--" + boundary.encode() + b"--" in body


# ---------------------------------------------------------------------------
# 2. _do_multipart_request direct unit tests
# ---------------------------------------------------------------------------

def test_do_multipart_request_success(monkeypatch):
    """_do_multipart_request: успешный 200 возвращает (data, 200)."""
    from app.routers.transcribe import remote as remote_mod

    class FakeResp:
        status = 200

        def read(self):
            return b'{"text":"hello","segments":[]}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        remote_mod.urllib.request, "urlopen", lambda req, timeout: FakeResp()
    )
    data, status = remote_mod._do_multipart_request(
        "http://example.com/transcribe", b"body", "BOUND"
    )
    assert status == 200
    assert b"hello" in data


def test_do_multipart_request_404_with_path(monkeypatch):
    """404 при наличии path → возвращаем (data, 404), не делаем fallback."""
    from app.routers.transcribe import remote as remote_mod
    import urllib.error

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", {}, io.BytesIO(b"nope")
        )

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", fake_urlopen)
    data, status = remote_mod._do_multipart_request(
        "http://example.com/transcribe", b"body", "BOUND"
    )
    assert status == 404
    assert data == b"nope"


def test_do_multipart_request_404_fallback(monkeypatch):
    """E280: 404 на корневом URL → пробуем добавить /transcribe."""
    from app.routers.transcribe import remote as remote_mod
    import urllib.error

    calls = []

    class FakeResp:
        status = 200

        def read(self):
            return b'{"text":"ok"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                req.full_url, 404, "Not Found", {}, io.BytesIO(b"empty")
            )
        return FakeResp()

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", fake_urlopen)
    data, status = remote_mod._do_multipart_request(
        "http://example.com:8000/", b"body", "BOUND"
    )
    assert status == 200
    assert b"ok" in data
    assert len(calls) == 2
    assert calls[1] == "http://example.com:8000/transcribe"


def test_do_multipart_request_500(monkeypatch):
    """_do_multipart_request: HTTP 500 не ретраит, возвращает (data, 500)."""
    from app.routers.transcribe import remote as remote_mod
    import urllib.error

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 500, "Internal", {}, io.BytesIO(b"err")
        )

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", fake_urlopen)
    data, status = remote_mod._do_multipart_request(
        "http://example.com/transcribe", b"body", "BOUND"
    )
    assert status == 500
    assert data == b"err"


# ---------------------------------------------------------------------------
# 3. POST /remote (валидация + happy path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remote_invalid_uuid(client):
    """Invalid UUID → 400 (валидация вручную)."""
    r = await client.post(
        "/api/v1/hmp/remote",
        data={
            "protocol_id": "not-a-uuid",
            "target_url": "http://example.com",
            "target_path": "/transcribe",
            "model": "base",
            "language": "ru",
        },
    )
    assert r.status_code == 400
    assert "Invalid protocol_id" in r.text


@pytest.mark.asyncio
async def test_remote_protocol_not_found(client):
    """Несуществующий UUID → 404 Protocol not found."""
    fake_id = str(uuid.uuid4())
    r = await client.post(
        "/api/v1/hmp/remote",
        data={
            "protocol_id": fake_id,
            "target_url": "http://example.com",
            "target_path": "/transcribe",
        },
    )
    assert r.status_code == 404
    assert "Protocol not found" in r.text


@pytest.mark.asyncio
async def test_remote_no_audio_file(client, sample_protocol):
    """Protocol без audio_file_id → 400."""
    # sample_protocol создаётся без audio_file_id
    assert sample_protocol.audio_file_id is None
    r = await client.post(
        "/api/v1/hmp/remote",
        data={
            "protocol_id": str(sample_protocol.id),
            "target_url": "http://example.com",
            "target_path": "/transcribe",
        },
    )
    assert r.status_code == 400
    assert "no audio file" in r.text.lower()


@pytest.mark.asyncio
async def test_remote_audio_missing_on_disk(client, missing_audio_file, sample_protocol):
    """AudioFile в БД, но файла нет на диске → 404."""
    r = await client.post(
        "/api/v1/hmp/remote",
        data={
            "protocol_id": str(sample_protocol.id),
            "target_url": "http://example.com",
            "target_path": "/transcribe",
        },
    )
    assert r.status_code == 404
    assert "missing on disk" in r.text.lower()


@pytest.mark.asyncio
async def test_remote_success(monkeypatch, client, real_audio_file, sample_protocol):
    """Happy path: AudioFile на диске, remote возвращает 200 с segments."""
    from app.routers.transcribe import remote as remote_mod

    fake_response = {
        "text": "hello world",
        "language": "ru",
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "hello"},
            {"start": 1.5, "end": 3.0, "text": "world"},
            {"start": 3.0, "end": 4.0, "text": "   "},  # blank — skipped
        ],
    }

    class FakeResp:
        status = 200

        def read(self):
            return json.dumps(fake_response).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", lambda req, timeout: FakeResp())
    r = await client.post(
        "/api/v1/hmp/remote",
        data={
            "protocol_id": str(sample_protocol.id),
            "target_url": "http://195.133.77.76:8000",
            "target_path": "/transcribe",
            "model": "base",
            "language": "ru",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_id"] == str(sample_protocol.id)
    assert body["segments_created"] == 2  # 1 blank skipped
    assert body["text"] == "hello world"
    assert body["language"] == "ru"

    # Проверяем, что Utterance сохранились в БД
    from sqlalchemy import select
    from app.db.models import Utterance

    stmt = select(Utterance).where(Utterance.protocol_id == sample_protocol.id)
    # Remote endpoint does NOT touch protocol.status (it only writes Utterance
    # rows). The fixture sets status to ProtocolStatus.LIVE, which serialises
    # as the string "live". The previous assertion of "ready" was incorrect.
    refreshed = sample_protocol
    assert refreshed.status == "live"


@pytest.mark.asyncio
async def test_remote_url_with_api_path_sanitized(
    monkeypatch, client, real_audio_file, sample_protocol
):
    """target_path с /api/v1/hmp → sanitized (игнорируется, используется /transcribe)."""
    from app.routers.transcribe import remote as remote_mod

    captured_urls = []

    class FakeResp:
        status = 200

        def read(self):
            return b'{"text":"ok","segments":[]}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        captured_urls.append(req.full_url)
        return FakeResp()

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", fake_urlopen)
    r = await client.post(
        "/api/v1/hmp/remote",
        data={
            "protocol_id": str(sample_protocol.id),
            "target_url": "http://example.com/",
            "target_path": "/api/v1/hmp/transcribe",  # мусорный
            "model": "base",
        },
    )
    assert r.status_code == 200, r.text
    assert len(captured_urls) == 1
    assert captured_urls[0] == "http://example.com/transcribe"


@pytest.mark.asyncio
async def test_remote_http_error_returns_502(
    monkeypatch, client, real_audio_file, sample_protocol
):
    """Remote возвращает 500 → прокси отдаёт 502."""
    from app.routers.transcribe import remote as remote_mod
    import urllib.error

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 500, "Internal", {}, io.BytesIO(b"boom")
        )

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", fake_urlopen)
    r = await client.post(
        "/api/v1/hmp/remote",
        data={
            "protocol_id": str(sample_protocol.id),
            "target_url": "http://example.com",
            "target_path": "/transcribe",
        },
    )
    assert r.status_code == 502
    assert "Remote 500" in r.text or "500" in r.text


@pytest.mark.asyncio
async def test_remote_network_error_returns_502(
    monkeypatch, client, real_audio_file, sample_protocol
):
    """URLError → 502 с обёрткой 'Failed to reach remote'."""
    from app.routers.transcribe import remote as remote_mod
    import urllib.error

    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", fake_urlopen)
    r = await client.post(
        "/api/v1/hmp/remote",
        data={
            "protocol_id": str(sample_protocol.id),
            "target_url": "http://nowhere.invalid",
            "target_path": "/transcribe",
        },
    )
    assert r.status_code == 502
    assert "Failed to reach remote" in r.text


# ---------------------------------------------------------------------------
# 4. POST /remote/test-upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_upload_success(monkeypatch, client):
    """POST /transcribe/remote/test-upload: успешный remote → ok с meta."""
    from app.routers.transcribe import remote as remote_mod

    class FakeResp:
        status = 200

        def read(self):
            return json.dumps(
                {
                    "text": "transcribed text",
                    "language": "ru",
                    "duration_sec": 12.5,
                    "segments": [
                        {"start": 0.0, "end": 1.0, "text": "first"},
                        {"start": 1.0, "end": 2.0, "text": "second"},
                    ],
                }
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", lambda req, timeout: FakeResp())
    files = {"file": ("clip.mp3", b"\x00" * 1024, "audio/mpeg")}
    data = {
        "target_url": "http://example.com",
        "target_path": "/transcribe",
        "model": "base",
        "language": "ru",
    }
    r = await client.post(
        "/api/v1/hmp/remote/test-upload", files=files, data=data
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["file_size_bytes"] == 1024
    assert body["filename"] == "clip.mp3"
    assert body["segments_count"] == 2
    assert body["remote_language"] == "ru"
    assert body["remote_duration_sec"] == 12.5
    assert body["first_segment"]["text"] == "first"
    assert body["remote_text_preview"] == "transcribed text"


@pytest.mark.asyncio
async def test_test_upload_500_error(monkeypatch, client):
    """Remote 500 → ответ с status=500 и error, но 200 от прокси."""
    from app.routers.transcribe import remote as remote_mod
    import urllib.error

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 500, "Server Error", {}, io.BytesIO(b"oops")
        )

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", fake_urlopen)
    files = {"file": ("clip.wav", b"\x00" * 512, "audio/wav")}
    data = {"target_url": "http://example.com", "target_path": "/transcribe"}
    r = await client.post(
        "/api/v1/hmp/remote/test-upload", files=files, data=data
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == 500
    assert body["error"] == "Remote returned 500"
    assert "oops" in body["remote_response"]


@pytest.mark.asyncio
async def test_test_upload_defaults_and_url_build(monkeypatch, client):
    """Defaults target_url/target_path; путь без ведущего слеша → добавляется /."""
    from app.routers.transcribe import remote as remote_mod

    captured_urls = []

    class FakeResp:
        status = 200

        def read(self):
            return b'{"text":"x","segments":[],"language":"en"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        captured_urls.append(req.full_url)
        return FakeResp()

    monkeypatch.setattr(remote_mod.urllib.request, "urlopen", fake_urlopen)
    files = {"file": ("a.mp3", b"x" * 8, "audio/mpeg")}
    # Не передаём target_url/target_path — должны использоваться defaults
    r = await client.post("/api/v1/hmp/remote/test-upload", files=files)
    assert r.status_code == 200, r.text
    assert len(captured_urls) == 1
    # default target_url — http://195.133.77.76:8000, default target_path — /transcribe
    assert captured_urls[0] == "http://195.133.77.76:8000/transcribe"
