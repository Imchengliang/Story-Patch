"""Reader for the DramaBench script-continuation dataset.

DramaBench (arXiv 2512.19012, HF ``FutureMa/DramaBench``, MIT) ships JSONL files
of ``context`` -> ``continuation`` pairs. Each record also carries a ``stats``
block describing where the script was split. We only read a locally-provided
copy under ``data/corpus/DramaBench`` (gitignored).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DramaBenchStats:
    total_lines: int | None = None
    context_lines: int | None = None
    continuation_lines: int | None = None
    split_ratio: str | None = None
    split_type: str | None = None
    split_point: int | None = None


@dataclass(frozen=True)
class DramaBenchRecord:
    record_id: str
    title: str
    description: str
    context: str
    continuation: str
    stats: DramaBenchStats
    raw: dict[str, Any]


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _stats(raw: Any) -> DramaBenchStats:
    if not isinstance(raw, dict):
        return DramaBenchStats()
    return DramaBenchStats(
        total_lines=_optional_int(raw.get("total_lines")),
        context_lines=_optional_int(raw.get("context_lines")),
        continuation_lines=_optional_int(raw.get("continuation_lines")),
        split_ratio=_optional_str(raw.get("split_ratio")),
        split_type=_optional_str(raw.get("split_type")),
        split_point=_optional_int(raw.get("split_point")),
    )


def normalize_record(raw: dict[str, Any], index: int) -> DramaBenchRecord:
    record_id = raw.get("id")
    return DramaBenchRecord(
        record_id=str(record_id) if record_id is not None else f"record_{index}",
        title=str(raw.get("title") or ""),
        description=str(raw.get("description") or ""),
        context=str(raw.get("context") or ""),
        continuation=str(raw.get("continuation") or ""),
        stats=_stats(raw.get("stats")),
        raw=raw,
    )


def iter_dramabench(path: Path) -> Iterator[DramaBenchRecord]:
    index = 0
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_no}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"expected JSON object at {path}:{line_no}")
            yield normalize_record(raw, index)
            index += 1


def load_dramabench(path: Path, limit: int | None = None) -> list[DramaBenchRecord]:
    records: list[DramaBenchRecord] = []
    for record in iter_dramabench(path):
        records.append(record)
        if limit is not None and len(records) >= limit:
            break
    return records


def summarize(records: list[DramaBenchRecord]) -> dict[str, Any]:
    total = len(records)
    context_chars = sum(len(record.context) for record in records)
    continuation_chars = sum(len(record.continuation) for record in records)
    split_types = Counter(record.stats.split_type for record in records if record.stats.split_type)
    return {
        "records": total,
        "context_chars": context_chars,
        "continuation_chars": continuation_chars,
        "avg_context_chars": round(context_chars / total, 1) if total else 0.0,
        "avg_continuation_chars": round(continuation_chars / total, 1) if total else 0.0,
        "split_types": dict(split_types),
        "with_stats": sum(1 for record in records if record.stats.total_lines is not None),
    }


def find_dataset_file(corpus_dir: Path, preferred: str = "1103") -> Path | None:
    candidates = sorted(corpus_dir.glob("dramabench_continuation_*.jsonl"))
    if not candidates:
        return None
    for candidate in candidates:
        if preferred in candidate.name:
            return candidate
    return candidates[-1]
