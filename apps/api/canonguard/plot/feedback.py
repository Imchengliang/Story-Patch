"""Append-only suggestion feedback store (JSONL)."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from canonguard.plot.schemas import PlotSuggestion

FeedbackDecision = Literal["adopt", "modify", "reject"]
FeedbackReason = Literal[
    "structure_mismatch",
    "character_mismatch",
    "world_conflict",
    "cliche",
    "low_novelty",
    "other",
]


class SuggestionFeedback(BaseModel):
    suggestion_id: str
    decision: FeedbackDecision
    reason_code: FeedbackReason = "other"
    note: str = ""
    stuck_question: str = ""
    corpus_reference: str = ""
    next_node: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def suggestion_id_for_values(corpus_reference: str, next_node: str) -> str:
    payload = f"{corpus_reference}|{next_node}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def suggestion_id_for(suggestion: PlotSuggestion) -> str:
    return suggestion_id_for_values(suggestion.corpus_reference, suggestion.next_node)


def append_feedback(path: Path, feedback: SuggestionFeedback) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(feedback.model_dump_json() + "\n")


def load_feedback(path: Path) -> list[SuggestionFeedback]:
    if not path.exists():
        return []
    records: list[SuggestionFeedback] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(SuggestionFeedback.model_validate_json(line))
    return records


def summarize_feedback(records: list[SuggestionFeedback]) -> dict[str, object]:
    decisions = Counter(record.decision for record in records)
    reasons = Counter(record.reason_code for record in records)
    total = len(records)
    adopted = decisions.get("adopt", 0)
    return {
        "total": total,
        "decisions": dict(decisions),
        "reasons": dict(reasons),
        "adoption_rate": round(adopted / total, 3) if total else 0.0,
    }
