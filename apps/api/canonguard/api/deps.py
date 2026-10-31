"""Shared cached service accessors, so the API never loads the index twice."""

from functools import lru_cache
from pathlib import Path

from canonguard.core.config import get_settings
from canonguard.llm.gateway import StructuredGateway
from canonguard.llm.providers import build_gateway
from canonguard.plot.aliases import AliasTable, load_default_alias_table
from canonguard.plot.embedding import OllamaEmbedder, load_embedding_config
from canonguard.plot.scene_index import SceneIndex


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


@lru_cache
def gateway() -> StructuredGateway:
    return build_gateway(get_settings())


@lru_cache
def embedder() -> OllamaEmbedder:
    return OllamaEmbedder(load_embedding_config())


@lru_cache
def aliases() -> AliasTable:
    return load_default_alias_table()


def scene_index_path() -> Path:
    return repo_root() / "data" / "indexes" / "scenes" / "index.json"


@lru_cache
def scene_index() -> SceneIndex:
    path = scene_index_path()
    if not path.exists():
        raise FileNotFoundError(f"scene index not found at {path}; run `make build-scene-index`")
    return SceneIndex.load(path)
