"""Calibrate suggestion scores against real adopt/modify/reject decisions.

Feedback rows are joined back to the assistant message payload for their run, so
fit/novelty come from the suggestion the writer actually saw. Rows without a
thread/run (old JSONL-era records) are counted but cannot be calibrated.
"""

import argparse
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from canonguard.db.session import SessionLocal
from canonguard.harness.store import ThreadStore
from canonguard.plot.feedback import load_feedback, suggestion_id_for_values


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _stats(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 3),
        "median": round(statistics.median(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def _linked_metrics(
    store: ThreadStore, thread_id: Any, run_id: Any, suggestion_ref: str
) -> tuple[float, float] | None:
    if thread_id is None or run_id is None:
        return None
    for message in store.list_messages(thread_id):
        if message.run_id != run_id or not isinstance(message.payload, dict):
            continue
        for item in message.payload.get("suggestions", []):
            if not isinstance(item, dict):
                continue
            reference = suggestion_id_for_values(
                str(item.get("corpus_reference", "")), str(item.get("next_node", ""))
            )
            if reference == suggestion_ref:
                return (
                    float(item.get("fit_score", 0.5)),
                    float(item.get("novelty_score", 0.5)),
                )
    return None


def summarize_rows(
    total_rows: int,
    unlinked_rows: int,
    linked: list[dict[str, Any]],
    jsonl_records: int,
) -> dict[str, Any]:
    by_decision: dict[str, list[float]] = defaultdict(list)
    by_reason: dict[str, list[float]] = defaultdict(list)
    novelty_by_decision: dict[str, list[float]] = defaultdict(list)
    pair: dict[str, list[float]] = defaultdict(list)
    for item in linked:
        by_decision[item["decision"]].append(item["fit"])
        by_reason[item["reason"]].append(item["fit"])
        novelty_by_decision[item["decision"]].append(item["novelty"])
        pair[f"{item['decision']}/{item['reason']}"].append(item["fit"])
    adopt = sum(1 for item in linked if item["decision"] == "adopt")
    return {
        "feedback_rows": total_rows,
        "linked_rows": len(linked),
        "unlinked_rows": unlinked_rows,
        "jsonl_records": jsonl_records,
        "adoption_rate": round(adopt / len(linked), 3) if linked else 0.0,
        "fit_by_decision": {key: _stats(values) for key, values in sorted(by_decision.items())},
        "fit_by_reason": {key: _stats(values) for key, values in sorted(by_reason.items())},
        "novelty_by_decision": {
            key: _stats(values) for key, values in sorted(novelty_by_decision.items())
        },
        "fit_by_decision_and_reason": {key: _stats(values) for key, values in sorted(pair.items())},
        "note": (
            "需要 thread/run 才能回溯 fit/novelty；旧 JSONL 记录只计数，无法校准。"
            if linked
            else "还没有可校准的反馈；先用新 UI 跑真实卡点并提交采纳/驳回。"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate suggestion fit/novelty by decision.")
    parser.add_argument(
        "--output",
        type=Path,
        default=_repo_root() / "data" / "evaluations" / "calibration_report.json",
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=_repo_root() / "data" / "evaluations" / "suggestion_feedback.jsonl",
    )
    args = parser.parse_args()

    store = ThreadStore(SessionLocal)
    rows = store.list_feedback()
    linked: list[dict[str, Any]] = []
    unlinked = 0
    for row in rows:
        metrics = _linked_metrics(store, row.thread_id, row.run_id, row.suggestion_ref)
        if metrics is None:
            unlinked += 1
            continue
        linked.append(
            {
                "decision": row.decision,
                "reason": row.reason_code or "other",
                "fit": metrics[0],
                "novelty": metrics[1],
            }
        )

    jsonl_records = len(load_feedback(args.jsonl)) if args.jsonl.exists() else 0
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": summarize_rows(len(rows), unlinked, linked, jsonl_records),
        "rows": linked,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
