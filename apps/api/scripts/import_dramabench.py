import argparse
import json
from pathlib import Path

from canonguard.plot.dramabench_loader import (
    find_dataset_file,
    load_dramabench,
    summarize,
)


def _default_corpus() -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / "data" / "corpus" / "DramaBench"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a local DramaBench copy.")
    parser.add_argument("--corpus", type=Path, default=_default_corpus())
    parser.add_argument("--path", type=Path)
    parser.add_argument("--limit", type=int, default=3, help="Preview records.")
    args = parser.parse_args()

    path = args.path if args.path is not None else find_dataset_file(args.corpus)
    if path is None or not path.exists():
        print(
            json.dumps(
                {
                    "error": "DramaBench file not found",
                    "corpus": str(args.corpus),
                    "hint": "Place the dataset under data/corpus/DramaBench/",
                },
                ensure_ascii=False,
            )
        )
        return

    records = load_dramabench(path)
    payload = {
        "file": str(path),
        "summary": summarize(records),
        "preview": [
            {
                "id": record.record_id,
                "title": record.title,
                "context_chars": len(record.context),
                "continuation_chars": len(record.continuation),
                "split_type": record.stats.split_type,
                "context_head": record.context[:160],
                "continuation_head": record.continuation[:160],
            }
            for record in records[: args.limit]
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
