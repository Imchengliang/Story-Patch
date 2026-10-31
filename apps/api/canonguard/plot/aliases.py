"""Bilingual alias table.

Canonical names are English; aliases keep the source language(s). Matching uses
the same normalization as evidence checks (traditional -> simplified, strip
punctuation/whitespace), so ``寶玉``, ``宝玉`` and ``Baoyu`` resolve to one
canonical name without translating the original text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from canonguard.corpus.normalize import normalize_for_match


@dataclass(frozen=True)
class AliasEntry:
    canonical: str
    aliases: tuple[str, ...] = ()
    language: str = "unknown"


class AliasTable:
    def __init__(self, entries: list[AliasEntry]) -> None:
        alias_to_canonical: dict[str, str] = {}
        canonical_to_aliases: dict[str, tuple[str, ...]] = {}
        for entry in entries:
            names = _unique((entry.canonical, *entry.aliases))
            for name in names:
                key = normalize_for_match(name)
                if not key:
                    continue
                existing = alias_to_canonical.get(key)
                if existing is not None and existing != entry.canonical:
                    raise ValueError(
                        f"alias conflict: {name!r} -> {existing!r} and {entry.canonical!r}"
                    )
                alias_to_canonical[key] = entry.canonical
            canonical_to_aliases[entry.canonical] = names
        self._alias_to_canonical = alias_to_canonical
        self._canonical_to_aliases = canonical_to_aliases

    def canonicalize(self, name: str) -> str | None:
        return self._alias_to_canonical.get(normalize_for_match(name))

    def aliases_for(self, canonical: str) -> tuple[str, ...]:
        return self._canonical_to_aliases.get(canonical, (canonical,))

    def canonical_names(self) -> tuple[str, ...]:
        return tuple(self._canonical_to_aliases)

    def expand(self, names: list[str]) -> list[str]:
        expanded: list[str] = []
        for name in names:
            canonical = self.canonicalize(name) or name
            for alias in self.aliases_for(canonical):
                if alias not in expanded:
                    expanded.append(alias)
        return expanded


def _unique(names: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for name in names:
        cleaned = name.strip()
        if cleaned:
            seen[cleaned] = None
    return tuple(seen)


def parse_alias_table(payload: Any) -> AliasTable:
    if isinstance(payload, dict):
        payload = payload.get("characters", payload.get("entries", []))
    entries: list[AliasEntry] = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        canonical = item.get("canonical") or item.get("name")
        if not canonical:
            continue
        aliases = item.get("aliases") or []
        entries.append(
            AliasEntry(
                canonical=str(canonical).strip(),
                aliases=tuple(str(alias).strip() for alias in aliases if alias),
                language=str(item.get("language") or "unknown"),
            )
        )
    return AliasTable(entries)


def load_alias_table(path: Path) -> AliasTable:
    text = path.read_text(encoding="utf-8")
    is_yaml = path.suffix.lower() in {".yaml", ".yml"}
    payload: Any = yaml.safe_load(text) if is_yaml else json.loads(text)
    return parse_alias_table(payload)


def default_alias_path() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "plot" / "aliases.yaml"


def load_default_alias_table() -> AliasTable:
    path = default_alias_path()
    if not path.exists():
        return AliasTable([])
    return load_alias_table(path)
