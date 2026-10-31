import asyncio
import os
from datetime import UTC, datetime

import pytest

from canonguard.plot.story_kg import (
    StoryKG,
    StoryKGConfig,
    load_story_kg_config,
)


def test_load_config_prefers_qwen() -> None:
    env = {
        "QWEN38_27B_FP8_BASE_URL": "http://qwen/v1",
        "QWEN38_27B_FP8_API_KEY": "k",
        "QWEN38_27B_FP8_MODEL": "qwen",
        "NEO4J_URI": "bolt://neo:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "pw",
        "OLLAMA_EMBED_MODEL": "bge-m3",
        "OLLAMA_EMBED_DIM": "1024",
    }
    config = load_story_kg_config(env)
    assert isinstance(config, StoryKGConfig)
    assert config.llm_base_url == "http://qwen/v1"
    assert config.llm_model == "qwen"
    assert config.llm_small_model == "qwen"
    assert config.neo4j_uri == "bolt://neo:7687"
    assert config.neo4j_password == "pw"
    assert config.embed_model == "bge-m3"
    assert config.embedding_dim == 1024


def test_load_config_falls_back_to_openai() -> None:
    env = {
        "OPENAI_BASE_URL": "https://api.example/v1",
        "OPENAI_API_KEY": "k",
        "OPENAI_MODEL": "m",
    }
    config = load_story_kg_config(env)
    assert config.llm_base_url == "https://api.example/v1"
    assert config.llm_model == "m"
    assert config.neo4j_uri == "bolt://127.0.0.1:7688"
    assert config.embed_model == "bge-m3"
    assert config.embed_base_url == "http://127.0.0.1:11434/v1"


def test_missing_llm_config_raises() -> None:
    with pytest.raises(RuntimeError):
        load_story_kg_config({})


@pytest.mark.skipif(
    not os.getenv("CANONGUARD_RUN_GRAPHITI"),
    reason="set CANONGUARD_RUN_GRAPHITI=1 to run against Neo4j+Ollama+Qwen",
)
def test_graphiti_roundtrip() -> None:
    async def _run() -> None:
        kg = StoryKG.from_env(group_id="pytest-story-kg")
        try:
            await kg.setup()
            await kg.ingest(
                name="roundtrip",
                text="宝玉与黛玉在书房争执，宝玉把旧帕赠予黛玉。",
                reference_time=datetime.now(UTC),
            )
            facts = await kg.search("宝玉 黛玉 关系", num_results=5)
            assert isinstance(facts, list)
        finally:
            await kg.close()

    asyncio.run(_run())
