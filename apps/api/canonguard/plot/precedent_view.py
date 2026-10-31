"""Build the precedent cards shown to the writer: scene, score, excerpt, highlight."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from canonguard.plot.scene_index import SceneIndex, scene_excerpt_around
from canonguard.plot.schemas import PlotSuggestion


def build_precedent_views(
    index: SceneIndex,
    scenes: Iterable[dict[str, Any]],
    suggestions: Sequence[PlotSuggestion],
    max_chars: int = 500,
) -> list[dict[str, Any]]:
    quote_by_reference: dict[str, str] = {}
    for suggestion in suggestions:
        if isinstance(suggestion, dict):
            quote = suggestion.get("reference_quote")
            reference = suggestion.get("corpus_reference")
        else:
            quote = suggestion.reference_quote
            reference = suggestion.corpus_reference
        if quote and reference and reference not in quote_by_reference:
            quote_by_reference[str(reference)] = str(quote)

    views: list[dict[str, Any]] = []
    for item in scenes:
        work_title = str(item.get("work_title", ""))
        scene_heading = str(item.get("scene_heading", ""))
        scene = index.get(str(item.get("scene_id", "")))
        quote = quote_by_reference.get(f"{work_title} · {scene_heading}")
        excerpt, highlight = (
            scene_excerpt_around(scene, quote, max_chars=max_chars) if scene else ("", None)
        )
        views.append(
            {
                "kind": "scene",
                "scene_id": str(item.get("scene_id", "")),
                "work_title": work_title,
                "scene_heading": scene_heading,
                "score": float(item.get("score", 0.0)),
                "excerpt": excerpt,
                "highlight": highlight,
                "reasons": [str(reason) for reason in item.get("reasons", [])],
            }
        )
    return views
