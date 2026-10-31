from pathlib import Path

import pytest

from canonguard.plot.aliases import (
    AliasEntry,
    AliasTable,
    load_alias_table,
    load_default_alias_table,
    parse_alias_table,
)


def test_canonicalize_and_aliases() -> None:
    table = parse_alias_table(
        {"characters": [{"canonical": "Baoyu", "aliases": ["宝玉", "寶玉", "宝二爷"]}]}
    )
    assert table.canonicalize("宝玉") == "Baoyu"
    assert table.canonicalize("寶玉") == "Baoyu"
    assert table.canonicalize("  Baoyu ") == "Baoyu"
    assert table.aliases_for("Baoyu") == ("Baoyu", "宝玉", "寶玉", "宝二爷")


def test_unknown_names_pass_through() -> None:
    table = AliasTable([])
    assert table.canonicalize("无名") is None
    assert table.aliases_for("无名") == ("无名",)
    assert table.expand(["无名"]) == ["无名"]


def test_expand_dedupes_across_languages() -> None:
    table = parse_alias_table(
        [
            {"canonical": "Baoyu", "aliases": ["宝玉", "寶玉"]},
            {"name": "Alice", "aliases": ["爱丽丝"]},
        ]
    )
    assert table.expand(["宝玉", "寶玉", "Baoyu", "爱丽丝"]) == [
        "Baoyu",
        "宝玉",
        "寶玉",
        "Alice",
        "爱丽丝",
    ]


def test_alias_conflict_raises() -> None:
    with pytest.raises(ValueError):
        AliasTable(
            [
                AliasEntry(canonical="Baoyu", aliases=("宝玉",)),
                AliasEntry(canonical="Jade", aliases=("宝玉",)),
            ]
        )


def test_load_yaml_and_json(tmp_path: Path) -> None:
    yaml_path = tmp_path / "aliases.yaml"
    yaml_path.write_text(
        "characters:\n  - canonical: Baoyu\n    aliases: [宝玉]\n", encoding="utf-8"
    )
    assert load_alias_table(yaml_path).canonicalize("宝玉") == "Baoyu"

    json_path = tmp_path / "aliases.json"
    json_path.write_text('[{"canonical":"Alice","aliases":["爱丽丝"]}]', encoding="utf-8")
    assert load_alias_table(json_path).canonicalize("爱丽丝") == "Alice"


def test_default_alias_table_has_sample_entries() -> None:
    table = load_default_alias_table()
    assert table.canonicalize("宝玉") == "Baoyu"
    assert table.canonicalize("黛玉") == "Daiyu"
    assert table.canonicalize("寶釵") == "Baochai"
