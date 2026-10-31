"""Retrieval over raw scenes: dense + BM25 + free metadata, no structural labels."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from canonguard.corpus.normalize import normalize_for_match
from canonguard.plot.aliases import AliasTable
from canonguard.plot.scene_index import SceneHit, SceneIndex, primary_genre
from canonguard.plot.schemas import StuckPoint

GENRE_BONUS = 0.15
CHARACTER_BONUS = 0.20
# Rerank works on RRF scores normalised to (0, 1] by the pool peak, so this bonus
# is a weight against relevance itself: 0.45 keeps a top-ranked genre-mismatched
# scene ahead of a weakly ranked genre match, and was set on the 9 dev stuck
# points (scripts/ab_genre_prior.py) to restore the pre-quota-merge same-genre
# share, which had come from incomparable candidate scores rather than from a prior.
GENRE_PRIMARY_BONUS = 0.45
GENRE_OVERLAP_BONUS = 0.12
GENRE_MISMATCH_PENALTY = -0.05
# "Drama" appears in most STAGE genre strings; on its own it says little.
UBIQUITOUS_GENRES = frozenset({"drama"})


def build_scene_query(stuck: StuckPoint, alias_table: AliasTable) -> str:
    parts = [stuck.stuck_question, stuck.current_node, stuck.desired_effect, stuck.genre]
    for character in stuck.characters:
        canonical = alias_table.canonicalize(character.name) or character.name
        parts.append(" ".join(alias_table.aliases_for(canonical)))
        parts.append(character.function)
    parts.extend(stuck.constraints)
    parts.extend(stuck.narrative_functions)
    return " ".join(part for part in parts if part)


def _genre_tokens(value: str) -> tuple[str, ...]:
    return tuple(token.strip().lower() for token in value.split(",") if token.strip())


def _genre_match(stuck: StuckPoint, scene_genre: str) -> bool:
    if not stuck.genre or not scene_genre:
        return False
    left = stuck.genre.lower()
    right = scene_genre.lower()
    return left in right or right in left


def genre_affinity(stuck: StuckPoint, scene_genre: str) -> tuple[int, str]:
    """Distance between the writer's genre and a scene's multi-label genre.

    0 primary match, 1 specific overlap (non-ubiquitous), 2 only Drama/ubiquitous,
    3 none. STAGE genres are strings like ``"Crime, Thriller, Drama"``; treating
    "contains Drama" as a match would mark most of the corpus as same-genre.
    """
    wanted = _genre_tokens(stuck.genre)
    scene = _genre_tokens(scene_genre)
    if not wanted or not scene:
        return 3, ""
    if wanted[0] == scene[0]:
        return 0, "primary genre"
    specific = (set(wanted) & set(scene)) - UBIQUITOUS_GENRES
    if specific:
        return 1, f"genre overlap: {', '.join(sorted(specific))}"
    if set(wanted) & set(scene):
        return 2, "ubiquitous genre only"
    return 3, ""


def _character_overlap(stuck: StuckPoint, scene_characters: tuple[str, ...]) -> float:
    wanted = {
        normalize_for_match(character.name).lower()
        for character in stuck.characters
        if character.name
    }
    if not wanted or not scene_characters:
        return 0.0
    present = {normalize_for_match(name).lower() for name in scene_characters}
    return len(wanted & present) / len(wanted)


def rerank(
    hits: list[SceneHit],
    stuck: StuckPoint,
    *,
    genre_prior: str = "current",
) -> list[SceneHit]:
    """Cheap deterministic signals only: genre and character presence.

    ``current`` keeps the original substring match; ``specificity`` uses the
    primary genre plus non-ubiquitous overlap, so "contains Drama" no longer
    counts as a full match.

    RRF scores live around 1/(k+rank), so they are normalised first; otherwise a
    flat genre bonus would flatten every candidate onto the same value.
    """
    if not hits:
        return []
    peak = max(hit.score for hit in hits) or 1.0
    ranked: list[SceneHit] = []
    for hit in hits:
        score = hit.score / peak
        reasons: list[str] = []
        if genre_prior == "specificity":
            tier, reason = genre_affinity(stuck, hit.scene.genre)
            if tier == 0:
                score += GENRE_PRIMARY_BONUS
            elif tier == 1:
                score += GENRE_OVERLAP_BONUS
            elif tier == 3:
                score += GENRE_MISMATCH_PENALTY
            if reason:
                reasons.append(reason)
        elif _genre_match(stuck, hit.scene.genre):
            score += GENRE_BONUS
            reasons.append("genre match")
        overlap = _character_overlap(stuck, hit.scene.characters)
        if overlap > 0:
            score += CHARACTER_BONUS * overlap
            reasons.append(f"characters: {', '.join(hit.scene.characters[:3])}")
        ranked.append(
            SceneHit(
                scene=hit.scene,
                score=round(score, 6),
                dense=hit.dense,
                lexical=hit.lexical,
                vector=hit.vector,
                reasons=tuple([*hit.reasons, *reasons]),
            )
        )
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return ()
    return tuple(value / norm for value in vector)


def mmr_select(
    hits: list[SceneHit],
    top_k: int,
    mmr_lambda: float = 0.7,
    work_cap: int | None = None,
) -> list[SceneHit]:
    """Greedy relevance/diversity pick, optionally capped per work.

    Corpus vectors are not unit-normalised, so the norms are taken once here
    instead of inside every candidate/selected pair.

    ``work_cap`` rejects a work while the pool is being ordered. That picks the
    same list as ordering everything and trimming afterwards: a rejected scene
    never enters the selected set, so it cannot change any later similarity score,
    and a work's count only ever rises, so a rejection is final.
    """
    if not hits or top_k <= 0:
        return []
    normals = [_unit(hit.vector) for hit in hits]
    remaining = list(range(len(hits)))
    picked: list[int] = []
    counts: Counter[str] = Counter()
    while remaining and len(picked) < top_k:
        best_position = 0
        best_value = float("-inf")
        for position, candidate in enumerate(remaining):
            similarity = max(
                (
                    sum(a * b for a, b in zip(normals[candidate], normals[chosen], strict=False))
                    for chosen in picked
                ),
                default=0.0,
            )
            value = mmr_lambda * hits[candidate].score - (1 - mmr_lambda) * similarity
            if value > best_value:
                best_value = value
                best_position = position
        candidate = remaining.pop(best_position)
        work = hits[candidate].scene.work_id
        if work_cap is not None and work_cap > 0 and counts[work] >= work_cap:
            continue
        counts[work] += 1
        picked.append(candidate)
    return [hits[index] for index in picked]


def candidate_pool(
    index: SceneIndex,
    query: str,
    query_vector: list[float],
    stuck: StuckPoint,
    candidate_k: int = 30,
    genre_extra: int = 15,
    genre_recall: bool = False,
) -> list[SceneHit]:
    """Global candidates, plus a same-primary-genre quota from the same scoring pass.

    A global top-30 can contain very few same-genre scenes, so rerank has nothing
    to promote; the quota adds the best of the writer's primary genre that the
    global slice missed. Both halves share one fused scale, which is what makes
    merging them legitimate rather than heuristic.
    """
    key = primary_genre(stuck.genre) if genre_recall else ""
    return index.search(
        query,
        query_vector,
        top_k=candidate_k,
        genre_quota=(key, genre_extra) if key else None,
    )


def retrieve_scenes(
    index: SceneIndex,
    stuck: StuckPoint,
    query_vector: list[float],
    alias_table: AliasTable,
    top_k: int = 5,
    candidate_k: int = 30,
    mmr_lambda: float = 0.7,
    work_cap: int | None = 1,
    genre_prior: str = "specificity",
    genre_recall: bool = True,
    genre_extra: int = 15,
) -> list[SceneHit]:
    query = build_scene_query(stuck, alias_table)
    hits = candidate_pool(
        index,
        query,
        query_vector,
        stuck,
        candidate_k=candidate_k,
        genre_extra=genre_extra,
        genre_recall=genre_recall,
    )
    return mmr_select(
        rerank(hits, stuck, genre_prior=genre_prior),
        top_k,
        mmr_lambda,
        work_cap=work_cap if work_cap and work_cap > 0 else None,
    )
