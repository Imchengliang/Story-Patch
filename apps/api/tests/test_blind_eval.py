import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report() -> dict:
    return {
        "records": [
            {
                "id": "s1",
                "stuck_question": "q1",
                "suggestions_detail": [
                    {
                        "next_node": "a",
                        "character_behavior_logic": "x",
                        "emotional_tone": "t",
                        "transfer_rationale": "r",
                        "corpus_reference": "Secret work · scene",
                        "reference_quote": "secret quote",
                    },
                    {
                        "next_node": "b",
                        "character_behavior_logic": "y",
                        "emotional_tone": "u",
                        "transfer_rationale": "s",
                        "corpus_reference": "Other work · scene",
                        "reference_quote": None,
                    },
                ],
            },
            {
                "id": "s2",
                "stuck_question": "q2",
                "suggestions_detail": [
                    {"next_node": "c"},
                    {"next_node": "d"},
                ],
            },
        ]
    }


def test_blind_rows_hide_corpus_and_are_deterministic() -> None:
    module = _load("make_blind_worksheet")

    rows = module.build_rows(_report(), seed=7)

    assert len(rows) == 4
    assert all("corpus_reference" not in row for row in rows)
    assert all("reference_quote" not in row for row in rows)
    assert all(row["usable"] == "" for row in rows)
    assert {row["item_id"] for row in rows} == {"s1-01", "s1-02", "s2-01", "s2-02"}
    assert module.build_rows(_report(), seed=7) == rows


def test_score_blind_summarizes_and_reports_missing() -> None:
    module = _load("score_blind")

    summary = module.summarize(
        [
            {"item_id": "s1-01", "scenario": "s1", "usable": "usable"},
            {"item_id": "s1-02", "scenario": "s1", "usable": "needs_edit"},
            {"item_id": "s2-01", "scenario": "s2", "usable": "unusable"},
            {"item_id": "s2-02", "scenario": "s2", "usable": ""},
        ]
    )

    assert summary["items"] == 4
    assert summary["scored"] == 3
    assert summary["missing"] == ["s2-02"]
    assert summary["overall"]["usable_rate"] == pytest.approx(1 / 3, rel=1e-3)
    assert summary["per_scenario"]["s1"]["total"] == 2
    assert summary["per_scenario"]["s2"]["unusable"] == 1
