"""Story-state knowledge graph backed by Graphiti.

Graphiti (MIT) builds a temporal entity/relationship graph from text using an
LLM for extraction and an embedder for hybrid retrieval. We point the LLM at
the project's OpenAI-compatible Qwen endpoint and the embedder at Ollama's
OpenAI-compatible ``/v1/embeddings`` (bge-m3, 1024-dim).

This module only models the *user's own story state*. The corpus side uses
STAGE annotations to build PlotUnit indexes and is unrelated to this graph.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.edges import EntityEdge
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.nodes import EpisodeType

from canonguard.core.config import get_settings

DEFAULT_NEO4J_URI = "bolt://127.0.0.1:7688"
DEFAULT_EMBED_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_EMBED_MODEL = "bge-m3"
DEFAULT_EMBED_DIM = 1024


@dataclass(frozen=True)
class StoryKGConfig:
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_small_model: str
    embed_base_url: str
    embed_api_key: str
    embed_model: str
    embedding_dim: int = DEFAULT_EMBED_DIM
    rerank: str = "off"


@dataclass(frozen=True)
class StoryFact:
    fact: str
    name: str
    source_node_uuid: str
    target_node_uuid: str
    valid_at: str | None
    invalid_at: str | None


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


def load_story_kg_config(env: dict[str, str] | None = None) -> StoryKGConfig:
    values = _load_env() if env is None else dict(env)
    settings = get_settings()

    qwen = (
        values.get("QWEN38_27B_FP8_BASE_URL") or "",
        values.get("QWEN38_27B_FP8_API_KEY") or "",
        values.get("QWEN38_27B_FP8_MODEL") or "",
    )
    deepseek = (
        values.get("DEEPSEEK_BASE_URL") or values.get("OPENAI_BASE_URL") or "",
        values.get("DEEPSEEK_API_KEY") or values.get("OPENAI_API_KEY") or "",
        values.get("DEEPSEEK_MODEL") or values.get("OPENAI_MODEL") or "",
    )
    preference = values.get("STORY_KG_LLM") or settings.model_preference
    order = (deepseek, qwen) if preference == "deepseek" else (qwen, deepseek)
    llm_base_url, llm_api_key, llm_model = next(
        (endpoint for endpoint in order if all(endpoint)), ("", "", "")
    )
    if not (llm_base_url and llm_api_key and llm_model):
        raise RuntimeError(
            "missing LLM endpoint config: set DEEPSEEK_* or QWEN38_27B_FP8_* in .env"
        )

    neo4j_uri = values.get("NEO4J_URI") or values.get("CANONGUARD_NEO4J_URI") or DEFAULT_NEO4J_URI
    embedding_dim = int(values.get("OLLAMA_EMBED_DIM", str(DEFAULT_EMBED_DIM)))
    return StoryKGConfig(
        neo4j_uri=neo4j_uri,
        neo4j_user=values.get("NEO4J_USER") or "neo4j",
        neo4j_password=values.get("NEO4J_PASSWORD") or settings.neo4j_password,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_small_model=values.get("QWEN38_27B_FP8_SMALL_MODEL") or llm_model,
        embed_base_url=values.get("OLLAMA_EMBED_BASE_URL") or DEFAULT_EMBED_BASE_URL,
        embed_api_key=values.get("OLLAMA_EMBED_API_KEY") or "ollama",
        embed_model=values.get("OLLAMA_EMBED_MODEL") or DEFAULT_EMBED_MODEL,
        embedding_dim=embedding_dim,
        rerank=values.get("STORY_KG_RERANK") or "off",
    )


class PassthroughReranker(CrossEncoderClient):
    """Keeps input order; used when no reranker model is configured."""

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(passage, 1.0 - index * 1e-6) for index, passage in enumerate(passages)]


def build_graphiti(config: StoryKGConfig) -> Graphiti:
    llm_config = LLMConfig(
        api_key=config.llm_api_key,
        model=config.llm_model,
        small_model=config.llm_small_model,
        base_url=config.llm_base_url,
        temperature=0.1,
        max_tokens=8192,
    )
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_dim=config.embedding_dim,
            embedding_model=config.embed_model,
            api_key=config.embed_api_key,
            base_url=config.embed_base_url,
        )
    )
    cross_encoder: CrossEncoderClient
    if config.rerank == "qwen":
        cross_encoder = OpenAIRerankerClient(config=llm_config)
    else:
        cross_encoder = PassthroughReranker()
    return Graphiti(
        uri=config.neo4j_uri,
        user=config.neo4j_user,
        password=config.neo4j_password,
        llm_client=OpenAIClient(config=llm_config),
        embedder=embedder,
        cross_encoder=cross_encoder,
    )


class StoryKG:
    def __init__(self, graphiti: Graphiti, group_id: str) -> None:
        self._graphiti = graphiti
        self._group_id = group_id

    @classmethod
    def from_env(cls, group_id: str) -> StoryKG:
        return cls(build_graphiti(load_story_kg_config()), group_id)

    @property
    def group_id(self) -> str:
        return self._group_id

    async def setup(self) -> None:
        await self._graphiti.build_indices_and_constraints()

    async def ingest(
        self,
        name: str,
        text: str,
        source_description: str = "story draft",
        reference_time: datetime | None = None,
    ) -> None:
        await self._graphiti.add_episode(
            name=name,
            episode_body=text,
            source_description=source_description,
            reference_time=reference_time or datetime.now(UTC),
            source=EpisodeType.text,
            group_id=self._group_id,
        )

    async def search(self, query: str, num_results: int = 10) -> list[StoryFact]:
        edges = await self._graphiti.search(
            query=query,
            group_ids=[self._group_id],
            num_results=num_results,
        )
        return [_to_fact(edge) for edge in edges]

    async def close(self) -> None:
        await self._graphiti.close()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _to_fact(edge: EntityEdge) -> StoryFact:
    return StoryFact(
        fact=edge.fact,
        name=edge.name,
        source_node_uuid=edge.source_node_uuid,
        target_node_uuid=edge.target_node_uuid,
        valid_at=_iso(edge.valid_at),
        invalid_at=_iso(edge.invalid_at),
    )
