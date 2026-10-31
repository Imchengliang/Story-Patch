"""Aggregate a filled blind worksheet.

Labels: ``usable`` / ``needs_edit`` / ``unusable``. Blank rows are reported as
missing and excluded from the rates.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

VALID = ("usable", "needs_edit", "unusable")


def summarize(rows: list[dict[str, str]]) -> dict[str, Any]:
    overall: Counter[str] = Counter()
    per_scenario: dict[str, Counter[str]] = {}
    missing: list[str] = []
    for row in rows:
        label = str(row.get("usable") or "").strip().lower()
        scenario = str(row.get("scenario") or "scenario")
        if label not in VALID:
            missing.append(str(row.get("item_id") or ""))
            continue
        overall[label] += 1
        per_scenario.setdefault(scenario, Counter())[label] += 1

    scored = sum(overall.values())

    def _rates(counter: Counter[str]) -> dict[str, Any]:
        total = sum(counter.values())
        return {
            "total": total,
            "usable": counter.get("usable", 0),
            "needs_edit": counter.get("needs_edit", 0),
            "unusable": counter.get("unusable", 0),
            "usable_rate": round(counter.get("usable", 0) / total, 3) if total else 0.0,
        }

    return {
        "items": len(rows),
        "scored": scored,
        "missing": missing,
        "overall": _rates(overall),
        "per_scenario": {name: _rates(counter) for name, counter in sorted(per_scenario.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a filled blind worksheet.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parents[3]
        / "data"
        / "evaluations"
        / "blind_worksheet_heldout.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[3]
        / "data"
        / "evaluations"
        / "blind_scores_heldout.json",
    )
    args = parser.parse_args()

    with args.input.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    summary = summarize(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["missing"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
