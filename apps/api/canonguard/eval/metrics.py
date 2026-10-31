import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GapEvalRecord:
    id: str
    gold_type: str
    predicted_type: str
    evidence_found: bool

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "GapEvalRecord":
        return cls(
            id=str(payload["id"]),
            gold_type=str(payload["gold_type"]),
            predicted_type=str(payload["predicted_type"]),
            evidence_found=bool(payload["evidence_found"]),
        )


def load_jsonl(path: Path) -> list[GapEvalRecord]:
    records: list[GapEvalRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(GapEvalRecord.from_dict(json.loads(line)))
    return records


def type_agreement(records: list[GapEvalRecord]) -> float:
    if not records:
        return 0.0
    matches = sum(record.gold_type == record.predicted_type for record in records)
    return matches / len(records)


def recall_for_type(records: list[GapEvalRecord], target: str = "A") -> float:
    gold = [record for record in records if record.gold_type == target]
    if not gold:
        return 0.0
    matches = sum(record.predicted_type == target for record in gold)
    return matches / len(gold)


def precision_for_type(records: list[GapEvalRecord], target: str = "A") -> float:
    predicted = [record for record in records if record.predicted_type == target]
    if not predicted:
        return 0.0
    matches = sum(record.gold_type == target for record in predicted)
    return matches / len(predicted)


def b_false_positive_rate(records: list[GapEvalRecord]) -> float:
    gold_b = [record for record in records if record.gold_type == "B"]
    if not gold_b:
        return 0.0
    predicted_a = sum(record.predicted_type == "A" for record in gold_b)
    return predicted_a / len(gold_b)


def evidence_localization_rate(records: list[GapEvalRecord]) -> float:
    if not records:
        return 0.0
    found = sum(record.evidence_found for record in records)
    return found / len(records)


def summarize(records: list[GapEvalRecord]) -> dict[str, float | int]:
    return {
        "n": len(records),
        "type_agreement": round(type_agreement(records), 4),
        "a_recall": round(recall_for_type(records, "A"), 4),
        "a_precision": round(precision_for_type(records, "A"), 4),
        "b_false_positive_rate": round(b_false_positive_rate(records), 4),
        "evidence_localization_rate": round(evidence_localization_rate(records), 4),
    }
