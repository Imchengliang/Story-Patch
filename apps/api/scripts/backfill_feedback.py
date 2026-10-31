"""One-time import of legacy JSONL feedback into the suggestion_feedback table.

Deduplicates on ``(suggestion_ref, decision)``; legacy rows without a thread/run
are kept with a ``legacy-jsonl`` note so reports can separate them.
"""

import argparse
import json
from pathlib import Path

from canonguard.db.session import SessionLocal
from canonguard.harness.store import ThreadStore
from canonguard.plot.feedback import load_feedback


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy JSONL feedback into the table.")
    parser.add_argument(
        "--store",
        type=Path,
        default=_repo_root() / "data" / "evaluations" / "suggestion_feedback.jsonl",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    records = load_feedback(args.store) if args.store.exists() else []
    store = ThreadStore(SessionLocal)
    existing = {(row.suggestion_ref, row.decision) for row in store.list_feedback()}

    added = skipped = 0
    for record in records:
        key = (record.suggestion_id, record.decision)
        if key in existing:
            skipped += 1
            continue
        note = "legacy-jsonl" + (f": {record.note}" if record.note else "")
        if not args.dry_run:
            store.record_feedback(
                record.suggestion_id,
                record.decision,
                reason_code=record.reason_code,
                note=note,
            )
        added += 1

    print(
        json.dumps(
            {"added": added, "skipped": skipped, "dry_run": args.dry_run},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
