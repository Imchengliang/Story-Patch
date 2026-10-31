from canonguard.eval.metrics import (
    GapEvalRecord,
    evidence_localization_rate,
    precision_for_type,
    recall_for_type,
    summarize,
    type_agreement,
)


def _record(gold: str, predicted: str, evidence: bool = True) -> GapEvalRecord:
    return GapEvalRecord(
        id=f"{gold}-{predicted}-{evidence}",
        gold_type=gold,
        predicted_type=predicted,
        evidence_found=evidence,
    )


def test_gap_metrics() -> None:
    records = [
        _record("A", "A"),
        _record("A", "A"),
        _record("A", "B", evidence=False),
        _record("B", "A"),
        _record("B", "B"),
        _record("C", "C"),
    ]

    assert type_agreement(records) == 4 / 6
    assert recall_for_type(records, "A") == 2 / 3
    assert precision_for_type(records, "A") == 2 / 3
    assert evidence_localization_rate(records) == 5 / 6

    summary = summarize(records)
    assert summary["n"] == 6
    assert summary["type_agreement"] == 0.6667
    assert summary["a_recall"] == 0.6667
    assert summary["b_false_positive_rate"] == 0.5
