"""Scene-level index built straight from STAGE scripts: no LLM, no labels.

This is the simple retrieval backend. A scene is the retrievable unit; the only
signals beyond raw text are facts that come for free (work, genre, language,
character names matched against the alias table). The structured PlotUnit index
stays available for comparison.
"""

from __future__ import annotations

import array
import json
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from canonguard.corpus.normalize import normalize_for_match
from canonguard.plot.aliases import AliasTable
from canonguard.plot.stage_loader import StageMovie
from canonguard.plot.text_search import Embedder, bm25_scores, ranks, rrf, tokenize

MIN_SCENE_CHARS = 20


@dataclass(frozen=True)
class SceneUnit:
    scene_id: str
    work_id: str
    work_title: str
    language: str
    genre: str
    scene_no: int
    heading: str
    text: str
    characters: tuple[str, ...] = ()

    def embed_text(self, max_chars: int = 1500) -> str:
        """What the vector sees: title and heading help separate same-genre scenes.

        Truncated because the local embedding endpoint rejects very large batches;
        1500 chars covers p95 of STAGE scenes in full.
        """
        return f"{self.work_title} | {self.heading}\n{self.text[:max_chars]}"


@dataclass(frozen=True)
class SceneHit:
    scene: SceneUnit
    score: float
    dense: float
    lexical: float
    vector: tuple[float, ...] = ()
    reasons: tuple[str, ...] = ()


def _scene_text(raw: dict[str, Any]) -> tuple[int, str, str]:
    try:
        scene_no = int(raw.get("_id") or raw.get("id") or 0)
    except (TypeError, ValueError):
        scene_no = 0
    heading = str(raw.get("title") or raw.get("heading") or f"scene {scene_no}").strip()
    text = str(raw.get("content") or raw.get("text") or "").strip()
    return scene_no, heading, text


def _characters_in(text: str, candidates: list[str], aliases: AliasTable) -> tuple[str, ...]:
    haystack = normalize_for_match(text)
    found: list[str] = []
    for name in candidates:
        canonical = aliases.canonicalize(name) or name
        probes = [normalize_for_match(probe) for probe in aliases.aliases_for(canonical)]
        if any(probe and probe in haystack for probe in probes):
            found.append(canonical)
    return tuple(dict.fromkeys(found))


def scenes_from_movie(movie: StageMovie, aliases: AliasTable) -> list[SceneUnit]:
    candidates = [character.name for character in movie.characters]
    units: list[SceneUnit] = []
    for raw in movie.script_scenes:
        scene_no, heading, text = _scene_text(raw)
        if len(text) < MIN_SCENE_CHARS:
            continue
        units.append(
            SceneUnit(
                scene_id=f"{movie.movie_id}:{scene_no}",
                work_id=movie.movie_id,
                work_title=movie.title,
                language=movie.language,
                genre=", ".join(movie.genres),
                scene_no=scene_no,
                heading=heading,
                text=text,
                characters=_characters_in(text, candidates, aliases),
            )
        )
    return units


class SceneIndex:
    def __init__(self, units: list[SceneUnit], vectors: Sequence[Sequence[float]]) -> None:
        if len(units) != len(vectors):
            raise ValueError("units and vectors must have the same length")
        self._units = units
        # Compact rows keep a full-corpus index (23k x 1024) near 90MB instead of
        # ~700MB of Python floats; cosine over arrays is memory-local and faster.
        self._vectors: list[array.array[float]] = [
            row if isinstance(row, array.array) else array.array("f", row) for row in vectors
        ]
        self._norms = [math.sqrt(sum(value * value for value in row)) for row in self._vectors]
        self._tokens = [tokenize(unit.text) for unit in units]
        self._document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            self._document_frequency.update(set(tokens))
        self._average_length = (
            sum(len(tokens) for tokens in self._tokens) / len(self._tokens) if self._tokens else 0.0
        )
        self._by_id = {unit.scene_id: unit for unit in units}
        self._by_primary_genre: dict[str, list[int]] = {}
        for index, unit in enumerate(units):
            key = primary_genre(unit.genre)
            if key:
                self._by_primary_genre.setdefault(key, []).append(index)

    def __len__(self) -> int:
        return len(self._units)

    @property
    def units(self) -> list[SceneUnit]:
        return list(self._units)

    @property
    def dim(self) -> int:
        return len(self._vectors[0]) if self._vectors else 0

    def get(self, scene_id: str) -> SceneUnit | None:
        return self._by_id.get(scene_id)

    def _allowed(self, primary_genre: str) -> list[int]:
        return self._by_primary_genre.get(primary_genre.strip().lower(), [])

    def _scores(self, query: str, vector: list[float]) -> tuple[list[float], list[float]]:
        query_norm = math.sqrt(sum(value * value for value in vector))
        if not query_norm:
            dense = [0.0] * len(self._vectors)
        else:
            dense = [
                sum(a * b for a, b in zip(vector, row, strict=False)) / (query_norm * norm)
                if norm
                else 0.0
                for row, norm in zip(self._vectors, self._norms, strict=False)
            ]
        lexical = bm25_scores(
            tokenize(query),
            self._tokens,
            document_frequency=self._document_frequency,
            average_length=self._average_length,
        )
        return dense, lexical

    def search(
        self,
        query: str,
        vector: list[float],
        top_k: int = 30,
        genre_quota: tuple[str, int] | None = None,
    ) -> list[SceneHit]:
        """Score the corpus once, then slice it.

        ``genre_quota=(genre, m)`` returns the global top ``top_k`` plus the best
        ``m`` scenes of that primary genre the global slice missed. Both halves
        carry scores from the same fused ranking, so merging them needs no
        renormalisation.
        """
        if not self._units:
            return []
        dense, lexical = self._scores(query, vector)
        fused = rrf([ranks(dense), ranks(lexical)])

        def by_score(indices: Iterable[int]) -> list[int]:
            return sorted(indices, key=fused.__getitem__, reverse=True)

        picks = by_score(range(len(self._units)))[:top_k]
        if genre_quota:
            key, extra_k = genre_quota
            # The quota is the genre's own top-m, minus whatever the global slice
            # already took - not m fresh scenes dug out further down the list.
            chosen = set(picks)
            picks = [
                *picks,
                *[index for index in by_score(self._allowed(key))[:extra_k] if index not in chosen],
            ]
        return [
            SceneHit(
                scene=self._units[index],
                score=round(fused[index], 6),
                dense=round(dense[index], 6),
                lexical=round(lexical[index], 6),
                vector=tuple(self._vectors[index]),
            )
            for index in picks
        ]

    def save(self, path: Path, *, split_vectors: bool = True) -> None:
        """Write ``units`` as JSON and, by default, vectors as a flat float32 file.

        A full-corpus index embeds ~23k x 1024 floats; keeping them out of JSON
        keeps the readable file small and parsing fast. Manual edits to
        ``index.json`` no longer touch the vectors, so a rebuild is required
        after changing scene text anyway.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        units_payload = [
            {
                "scene_id": unit.scene_id,
                "work_id": unit.work_id,
                "work_title": unit.work_title,
                "language": unit.language,
                "genre": unit.genre,
                "scene_no": unit.scene_no,
                "heading": unit.heading,
                "text": unit.text,
                "characters": list(unit.characters),
            }
            for unit in self._units
        ]
        if split_vectors and self._vectors:
            vector_path = path.with_name(f"{path.stem}.vectors.f32")
            _write_vectors(vector_path, self._vectors)
            payload: dict[str, Any] = {
                "units": units_payload,
                "vector_file": vector_path.name,
                "dim": self.dim,
                "count": len(self._units),
            }
        else:
            payload = {"units": units_payload, "vectors": [list(row) for row in self._vectors]}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SceneIndex:
        payload = json.loads(path.read_text(encoding="utf-8"))
        units = [SceneUnit(**item) for item in payload["units"]]
        if "vector_file" in payload:
            vectors = _read_vectors(
                path.parent / payload["vector_file"],
                count=int(payload["count"]),
                dim=int(payload["dim"]),
            )
        else:  # legacy single-file index with inline vectors
            vectors = payload["vectors"]
        return cls(units, vectors)


def _write_vectors(path: Path, vectors: Sequence[Sequence[float]]) -> None:
    flat = array.array("f")
    for vector in vectors:
        flat.extend(vector)
    with path.open("wb") as handle:
        flat.tofile(handle)


def _read_vectors(path: Path, count: int, dim: int) -> list[array.array[float]]:
    flat = array.array("f")
    expected = count * dim
    with path.open("rb") as handle:
        try:
            flat.fromfile(handle, expected)
        except EOFError as error:
            raise ValueError(f"vector file {path} is truncated") from error
    if len(flat) != expected:
        raise ValueError(f"vector file {path} has {len(flat)} floats, expected {expected}")
    return [flat[index * dim : (index + 1) * dim] for index in range(count)]


async def build_scene_index(
    movies: list[StageMovie],
    embedder: Embedder,
    aliases: AliasTable,
    batch_size: int = 32,
) -> SceneIndex:
    units: list[SceneUnit] = []
    for movie in movies:
        units.extend(scenes_from_movie(movie, aliases))
    vectors: list[list[float]] = []
    for start in range(0, len(units), batch_size):
        batch = units[start : start + batch_size]
        vectors.extend(await embedder.embed([unit.embed_text() for unit in batch]))
    return SceneIndex(units, vectors)


def _normalized_index_map(text: str) -> tuple[str, list[int]]:
    """Normalise char by char and keep a map back to original offsets."""
    chars: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        normalised = normalize_for_match(char)
        if not normalised:
            continue
        for piece in normalised:
            chars.append(piece)
            origin.append(index)
    return "".join(chars), origin


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Find the quote in the original text, tolerating spacing/punctuation differences."""
    exact = text.find(quote)
    if exact >= 0:
        return exact, exact + len(quote)
    normalised_text, origin = _normalized_index_map(text)
    normalised_quote = normalize_for_match(quote)
    if len(normalised_quote) < 2:
        return None
    position = normalised_text.find(normalised_quote)
    if position < 0:
        return None
    start = origin[position]
    end = origin[position + len(normalised_quote) - 1] + 1
    return start, end


def scene_excerpt_around(
    scene: SceneUnit,
    quote: str | None,
    max_chars: int = 500,
) -> tuple[str, str | None]:
    """Return a window of the scene text plus the exact quote span inside it."""
    text = " ".join(scene.text.split())
    if not quote:
        excerpt = text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"
        return excerpt, None
    span = locate_quote(scene.text, quote)
    if span is None:
        excerpt = text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"
        return excerpt, None
    start, end = span
    highlight = scene.text[start:end]
    # re-locate in the whitespace-collapsed text so the client can match exactly
    collapsed_highlight = " ".join(highlight.split())
    if not collapsed_highlight or collapsed_highlight not in text:
        excerpt = text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"
        return excerpt, None
    index = text.find(collapsed_highlight)
    left = max(0, index - (max_chars - len(collapsed_highlight)) // 2)
    right = min(len(text), left + max_chars)
    left = max(0, min(left, index))
    window = text[left:right]
    if left > 0:
        window = "…" + window
    if right < len(text):
        window = window + "…"
    return window, collapsed_highlight


def scene_excerpt(scene: SceneUnit, max_chars: int = 700) -> str:
    text = " ".join(scene.text.split())
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "…"


def scene_reference(scene: SceneUnit) -> str:
    return f"{scene.work_title} · {scene.heading}"


def primary_genre(value: str) -> str:
    """First genre label, lowercased: ``"Crime, Thriller, Drama"`` -> ``"crime"``."""
    return value.split(",", 1)[0].strip().lower()
