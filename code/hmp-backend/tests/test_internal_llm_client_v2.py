"""Comprehensive tests for app/services/llm_client.py using httpx.MockTransport.

Targets ≥60% coverage on HermesClient, GigaChatClient, OllamaClient, LLMRouter.
"""
import json
from typing import Any

import httpx
import pytest

from app.services.llm_client import (
    GigaChatClient,
    HermesClient,
    LLMRouter,
    OllamaClient,
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def make_transport(handler):
    """Build an httpx.AsyncClient wired to a MockTransport."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def hermes_ok(payload: dict[str, Any] | None = None):
    """Return a handler that responds OK to a Hermes POST."""
    body = payload or {
        "choices": [{"message": {"content": "Hermes reply"}}],
        "usage": {"total_tokens": 77},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer hermes-key"
        assert request.url.path.endswith("/chat/completions")
        body_req = json.loads(request.content)
        assert body_req["model"] == "hermes-3"
        assert body_req["messages"][-1]["role"] == "user"
        return httpx.Response(200, json=body)

    return handler


def gigachat_ok(payload: dict[str, Any] | None = None):
    body = payload or {
        "choices": [{"message": {"content": "GigaChat reply"}}],
        "usage": {"total_tokens": 33},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer giga-token"
        return httpx.Response(200, json=body)

    return handler


def ollama_ok(payload: dict[str, Any] | None = None):
    body = payload or {"response": "Ollama reply", "eval_count": 17}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return handler


# ----------------------------------------------------------------------------
# HermesClient
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hermes_generate_success(monkeypatch):
    """Hermes returns parsed text + token count."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "hermes_api_key", "hermes-key", raising=False)
    monkeypatch.setattr(llm_client.settings, "hermes_base_url", "https://hermes.test/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(hermes_ok())
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = HermesClient()
    text, tokens = await client.generate("Hi", system="You are helpful", max_tokens=64, temperature=0.5)
    assert text == "Hermes reply"
    assert tokens == 77


@pytest.mark.asyncio
async def test_hermes_generate_no_api_key(monkeypatch):
    """Missing API key raises ValueError BEFORE any HTTP call."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "hermes_api_key", "", raising=False)

    client = HermesClient()
    with pytest.raises(ValueError, match="HERMES_API_KEY"):
        await client.generate("anything")


@pytest.mark.asyncio
async def test_hermes_generate_http_error(monkeypatch):
    """401 response propagates as HTTPStatusError."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "hermes_api_key", "k", raising=False)
    monkeypatch.setattr(llm_client.settings, "hermes_base_url", "https://hermes.test/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = HermesClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.generate("test")


@pytest.mark.asyncio
async def test_hermes_generate_missing_usage(monkeypatch):
    """Missing `usage` field → tokens default to 0 (branch coverage)."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "hermes_api_key", "k", raising=False)
    monkeypatch.setattr(llm_client.settings, "hermes_base_url", "https://hermes.test/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = HermesClient()
    text, tokens = await client.generate("prompt")
    assert text == "x"
    assert tokens == 0


# ----------------------------------------------------------------------------
# GigaChatClient
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gigachat_generate_success_with_system(monkeypatch):
    """GigaChat includes system message when supplied."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "gigachat_token", "giga-token", raising=False)
    monkeypatch.setattr(llm_client.settings, "gigachat_base_url", "https://giga.test/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "GC reply"}}],
            "usage": {"total_tokens": 12},
        })

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = GigaChatClient()
    text, tokens = await client.generate("q", system="be terse")
    assert text == "GC reply"
    assert tokens == 12
    assert captured["body"]["messages"][0]["role"] == "system"
    assert captured["body"]["messages"][1]["role"] == "user"


@pytest.mark.asyncio
async def test_gigachat_generate_success_without_system(monkeypatch):
    """When system=None, no empty system message is appended (E201 branch)."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "gigachat_token", "giga-token", raising=False)
    monkeypatch.setattr(llm_client.settings, "gigachat_base_url", "https://giga.test/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = GigaChatClient()
    text, tokens = await client.generate("q")
    assert text == "ok"
    assert tokens == 0  # missing usage → 0
    msgs = captured["body"]["messages"]
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


@pytest.mark.asyncio
async def test_gigachat_generate_no_token(monkeypatch):
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "gigachat_token", "", raising=False)

    client = GigaChatClient()
    with pytest.raises(ValueError, match="GIGACHAT_TOKEN"):
        await client.generate("x")


@pytest.mark.asyncio
async def test_gigachat_generate_429(monkeypatch):
    """429 rate-limit error surfaces."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "gigachat_token", "t", raising=False)
    monkeypatch.setattr(llm_client.settings, "gigachat_base_url", "https://giga.test/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = GigaChatClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.generate("x")


# ----------------------------------------------------------------------------
# OllamaClient
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ollama_generate_with_system(monkeypatch):
    """Ollama concatenates system + prompt with double newline."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "ollama_url", "http://localhost:11434", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_model", "llama3.1:8b", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"response": "ollama reply", "eval_count": 9})

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = OllamaClient()
    text, tokens = await client.generate("Q", system="SYS", max_tokens=128, temperature=0.7)
    assert text == "ollama reply"
    assert tokens == 9
    assert captured["body"]["prompt"] == "SYS\n\nQ"
    assert captured["body"]["stream"] is False
    assert captured["body"]["options"]["num_predict"] == 128
    assert captured["body"]["options"]["temperature"] == 0.7


@pytest.mark.asyncio
async def test_ollama_generate_without_system(monkeypatch):
    """No system → prompt sent verbatim."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "ollama_url", "http://localhost:11434", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_model", "llama3.1:8b", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"response": "ok", "eval_count": 1})

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = OllamaClient()
    text, tokens = await client.generate("hello")
    assert captured["body"]["prompt"] == "hello"
    assert tokens == 1


@pytest.mark.asyncio
async def test_ollama_generate_500(monkeypatch):
    """Ollama 500 → HTTPStatusError."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "ollama_url", "http://localhost:11434", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_model", "llama3.1:8b", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server down")

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = OllamaClient()
    with pytest.raises(httpx.HTTPStatusError):
        await client.generate("x")


# ----------------------------------------------------------------------------
# LLMRouter — fallback logic
# ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_router_primary_success(monkeypatch):
    """When primary works, fallback is NOT consulted."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "llm_default_provider", "hermes", raising=False)
    monkeypatch.setattr(llm_client.settings, "llm_fallback_provider", "gigachat", raising=False)
    monkeypatch.setattr(llm_client.settings, "hermes_api_key", "k", raising=False)
    monkeypatch.setattr(llm_client.settings, "hermes_base_url", "https://hermes.test/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "primary ok"}}],
            "usage": {"total_tokens": 5},
        })

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    router = LLMRouter()
    text, used, tokens = await router.generate("hi")
    assert text == "primary ok"
    assert used == "hermes"
    assert tokens == 5
    assert call_count["n"] == 1  # fallback never hit


@pytest.mark.asyncio
async def test_router_fallback_success(monkeypatch):
    """Primary raises → fallback succeeds."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "llm_default_provider", "hermes", raising=False)
    monkeypatch.setattr(llm_client.settings, "llm_fallback_provider", "gigachat", raising=False)
    monkeypatch.setattr(llm_client.settings, "hermes_api_key", "k", raising=False)
    monkeypatch.setattr(llm_client.settings, "gigachat_token", "t", raising=False)
    monkeypatch.setattr(llm_client.settings, "gigachat_base_url", "https://giga.test/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "hermes_base_url", "https://hermes.test/v1", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    # Round 1 (Hermes) = 500, Round 2 (GigaChat) = 200
    n = {"i": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        n["i"] += 1
        if "hermes" in req.url.host or "/chat/completions" in req.url.path and "giga" not in req.url.host:
            # Hermes call
            if req.headers.get("Authorization") == "Bearer k":
                return httpx.Response(500, text="boom")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "fallback ok"}}],
            "usage": {"total_tokens": 11},
        })

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    router = LLMRouter()
    text, used, tokens = await router.generate("hi")
    assert text == "fallback ok"
    assert used == "gigachat"
    assert tokens == 11
    assert n["i"] == 2


@pytest.mark.asyncio
async def test_router_all_providers_fail(monkeypatch):
    """If every provider raises → RuntimeError('All LLM providers failed')."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "llm_default_provider", "hermes", raising=False)
    monkeypatch.setattr(llm_client.settings, "llm_fallback_provider", "gigachat", raising=False)
    monkeypatch.setattr(llm_client.settings, "hermes_api_key", "", raising=False)  # value-error path
    monkeypatch.setattr(llm_client.settings, "gigachat_token", "", raising=False)

    router = LLMRouter()
    with pytest.raises(RuntimeError, match="All LLM providers failed"):
        await router.generate("x")


@pytest.mark.asyncio
async def test_router_explicit_provider(monkeypatch):
    """Explicit `provider` overrides settings.llm_default_provider."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "llm_default_provider", "hermes", raising=False)
    monkeypatch.setattr(llm_client.settings, "llm_fallback_provider", "gigachat", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_url", "http://localhost:11434", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_model", "llama3.1:8b", raising=False)
    monkeypatch.setattr(llm_client.settings, "ollama_timeout", 30, raising=False)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "ollama win", "eval_count": 4})

    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    router = LLMRouter()
    text, used, tokens = await router.generate("x", provider="local_ollama")
    assert text == "ollama win"
    assert used == "local_ollama"
    assert tokens == 4


@pytest.mark.asyncio
async def test_router_value_error_propagates_to_runtime(monkeypatch):
    """Hermes ValueError (no key) is caught, then GigaChat also ValueError → RuntimeError."""
    from app.services import llm_client

    monkeypatch.setattr(llm_client.settings, "llm_default_provider", "hermes", raising=False)
    monkeypatch.setattr(llm_client.settings, "llm_fallback_provider", "gigachat", raising=False)
    monkeypatch.setattr(llm_client.settings, "hermes_api_key", "", raising=False)
    monkeypatch.setattr(llm_client.settings, "gigachat_token", "", raising=False)

    router = LLMRouter()
    with pytest.raises(RuntimeError):
        await router.generate("y", provider="hermes")
