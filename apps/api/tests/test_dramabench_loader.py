from pathlib import Path

import pytest

from canonguard.plot.dramabench_loader import (
    find_dataset_file,
    load_dramabench,
    summarize,
)

FIXTURE = Path(__file__).parent / "fixtures" / "dramabench_sample.jsonl"


def test_load_returns_all_records() -> None:
    records = load_dramabench(FIXTURE)
    assert len(records) == 2

    first = records[0]
    assert first.record_id == "script_0001"
    assert first.title == "示例一"
    assert first.description == "一个关于选择的故事。"
    assert "ALICE" in first.context
    assert first.continuation == "BOB\n先坐下，再说。"
    assert first.stats.total_lines == 8
    assert first.stats.context_lines == 4
    assert first.stats.continuation_lines == 4
    assert first.stats.split_ratio == "50.0%"
    assert first.stats.split_type == "middle"
    assert first.stats.split_point == 4


def test_missing_stats_default_to_none() -> None:
    records = load_dramabench(FIXTURE)
    second = records[1]
    assert second.record_id == "script_0002"
    assert second.description == ""
    assert second.stats.total_lines is None
    assert second.stats.split_type is None
    assert second.stats.split_point is None


def test_limit_stops_early() -> None:
    assert len(load_dramabench(FIXTURE, limit=1)) == 1


def test_summarize_counts_chars_and_stats() -> None:
    records = load_dramabench(FIXTURE)
    summary = summarize(records)
    assert summary["records"] == 2
    assert summary["with_stats"] == 1
    assert summary["split_types"] == {"middle": 1}
    assert summary["context_chars"] == sum(len(record.context) for record in records)
    assert summary["continuation_chars"] == sum(len(record.continuation) for record in records)


def test_invalid_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_dramabench(bad)


def test_find_dataset_file_prefers_full_split(tmp_path: Path) -> None:
    (tmp_path / "dramabench_continuation_100.jsonl").write_text("", encoding="utf-8")
    full = tmp_path / "dramabench_continuation_1103.jsonl"
    full.write_text("", encoding="utf-8")
    assert find_dataset_file(tmp_path) == full
    assert find_dataset_file(tmp_path / "missing") is None
