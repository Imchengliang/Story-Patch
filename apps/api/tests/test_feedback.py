from pathlib import Path

from canonguard.plot.feedback import (
    SuggestionFeedback,
    append_feedback,
    load_feedback,
    suggestion_id_for,
    summarize_feedback,
)
from canonguard.plot.schemas import PlotSuggestion


def _suggestion(next_node: str = "next") -> PlotSuggestion:
    return PlotSuggestion(
        next_node=next_node,
        character_behavior_logic="logic",
        emotional_tone="tone",
        corpus_reference="Work · Scene",
        transfer_rationale="because",
        fit_score=0.5,
        novelty_score=0.5,
    )


def test_suggestion_id_is_stable() -> None:
    assert suggestion_id_for(_suggestion()) == suggestion_id_for(_suggestion())
    assert suggestion_id_for(_suggestion("a")) != suggestion_id_for(_suggestion("b"))


def test_append_load_and_summary(tmp_path: Path) -> None:
    store = tmp_path / "feedback.jsonl"
    suggestion = _suggestion()
    append_feedback(
        store,
        SuggestionFeedback(
            suggestion_id=suggestion_id_for(suggestion),
            decision="adopt",
            reason_code="other",
            corpus_reference=suggestion.corpus_reference,
            next_node=suggestion.next_node,
        ),
    )
    append_feedback(
        store,
        SuggestionFeedback(
            suggestion_id=suggestion_id_for(suggestion),
            decision="reject",
            reason_code="cliche",
            corpus_reference=suggestion.corpus_reference,
            next_node=suggestion.next_node,
        ),
    )
    records = load_feedback(store)
    assert len(records) == 2
    summary = summarize_feedback(records)
    assert summary["total"] == 2
    assert summary["decisions"] == {"adopt": 1, "reject": 1}
    assert summary["adoption_rate"] == 0.5
