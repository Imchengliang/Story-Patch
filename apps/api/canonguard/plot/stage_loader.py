"""Tolerant reader for the STAGE screenplay benchmark layout.

STAGE ships one directory per film under ``Chinese/`` or ``English/``. Each
movie directory contains ``script.json`` (scene list), ``episodes.json``
(narrative units), ``episde_relations.json`` (ordering/causal links),
``episde_causality_graph.json``, ``extraction_results.json`` and an ``ICRP``
folder with one sub-directory per character.

The repo carries no LICENSE file and the scripts are copyrighted, so this
module only reads a locally-provided copy under ``data/corpus/STAGE`` (which is
gitignored). Mapping STAGE records to our PlotUnit model happens elsewhere.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Canonical kind -> normalized filename candidates (punctuation stripped, lower).
# Includes typo variants used by STAGE, e.g. "episde_relations.json".
_FILENAME_KIND_ALIASES: dict[str, tuple[str, ...]] = {
    "script": ("scriptjson", "scriptsjson", "scenesjson"),
    "episodes": ("episodesjson", "episodejson"),
    "relations": (
        "episoderelationsjson",
        "episderelationsjson",
        "relationsjson",
        "edgerelationsjson",
    ),
    "causality": (
        "episodecausalitygraphjson",
        "episdecausalitygraphjson",
        "causalitygraphjson",
    ),
    "extraction": ("extractionresultsjson", "extractionsjson"),
    "characters": ("charactersjson", "charactercardsjson"),
}
_CHARACTER_DIR_ALIASES = ("icrp", "characters", "character")
_INFO_FILES = ("chinese_movie_info.csv", "english_movie_info.csv")


@dataclass(frozen=True)
class StageEpisode:
    episode_id: str
    summary: str
    event_texts: tuple[str, ...]
    scene_refs: tuple[int, ...]
    document_refs: tuple[str, ...]
    characters: tuple[str, ...]
    narrative_function: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StageRelation:
    source: str
    target: str
    relation: str
    confidence: float | None
    reason: str = ""
    source_documents: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageCharacter:
    name: str
    role: str | None
    description: str
    relations: tuple[str, ...]
    traits: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    speaking_style: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageMovie:
    movie_id: str
    title: str
    language: str
    genres: tuple[str, ...]
    root: Path
    script_scenes: tuple[dict[str, Any], ...]
    episodes: tuple[StageEpisode, ...]
    relations: tuple[StageRelation, ...]
    causality: list[Any] | dict[str, Any] | None
    characters: tuple[StageCharacter, ...]
    extra_files: tuple[str, ...]


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _first(obj: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(obj, dict):
        return default
    for key in keys:
        if key in obj and obj[key] not in (None, "", [], {}):
            return obj[key]
    return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        inner = _first(value, "description", "summary", "text", "event", "action", "content")
        return _text(inner) if inner is not None else ""
    return "" if value is None else str(value).strip()


def _maybe_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _coerce_str_list(value: Any) -> tuple[str, ...]:
    texts: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str):
            texts.append(item.strip())
        elif isinstance(item, dict):
            text = _first(item, "name", "id", "text", "character")
            if isinstance(text, str):
                texts.append(text.strip())
    return tuple(text for text in texts if text)


def _index_files(movie_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in sorted(movie_dir.iterdir()):
        if path.is_file() and path.suffix.lower() == ".json":
            index.setdefault(_normalize_name(path.name), path)
    return index


def _resolve(index: dict[str, Path], kind: str) -> Path | None:
    for candidate in _FILENAME_KIND_ALIASES[kind]:
        if candidate in index:
            return index[candidate]
    return None


def _character_dir(movie_dir: Path) -> Path | None:
    for path in movie_dir.iterdir():
        if path.is_dir() and _normalize_name(path.name) in _CHARACTER_DIR_ALIASES:
            return path
    return None


def _coerce_scenes(value: Any) -> tuple[dict[str, Any], ...]:
    container = value
    if isinstance(container, dict):
        container = _first(container, "scenes", "script", "data", default=container)
    scenes: list[dict[str, Any]] = []
    for item in _as_list(container):
        if isinstance(item, dict):
            scenes.append(item)
        elif isinstance(item, str):
            scenes.append({"content": item})
    return tuple(scenes)


def _coerce_int_list(value: Any) -> tuple[int, ...]:
    numbers: list[int] = []
    for item in _as_list(value):
        if isinstance(item, int):
            numbers.append(item)
        elif isinstance(item, str) and item.isdigit():
            numbers.append(int(item))
        elif isinstance(item, dict):
            number = _first(item, "scene_index", "index", "order", "scene_id", "id")
            if isinstance(number, int):
                numbers.append(number)
    return tuple(numbers)


def normalize_episode(raw: dict[str, Any], index: int) -> StageEpisode:
    episode_id = _first(raw, "episode_id", "id", "unit_id", "ep_id")
    summary = _first(raw, "description", "summary", "plot", "text", "title", "name")
    events = _first(
        raw,
        "events",
        "related_events",
        "associated_events",
        "event_ids",
        "scene_events",
        default=[],
    )
    scene_refs = _first(raw, "scene_refs", "scenes", "scene_indices", "scene_ids", default=[])
    document_refs = _first(raw, "source_documents", "documents", default=[])
    characters = _first(raw, "characters", "agents", "roles", default=[])
    function = _first(raw, "narrative_function", "function", "beat_type", "type")
    return StageEpisode(
        episode_id=str(episode_id) if episode_id is not None else f"episode_{index}",
        summary=_text(summary),
        event_texts=tuple(text for text in (_text(e) for e in _as_list(events)) if text),
        scene_refs=_coerce_int_list(scene_refs),
        document_refs=_coerce_str_list(document_refs),
        characters=_coerce_str_list(characters),
        narrative_function=_maybe_str(function),
        raw=raw,
    )


def _coerce_relations(value: Any) -> tuple[StageRelation, ...]:
    container = value
    if isinstance(container, dict):
        container = _first(container, "relations", "edges", "links", "data", default=container)
    relations: list[StageRelation] = []
    for item in _as_list(container):
        if not isinstance(item, dict):
            continue
        source = _first(item, "source", "from", "src", "head", "source_id", "from_id", "subject_id")
        target = _first(item, "target", "to", "tgt", "tail", "target_id", "to_id", "object_id")
        if source is None or target is None:
            continue
        relation = _first(
            item,
            "relation",
            "type",
            "label",
            "predicate",
            "relation_type",
            default="related_to",
        )
        confidence = _first(item, "confidence", "score", "weight", "effective_weight")
        relations.append(
            StageRelation(
                source=str(source),
                target=str(target),
                relation=str(relation),
                confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
                reason=_text(_first(item, "reason", "description", default="")),
                source_documents=_coerce_str_list(
                    _first(item, "source_documents", "documents", default=[])
                ),
            )
        )
    return tuple(relations)


def _character_from_record(record: dict[str, Any]) -> StageCharacter | None:
    name = _first(record, "name", "character", "id", "character_id")
    if name is None:
        return None
    return StageCharacter(
        name=str(name),
        role=_maybe_str(_first(record, "role", "function", "archetype")),
        description=_text(_first(record, "description", "summary", "profile", default="")),
        relations=_coerce_str_list(_first(record, "relations", "relationships", default=[])),
    )


def _character_from_dir(char_dir: Path) -> StageCharacter:
    persona_path = char_dir / "persona_card.json"
    persona = _read_json(persona_path) if persona_path.exists() else {}
    if not isinstance(persona, dict):
        persona = {}
    relations_path = char_dir / "key_relations.json"
    relations_raw = _read_json(relations_path) if relations_path.exists() else []
    relations = tuple(
        str(item["character"])
        for item in _as_list(relations_raw)
        if isinstance(item, dict) and item.get("character")
    )
    traits = _coerce_str_list(persona.get("traits", []))
    speaking_style = _coerce_str_list(persona.get("speaking_style", []))
    constraints = _coerce_str_list(persona.get("constraints", []))
    return StageCharacter(
        name=char_dir.name,
        role=None,
        description=", ".join(traits),
        relations=relations,
        traits=traits,
        constraints=constraints,
        speaking_style=speaking_style,
    )


def _load_characters(movie_dir: Path, index: dict[str, Path]) -> tuple[StageCharacter, ...]:
    char_dir = _character_dir(movie_dir)
    if char_dir is not None:
        subdirs = [path for path in sorted(char_dir.iterdir()) if path.is_dir()]
        if subdirs:
            return tuple(_character_from_dir(path) for path in subdirs)
        records: list[dict[str, Any]] = []
        for path in sorted(char_dir.glob("*.json")):
            for item in _as_list(_read_json(path)):
                if isinstance(item, dict):
                    records.append(item)
        return tuple(
            character
            for character in (_character_from_record(record) for record in records)
            if character is not None
        )

    char_path = _resolve(index, "characters")
    if char_path is not None:
        return tuple(
            character
            for character in (
                _character_from_record(item)
                for item in _as_list(_read_json(char_path))
                if isinstance(item, dict)
            )
            if character is not None
        )
    return ()


def _movie_info(movie_dir: Path, info: dict[str, Any] | None) -> tuple[str, tuple[str, ...]]:
    title = movie_dir.name
    genres: tuple[str, ...] = ()
    if info:
        title = str(info.get("title") or title)
        genres = tuple(str(info[key]) for key in ("genre_1", "genre_2", "genre_3") if info.get(key))
    return title, genres


def load_stage_movie(
    movie_dir: Path,
    language: str = "unknown",
    info: dict[str, Any] | None = None,
) -> StageMovie:
    index = _index_files(movie_dir)
    script_path = _resolve(index, "script")
    episodes_path = _resolve(index, "episodes")
    relations_path = _resolve(index, "relations")
    causality_path = _resolve(index, "causality")

    script_scenes = _coerce_scenes(_read_json(script_path)) if script_path else ()

    episodes: tuple[StageEpisode, ...] = ()
    if episodes_path is not None:
        raw_episodes = _read_json(episodes_path)
        container = raw_episodes
        if isinstance(container, dict):
            container = _first(container, "episodes", "units", "data", default=container)
        episodes = tuple(
            normalize_episode(item, offset)
            for offset, item in enumerate(_as_list(container))
            if isinstance(item, dict)
        )

    relations = _coerce_relations(_read_json(relations_path)) if relations_path else ()
    causality_raw = _read_json(causality_path) if causality_path else None
    causality = causality_raw if isinstance(causality_raw, (list, dict)) else None
    title, genres = _movie_info(movie_dir, info)

    return StageMovie(
        movie_id=movie_dir.name,
        title=title,
        language=language,
        genres=genres,
        root=movie_dir,
        script_scenes=script_scenes,
        episodes=episodes,
        relations=relations,
        causality=causality,
        characters=_load_characters(movie_dir, index),
        extra_files=tuple(sorted(p.name for p in movie_dir.iterdir() if p.is_file())),
    )


def load_movie_catalog(corpus_root: Path) -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    for name in _INFO_FILES:
        path = corpus_root / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                movie_id = row.get("movie_id")
                if movie_id:
                    catalog[movie_id] = dict(row)
    return catalog


def _language_from_dir(name: str) -> str:
    normalized = _normalize_name(name)
    if normalized.startswith("chin"):
        return "zh"
    if normalized.startswith("eng"):
        return "en"
    return name


def discover_movies(corpus_root: Path) -> list[tuple[Path, str]]:
    movies: list[tuple[Path, str]] = []
    if not corpus_root.exists():
        return movies
    for lang_dir in sorted(p for p in corpus_root.iterdir() if p.is_dir()):
        language = _language_from_dir(lang_dir.name)
        for movie_dir in sorted(p for p in lang_dir.iterdir() if p.is_dir()):
            index = _index_files(movie_dir)
            if _resolve(index, "script") is not None or _resolve(index, "episodes") is not None:
                movies.append((movie_dir, language))
    return movies


def _summarize(value: Any, depth: int = 0, max_depth: int = 3) -> Any:
    if depth >= max_depth:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            key: _summarize(item, depth + 1, max_depth) for key, item in list(value.items())[:12]
        }
    if isinstance(value, list):
        if not value:
            return {"type": "list", "len": 0}
        return {
            "type": "list",
            "len": len(value),
            "item": _summarize(value[0], depth + 1, max_depth),
        }
    return type(value).__name__


def probe_movie(movie_dir: Path) -> dict[str, Any]:
    index = _index_files(movie_dir)
    char_dir = _character_dir(movie_dir)
    summary: dict[str, Any] = {
        "title": movie_dir.name,
        "files": sorted(p.name for p in movie_dir.iterdir() if p.is_file()),
        "character_dir": char_dir.name if char_dir is not None else None,
        "character_dirs": (
            [p.name for p in sorted(char_dir.iterdir()) if p.is_dir()]
            if char_dir is not None
            else []
        ),
        "kinds": {},
    }
    for kind in _FILENAME_KIND_ALIASES:
        path = _resolve(index, kind)
        if path is None:
            summary["kinds"][kind] = {"resolved": None}
            continue
        summary["kinds"][kind] = {
            "resolved": path.name,
            "schema": _summarize(_read_json(path)),
        }
    return summary
