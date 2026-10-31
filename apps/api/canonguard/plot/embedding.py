"""Embedding client for the local Ollama OpenAI-compatible endpoint."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import dotenv_values

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "bge-m3"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = _repo_root() / ".env"
    if env_path.exists():
        for key, value in dotenv_values(env_path).items():
            if value is not None:
                values[key] = value
    values.update(os.environ)
    return values


@dataclass(frozen=True)
class EmbeddingConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = "ollama"


def load_embedding_config() -> EmbeddingConfig:
    env = _load_env()
    return EmbeddingConfig(
        base_url=env.get("OLLAMA_EMBED_BASE_URL") or DEFAULT_BASE_URL,
        model=env.get("OLLAMA_EMBED_MODEL") or DEFAULT_MODEL,
        api_key=env.get("OLLAMA_EMBED_API_KEY") or "ollama",
    )


class OllamaEmbedder:
    def __init__(self, config: EmbeddingConfig, batch_size: int = 32) -> None:
        self._config = config
        self._batch_size = batch_size

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=120.0) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                response = await client.post(
                    f"{self._config.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._config.api_key}"},
                    json={"model": self._config.model, "input": batch},
                )
                response.raise_for_status()
                data = response.json()["data"]
                ordered = sorted(data, key=lambda item: item.get("index", 0))
                vectors.extend(list(item["embedding"]) for item in ordered)
        return vectors
