"""LLM Client abstraction (ADR-004).

Supports Hermes (priority), GigaChat (fallback), Ollama (local).
"""
from abc import ABC, abstractmethod
from typing import Literal

import httpx

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class LLMClient(ABC):
    """Abstract LLM client interface."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> tuple[str, int]:
        """Generate completion. Returns (text, tokens_used)."""
        ...


class HermesClient(LLMClient):
    """Hermes API client (OpenAI-compatible)."""

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> tuple[str, int]:
        if not settings.hermes_api_key:
            raise ValueError("HERMES_API_KEY not configured")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
            response = await client.post(
                f"{settings.hermes_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.hermes_api_key}"},
                json={
                    "model": settings.llm_model or "hermes-3",
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()

        text = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return text, tokens


class GigaChatClient(LLMClient):
    """GigaChat API client (ФСТЭК certified)."""

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> tuple[str, int]:
        if not settings.gigachat_token:
            raise ValueError("GIGACHAT_TOKEN not configured")

        # TODO: Implement OAuth token refresh for GigaChat
        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
            response = await client.post(
                f"{settings.gigachat_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.gigachat_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "GigaChat",
                    "messages": [
                        {"role": "system" if system else "user", "content": system or prompt},
                        {"role": "user", "content": prompt if system else ""},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()

        text = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return text, tokens


class OllamaClient(LLMClient):
    """Local Ollama LLM client."""

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> tuple[str, int]:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
            response = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": f"{system}\n\n{prompt}" if system else prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

        text = data["response"]
        tokens = data.get("eval_count", 0)
        return text, tokens


class LLMRouter:
    """LLM router with automatic fallback (ADR-004)."""

    def __init__(self) -> None:
        self.clients: dict[str, LLMClient] = {
            "hermes": HermesClient(),
            "gigachat": GigaChatClient(),
            "local_ollama": OllamaClient(),
        }

    async def generate(
        self,
        prompt: str,
        provider: Literal["hermes", "gigachat", "local_ollama"] | None = None,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> tuple[str, str, int]:
        """Generate with fallback. Returns (text, used_provider, tokens)."""
        primary = provider or settings.llm_default_provider
        fallback = settings.llm_fallback_provider

        for prov in [primary, fallback]:
            if prov == primary or prov != primary:  # Try fallback if primary fails
                try:
                    client = self.clients[prov]
                    text, tokens = await client.generate(prompt, system, max_tokens, temperature)
                    logger.info(
                        "llm_generated",
                        provider=prov,
                        tokens=tokens,
                        prompt_len=len(prompt),
                    )
                    return text, prov, tokens
                except Exception as e:
                    logger.warning(
                        "llm_provider_failed",
                        provider=prov,
                        error=str(e),
                    )

        raise RuntimeError("All LLM providers failed")


# Singleton
llm_router = LLMRouter()
