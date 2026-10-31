from scripts.calibrate_feedback import summarize_rows


def test_summarize_rows_groups_fit_and_novelty() -> None:
    linked = [
        {"decision": "adopt", "reason": "other", "fit": 0.9, "novelty": 0.6},
        {"decision": "adopt", "reason": "other", "fit": 0.7, "novelty": 0.8},
        {"decision": "reject", "reason": "cliche", "fit": 0.3, "novelty": 0.4},
    ]

    summary = summarize_rows(4, 1, linked, 2)

    assert summary["feedback_rows"] == 4
    assert summary["linked_rows"] == 3
    assert summary["unlinked_rows"] == 1
    assert summary["adoption_rate"] == 0.667
    assert summary["fit_by_decision"]["adopt"]["mean"] == 0.8
    assert summary["fit_by_decision"]["reject"]["mean"] == 0.3
    assert summary["fit_by_reason"]["cliche"]["count"] == 1
    assert summary["fit_by_decision_and_reason"]["adopt/other"]["count"] == 2


def test_summarize_rows_without_linked_data() -> None:
    summary = summarize_rows(0, 0, [], 2)

    assert summary["linked_rows"] == 0
    assert summary["adoption_rate"] == 0.0
    assert "还没有" in summary["note"]
