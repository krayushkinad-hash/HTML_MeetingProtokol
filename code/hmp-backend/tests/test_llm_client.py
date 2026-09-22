"""Tests for LLM client (Hermes + GigaChat fallback)."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.llm_client import GigaChatClient, HermesClient, LLMRouter, OllamaClient


@pytest.fixture
def mock_httpx_post():
    """Mock httpx.AsyncClient.post for all LLM clients."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock:
        yield mock


@pytest.mark.asyncio
async def test_hermes_generate_success(mock_httpx_post):
    """Test Hermes client returns text and tokens."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Test response"}}],
        "usage": {"total_tokens": 100},
    }
    mock_response.raise_for_status = MagicMock()
    mock_httpx_post.return_value = mock_response

    client = HermesClient()
    text, tokens = await client.generate("Test prompt")

    assert text == "Test response"
    assert tokens == 100


@pytest.mark.asyncio
async def test_hermes_generate_no_api_key():
    """Hermes without API key should raise ValueError."""
    with patch("app.services.llm_client.settings") as mock_settings:
        mock_settings.hermes_api_key = ""
        client = HermesClient()
        with pytest.raises(ValueError, match="HERMES_API_KEY"):
            await client.generate("test")


@pytest.mark.asyncio
async def test_router_uses_fallback_on_failure(mock_httpx_post):
    """Router should fallback to secondary provider if primary fails."""
    # First call (Hermes) fails
    # Second call (GigaChat fallback) succeeds
    mock_hermes_response = MagicMock()
    mock_hermes_response.raise_for_status.side_effect = httpx.HTTPError("Hermes down")

    mock_gigachat_response = MagicMock()
    mock_gigachat_response.json.return_value = {
        "choices": [{"message": {"content": "Fallback response"}}],
        "usage": {"total_tokens": 50},
    }
    mock_gigachat_response.raise_for_status = MagicMock()

    mock_httpx_post.side_effect = [mock_hermes_response, mock_gigachat_response]

    with patch("app.services.llm_client.settings") as mock_settings:
        mock_settings.hermes_api_key = "test-key"
        mock_settings.gigachat_token = "test-token"
        mock_settings.gigachat_scope = "GIGACHAT_API_PERS"
        mock_settings.gigachat_base_url = "https://gigachat.test/v1"
        mock_settings.ollama_timeout = 60
        mock_settings.llm_default_provider = "hermes"
        mock_settings.llm_fallback_provider = "gigachat"

        router = LLMRouter()
        text, used_provider, tokens = await router.generate("test prompt")

    assert text == "Fallback response"
    assert used_provider == "gigachat"
    assert tokens == 50


@pytest.mark.asyncio
async def test_ollama_generate_local(mock_httpx_post):
    """Test Ollama client (local)."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "response": "Local response",
        "eval_count": 42,
    }
    mock_response.raise_for_status = MagicMock()
    mock_httpx_post.return_value = mock_response

    client = OllamaClient()
    text, tokens = await client.generate("test", system="system")

    assert text == "Local response"
    assert tokens == 42
