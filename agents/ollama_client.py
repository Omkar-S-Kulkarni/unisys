"""
agents/ollama_client.py
========================
Shared async Ollama client for all ADEO agents.

Provides:
  - Connection management to the local Ollama server
  - Health checks and model listing
  - Text generation with caching and timeout
  - Automatic fallback flag when Ollama is unreachable

Usage:
    from agents.ollama_client import OllamaClient

    client = OllamaClient()
    if await client.is_available():
        response = await client.generate("Analyze this zone...")
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any, Optional

import httpx

logger = logging.getLogger("OllamaClient")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "[%(name)s] %(message)s"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


class _LRUCache:
    """Simple LRU cache with TTL support."""

    def __init__(self, max_size: int = 128, ttl_seconds: int = 60):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str) -> Optional[str]:
        if key in self._cache:
            ts, value = self._cache[key]
            if time.time() - ts < self._ttl:
                self._cache.move_to_end(key)
                return value
            else:
                del self._cache[key]
        return None

    def put(self, key: str, value: str) -> None:
        if key in self._cache:
            del self._cache[key]
        self._cache[key] = (time.time(), value)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()


class OllamaClient:
    """
    Async client for the local Ollama REST API.

    Args:
        host:           Ollama server URL (default: http://127.0.0.1:11434)
        model:          Default model name for generation
        fallback_model: Secondary model if primary is unavailable
        timeout:        HTTP request timeout in seconds
        cache_ttl:      Cache time-to-live in seconds
    """

    def __init__(
        self,
        host: str = "http://127.0.0.1:11434",
        model: str = "llama3.2:3b",
        fallback_model: str = "qwen2.5-coder:7b",
        timeout: int = 30,
        cache_ttl: int = 30,
        enabled: bool = True,
    ) -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._fallback_model = fallback_model
        self._timeout = timeout
        self._enabled = enabled
        self._cache = _LRUCache(max_size=256, ttl_seconds=cache_ttl)
        self._available: Optional[bool] = None
        self._active_model: Optional[str] = None
        self._last_health_check: float = 0.0
        self._health_check_interval: float = 30.0  # seconds

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def active_model(self) -> Optional[str]:
        return self._active_model

    async def is_available(self) -> bool:
        """
        Check if Ollama server is reachable and has at least one model.
        Caches the result for health_check_interval seconds.
        """
        if not self._enabled:
            return False

        now = time.time()
        if self._available is not None and (now - self._last_health_check) < self._health_check_interval:
            return self._available

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._host}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    logger.info(f"Ollama available — models: {models}")

                    # Determine which model to use
                    if self._model in models or any(self._model.split(":")[0] in m for m in models):
                        self._active_model = self._model
                    elif self._fallback_model in models or any(self._fallback_model.split(":")[0] in m for m in models):
                        self._active_model = self._fallback_model
                        logger.info(f"Primary model {self._model} not found, using fallback: {self._fallback_model}")
                    elif models:
                        self._active_model = models[0]
                        logger.info(f"Using first available model: {self._active_model}")
                    else:
                        self._available = False
                        self._last_health_check = now
                        return False

                    self._available = True
                    self._last_health_check = now
                    return True
                else:
                    self._available = False
        except Exception as e:
            logger.warning(f"Ollama unreachable: {e}")
            self._available = False

        self._last_health_check = now
        return False

    async def list_models(self) -> list[str]:
        """List all models available on the Ollama server."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._host}/api/tags")
                if resp.status_code == 200:
                    return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 512,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        Generate text using the Ollama API.

        Args:
            prompt:      The user prompt to send.
            model:       Override the default model.
            system:      Optional system prompt.
            temperature: Sampling temperature (lower = more deterministic).
            max_tokens:  Maximum tokens to generate.
            use_cache:   Whether to use response caching.

        Returns:
            Generated text string, or None if Ollama is unavailable.
        """
        if not self._enabled:
            return None

        # Check cache
        cache_key = self._make_cache_key(prompt, model, system, temperature)
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info("Cache hit — returning cached LLM response")
                return cached

        # Ensure availability
        if not await self.is_available():
            logger.warning("Ollama not available — skipping LLM generation")
            return None

        use_model = model or self._active_model or self._model

        payload: dict[str, Any] = {
            "model": use_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._host}/api/generate",
                    json=payload,
                )
                if resp.status_code == 200:
                    result = resp.json().get("response", "").strip()
                    if result and use_cache:
                        self._cache.put(cache_key, result)
                    logger.info(f"LLM response received ({len(result)} chars, model={use_model})")
                    return result
                else:
                    logger.error(f"Ollama returned status {resp.status_code}: {resp.text[:200]}")
                    return None
        except httpx.TimeoutException:
            logger.warning(f"Ollama request timed out after {self._timeout}s")
            return None
        except Exception as e:
            logger.error(f"Ollama request failed: {e}")
            return None

    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Optional[dict]:
        """
        Generate a JSON response from the LLM.
        Parses the response as JSON, returning None on parse failure.
        """
        response = await self.generate(
            prompt=prompt,
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response is None:
            return None

        # Try to extract JSON from the response
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to find JSON within the response
            try:
                start = response.index("{")
                end = response.rindex("}") + 1
                return json.loads(response[start:end])
            except (ValueError, json.JSONDecodeError):
                # Try array format
                try:
                    start = response.index("[")
                    end = response.rindex("]") + 1
                    return json.loads(response[start:end])
                except (ValueError, json.JSONDecodeError):
                    logger.warning(f"Failed to parse LLM response as JSON: {response[:200]}")
                    return None

    def get_status(self) -> dict:
        """Return current client status for API endpoints."""
        return {
            "enabled": self._enabled,
            "available": self._available or False,
            "host": self._host,
            "active_model": self._active_model,
            "primary_model": self._model,
            "fallback_model": self._fallback_model,
            "cache_size": len(self._cache._cache),
        }

    def _make_cache_key(
        self,
        prompt: str,
        model: Optional[str],
        system: Optional[str],
        temperature: float,
    ) -> str:
        raw = f"{model or self._model}|{system or ''}|{temperature}|{prompt}"
        return hashlib.md5(raw.encode()).hexdigest()

    def clear_cache(self) -> None:
        """Clear the response cache."""
        self._cache.clear()
        logger.info("LLM response cache cleared")
