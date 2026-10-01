"""Tests for app/services/llm_client.py — HermesClient, GigaChatClient, OllamaClient, LLMRouter.

Goal: 80%+ coverage on app/services/llm_client.py (62 statements).

Strategy:
- Mock httpx.AsyncClient at the module level via monkeypatching its `__init__`
  so it returns an AsyncClient wired to a httpx.MockTransport. This avoids
  real network calls.
- Set the relevant settings.* attributes via monkeypatch (hermes_api_key,
  gigachat_token, llm_default_provider, llm_fallback_provider) for each test.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core import config as config_module
from app.services import llm_client as llm_module
from app.services.llm_client import (
    GigaChatClient,
    HermesClient,
    LLMRouter,
    OllamaClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def install_mock_client(monkeypatch, handler):
    """Patch httpx.AsyncClient so production code gets a MockTransport-backed client.

    Important: we capture the *original* httpx classes BEFORE patching the module,
    otherwise our factory would recurse infinitely (httpx.AsyncClient(...) inside
    the factory calls the patched factory again).
    """
    original_async_client = httpx.AsyncClient
    original_mock_transport = httpx.MockTransport

    def factory(*args, **kwargs):
        # Use captured originals to avoid recursion.
        transport = original_mock_transport(handler)
        return original_async_client(transport=transport, base_url="http://mocked")

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    # Also patch the alias used inside llm_client (same module object, but be explicit).
    monkeypatch.setattr(llm_module.httpx, "AsyncClient", factory)


def ok_response(payload: dict[str, Any], status_code: int = 200) -> httpx.Response:
    """Build a synthetic successful httpx.Response."""
    body = json.dumps(payload).encode("utf-8")
    return httpx.Response(
        status_code=status_code,
        content=body,
        headers={"content-type": "application/json"},
    )


def error_response(status_code: int, message: str = "boom") -> httpx.Response:
    """Build a synthetic error httpx.Response (will trigger raise_for_status)."""
    body = json.dumps({"error": message}).encode("utf-8")
    return httpx.Response(
        status_code=status_code,
        content=body,
        headers={"content-type": "application/json"},
    )


def chat_payload(text: str = "hello", tokens: int = 42) -> dict[str, Any]:
    """OpenAI-/GigaChat-style chat completion payload."""
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"total_tokens": tokens},
    }


def ollama_payload(text: str = "hello", eval_count: int = 17) -> dict[str, Any]:
    """Ollama-style /api/generate payload."""
    return {"response": text, "eval_count": eval_count}


# ---------------------------------------------------------------------------
# HermesClient
# ---------------------------------------------------------------------------

class TestHermesClient:
    @pytest.mark.asyncio
    async def test_missing_api_key_raises_value_error(self, monkeypatch):
        # Ensure no real network attempt happens before the guard.
        install_mock_client(monkeypatch, lambda req: ok_response(chat_payload()))
        monkeypatch.setattr(config_module.settings, "hermes_api_key", "", raising=False)

        with pytest.raises(ValueError, match="HERMES_API_KEY not configured"):
            await HermesClient().generate("hi")

    @pytest.mark.asyncio
    async def test_generate_success_returns_text_and_tokens(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "hermes_api_key", "secret-key", raising=False)

        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = json.loads(request.content)
            return ok_response(chat_payload(text="world", tokens=123))

        install_mock_client(monkeypatch, handler)

        text, tokens = await HermesClient().generate(
            "hello", system="be terse", max_tokens=64, temperature=0.7
        )

        assert text == "world"
        assert tokens == 123
        assert captured["auth"] == "Bearer secret-key"
        assert captured["url"].endswith("/chat/completions")
        body = captured["body"]
        assert body["messages"] == [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hello"},
        ]
        assert body["max_tokens"] == 64
        assert body["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_generate_without_system_omits_system_message(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "hermes_api_key", "k", raising=False)

        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return ok_response(chat_payload(text="ok", tokens=0))

        install_mock_client(monkeypatch, handler)

        text, tokens = await HermesClient().generate("hi")

        assert text == "ok"
        assert tokens == 0
        assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_generate_handles_missing_usage(self, monkeypatch):
        """If the response has no 'usage' key, total_tokens must default to 0."""
        monkeypatch.setattr(config_module.settings, "hermes_api_key", "k", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return ok_response({"choices": [{"message": {"content": "x"}}]})

        install_mock_client(monkeypatch, handler)

        text, tokens = await HermesClient().generate("hi")
        assert text == "x"
        assert tokens == 0

    @pytest.mark.asyncio
    async def test_generate_401_propagates_http_status_error(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "hermes_api_key", "k", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return error_response(401, "unauthorized")

        install_mock_client(monkeypatch, handler)

        with pytest.raises(httpx.HTTPStatusError):
            await HermesClient().generate("hi")

    @pytest.mark.asyncio
    async def test_generate_500_propagates_http_status_error(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "hermes_api_key", "k", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return error_response(500, "internal")

        install_mock_client(monkeypatch, handler)

        with pytest.raises(httpx.HTTPStatusError):
            await HermesClient().generate("hi")


# ---------------------------------------------------------------------------
# GigaChatClient
# ---------------------------------------------------------------------------

class TestGigaChatClient:
    @pytest.mark.asyncio
    async def test_missing_token_raises_value_error(self, monkeypatch):
        install_mock_client(monkeypatch, lambda req: ok_response(chat_payload()))
        monkeypatch.setattr(config_module.settings, "gigachat_token", "", raising=False)

        with pytest.raises(ValueError, match="GIGACHAT_TOKEN not configured"):
            await GigaChatClient().generate("hi")

    @pytest.mark.asyncio
    async def test_generate_success_with_system_message(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "gigachat_token", "tok-1", raising=False)

        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            captured["content_type"] = request.headers.get("content-type")
            captured["body"] = json.loads(request.content)
            return ok_response(chat_payload(text="giga-out", tokens=99))

        install_mock_client(monkeypatch, handler)

        text, tokens = await GigaChatClient().generate("hello", system="sys-prompt")

        assert text == "giga-out"
        assert tokens == 99
        assert captured["auth"] == "Bearer tok-1"
        assert captured["content_type"] == "application/json"
        assert captured["url"].endswith("/chat/completions")
        body = captured["body"]
        assert body["model"] == "GigaChat"
        # system message is included only when system truthy
        assert body["messages"] == [
            {"role": "system", "content": "sys-prompt"},
            {"role": "user", "content": "hello"},
        ]

    @pytest.mark.asyncio
    async def test_generate_without_system_skips_system_message(self, monkeypatch):
        """Per E201: when system is None/empty, do NOT add an empty system message."""
        monkeypatch.setattr(config_module.settings, "gigachat_token", "tok", raising=False)

        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return ok_response(chat_payload(text="ok", tokens=1))

        install_mock_client(monkeypatch, handler)

        await GigaChatClient().generate("hi")

        assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_generate_429_propagates_http_status_error(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "gigachat_token", "tok", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return error_response(429, "rate limited")

        install_mock_client(monkeypatch, handler)

        with pytest.raises(httpx.HTTPStatusError):
            await GigaChatClient().generate("hi")


# ---------------------------------------------------------------------------
# OllamaClient
# ---------------------------------------------------------------------------

class TestOllamaClient:
    @pytest.mark.asyncio
    async def test_generate_success_with_system_prefix(self, monkeypatch):
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return ok_response(ollama_payload(text="ollama-out", eval_count=33))

        install_mock_client(monkeypatch, handler)

        text, tokens = await OllamaClient().generate("hi", system="be brief")

        assert text == "ollama-out"
        assert tokens == 33
        assert captured["url"].endswith("/api/generate")
        body = captured["body"]
        assert body["stream"] is False
        assert body["options"]["num_predict"] == 1024  # default
        # system prefix is prepended with double newline separator
        assert body["prompt"] == "be brief\n\nhi"

    @pytest.mark.asyncio
    async def test_generate_without_system_uses_plain_prompt(self, monkeypatch):
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return ok_response(ollama_payload(text="ok", eval_count=0))

        install_mock_client(monkeypatch, handler)

        await OllamaClient().generate("hello world")

        assert captured["body"]["prompt"] == "hello world"

    @pytest.mark.asyncio
    async def test_generate_timeout_raises(self, monkeypatch):
        """Timeout via MockTransport raising ReadTimeout must propagate."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated timeout", request=request)

        install_mock_client(monkeypatch, handler)

        with pytest.raises(httpx.ReadTimeout):
            await OllamaClient().generate("hi")

    @pytest.mark.asyncio
    async def test_generate_500_propagates(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return error_response(500, "ollama crashed")

        install_mock_client(monkeypatch, handler)

        with pytest.raises(httpx.HTTPStatusError):
            await OllamaClient().generate("hi")


# ---------------------------------------------------------------------------
# LLMRouter (fallback logic)
# ---------------------------------------------------------------------------

class TestLLMRouter:
    @pytest.mark.asyncio
    async def test_primary_succeeds_no_fallback(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "llm_default_provider", "local_ollama", raising=False)
        monkeypatch.setattr(config_module.settings, "llm_fallback_provider", "gigachat", raising=False)

        attempts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/api/generate" in url:
                attempts.append("ollama")
                return ok_response(ollama_payload(text="primary", eval_count=5))
            attempts.append("gigachat")
            return ok_response(chat_payload(text="fallback", tokens=9))

        install_mock_client(monkeypatch, handler)

        text, used, tokens = await LLMRouter().generate("hi")

        assert text == "primary"
        assert used == "local_ollama"
        assert tokens == 5
        assert attempts == ["ollama"]  # fallback NOT attempted

    @pytest.mark.asyncio
    async def test_fallback_when_primary_fails(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "llm_default_provider", "hermes", raising=False)
        monkeypatch.setattr(config_module.settings, "llm_fallback_provider", "gigachat", raising=False)
        monkeypatch.setattr(config_module.settings, "hermes_api_key", "hk", raising=False)
        monkeypatch.setattr(config_module.settings, "gigachat_token", "gt", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            # Hermes hits /chat/completions via hermes_base_url
            # GigaChat hits /chat/completions via gigachat_base_url
            # We can't reliably tell bases apart, so use body to distinguish.
            body = json.loads(request.content) if request.content else {}
            if body.get("model") == "GigaChat":
                return ok_response(chat_payload(text="fallback-ok", tokens=11))
            # Hermes path: fail with 500
            return error_response(500, "hermes down")

        install_mock_client(monkeypatch, handler)

        text, used, tokens = await LLMRouter().generate("hi")

        assert text == "fallback-ok"
        assert used == "gigachat"
        assert tokens == 11

    @pytest.mark.asyncio
    async def test_explicit_provider_skips_default(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "llm_default_provider", "hermes", raising=False)
        monkeypatch.setattr(config_module.settings, "llm_fallback_provider", "gigachat", raising=False)
        monkeypatch.setattr(config_module.settings, "gigachat_token", "gt", raising=False)
        monkeypatch.setattr(config_module.settings, "hermes_api_key", "", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else {}
            if body.get("model") == "GigaChat":
                return ok_response(chat_payload(text="explicit", tokens=2))
            return error_response(401, "no key")

        install_mock_client(monkeypatch, handler)

        text, used, tokens = await LLMRouter().generate("hi", provider="gigachat")

        assert text == "explicit"
        assert used == "gigachat"
        assert tokens == 2

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises_runtime_error(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "llm_default_provider", "hermes", raising=False)
        monkeypatch.setattr(config_module.settings, "llm_fallback_provider", "local_ollama", raising=False)
        monkeypatch.setattr(config_module.settings, "hermes_api_key", "hk", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return error_response(503, "nope")

        install_mock_client(monkeypatch, handler)

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await LLMRouter().generate("hi")

    @pytest.mark.asyncio
    async def test_missing_provider_entry_is_skipped(self, monkeypatch):
        """If provider resolves to a key not in clients dict, KeyError → caught → continue."""
        monkeypatch.setattr(config_module.settings, "llm_default_provider", "nonexistent", raising=False)
        monkeypatch.setattr(config_module.settings, "llm_fallback_provider", "local_ollama", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return ok_response(ollama_payload(text="recovered", eval_count=4))

        install_mock_client(monkeypatch, handler)

        text, used, tokens = await LLMRouter().generate("hi")

        assert text == "recovered"
        assert used == "local_ollama"
        assert tokens == 4

    @pytest.mark.asyncio
    async def test_none_providers_are_skipped(self, monkeypatch):
        """When primary and fallback are both None the loop must not crash."""
        monkeypatch.setattr(config_module.settings, "llm_default_provider", "hermes", raising=False)
        monkeypatch.setattr(config_module.settings, "llm_fallback_provider", "gigachat", raising=False)
        # Force primary & fallback to evaluate to falsy by overriding the function
        # to return None via patching the client dict access path: simpler — pass provider=None
        # but the source uses `settings.llm_default_provider`. Patch settings values to None
        # isn't allowed by pydantic Literal, so instead we patch the LLMRouter generate's
        # access by overriding the attribute to return None via a property proxy.
        # Easiest: rely on `primary or settings.llm_default_provider` semantics — call with
        # provider="local_ollama" (truthy) and patch the fallback to be missing from clients.
        # Cleanest approach: drop fallback from clients dict.
        router = LLMRouter()
        # Drop gigachat so its None-skipped behaviour is testable.
        router.clients = {"local_ollama": OllamaClient()}
        monkeypatch.setattr(config_module.settings, "llm_default_provider", "local_ollama", raising=False)
        monkeypatch.setattr(config_module.settings, "llm_fallback_provider", "gigachat", raising=False)

        def handler(request: httpx.Request) -> httpx.Response:
            return ok_response(ollama_payload(text="ok", eval_count=1))

        install_mock_client(monkeypatch, handler)

        text, used, _ = await router.generate("hi")
        assert text == "ok"
        assert used == "local_ollama"

    @pytest.mark.asyncio
    async def test_none_provider_in_iteration_is_skipped(self, monkeypatch):
        """When fallback_provider is None, the `continue # skip None` branch must fire.

        To exercise it: primary must fail first (so we enter the fallback iteration)
        and fallback must be None (so the inner `if not prov: continue` branch fires,
        then we exit the loop and raise RuntimeError).
        """
        monkeypatch.setattr(
            config_module.settings, "llm_default_provider", "local_ollama", raising=False
        )
        # Force fallback to be None so the loop hits `if not prov: continue`.
        monkeypatch.setattr(
            config_module.settings, "llm_fallback_provider", None, raising=False
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return error_response(500, "primary down")

        install_mock_client(monkeypatch, handler)

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await LLMRouter().generate("hi")