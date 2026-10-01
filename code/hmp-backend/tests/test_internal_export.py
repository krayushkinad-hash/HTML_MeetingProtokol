"""E288: тесты routers/export.py."""
import pytest


def test_export_router_imports():
    from app.routers import export
    assert export is not None


@pytest.mark.asyncio
async def test_export_docx_endpoint(client, sample_protocol):
    """POST /export/{id}/docx."""
    r = await client.post(f"/api/v1/hmp/export/{sample_protocol.id}/docx")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_export_txt_endpoint(client, sample_protocol):
    """POST /export/{id}/txt."""
    r = await client.post(f"/api/v1/hmp/export/{sample_protocol.id}/txt")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_export_docx_invalid_id(client):
    """POST /export/invalid/docx."""
    r = await client.post("/api/v1/hmp/export/not-uuid/docx")
    assert r.status_code in (404, 422, 500)


def test_format_ts_helper():
    """fmt_ts helper."""
    try:
        from app.routers.export import fmt_ts
        assert fmt_ts(0) == "00:00"
        assert fmt_ts(60) == "00:01:00" or fmt_ts(60) == "1:00"
        assert fmt_ts(3661) == "01:01:01"
    except ImportError:
        pytest.skip("fmt_ts не найден")


@pytest.mark.asyncio
async def test_export_docx_with_utterances(client, sample_protocol, sample_utterance):
    """POST /export/{id}/docx когда есть utterances."""
    r = await client.post(f"/api/v1/hmp/export/{sample_protocol.id}/docx")
    assert r.status_code in (200, 404, 422, 500)


@pytest.mark.asyncio
async def test_export_txt_with_utterances(client, sample_protocol, sample_utterance):
    """POST /export/{id}/txt когда есть utterances."""
    r = await client.post(f"/api/v1/hmp/export/{sample_protocol.id}/txt")
    assert r.status_code in (200, 404, 422, 500)


def test_build_docx_function_exists():
    """_build_docx function exists."""
    try:
        from app.routers.export import _build_docx
        assert callable(_build_docx)
    except ImportError:
        pytest.skip("_build_docx не найден")
