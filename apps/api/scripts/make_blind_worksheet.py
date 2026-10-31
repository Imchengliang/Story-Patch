"""Turn an eval report into a blind rating sheet.

Hides corpus reference, quote, fit and novelty so the rater judges only the
proposed next beat, behaviour logic, tone and transfer rationale.
"""

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any

COLUMNS = (
    "item_id",
    "scenario",
    "stuck_question",
    "next_node",
    "character_behavior_logic",
    "emotional_tone",
    "transfer_rationale",
    "usable",
    "note",
)


def build_rows(report: dict[str, Any], seed: int = 42) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    rng = random.Random(seed)
    for record in report.get("records") or []:
        scenario = str(record.get("id") or "scenario")
        question = str(record.get("stuck_question") or "")
        details = list(record.get("suggestions_detail") or [])
        rng.shuffle(details)
        for position, item in enumerate(details, start=1):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "item_id": f"{scenario}-{position:02d}",
                    "scenario": scenario,
                    "stuck_question": question,
                    "next_node": str(item.get("next_node") or ""),
                    "character_behavior_logic": str(item.get("character_behavior_logic") or ""),
                    "emotional_tone": str(item.get("emotional_tone") or ""),
                    "transfer_rationale": str(item.get("transfer_rationale") or ""),
                    "usable": "",
                    "note": "",
                }
            )
    return rows


def write_csv(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a blind worksheet from an eval report.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "data" / "evaluations" / "eval_heldout.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[3]
        / "data"
        / "evaluations"
        / "blind_worksheet_heldout.csv",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    report = json.loads(args.input.read_text(encoding="utf-8"))
    rows = build_rows(report, args.seed)
    write_csv(rows, args.output)
    print(json.dumps({"items": len(rows), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
