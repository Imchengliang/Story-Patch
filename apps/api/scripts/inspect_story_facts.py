"""Ingest a draft into Graphiti and report what facts come back.

Usage:
    uv run python scripts/inspect_story_facts.py \
        --text-file ../data/sources/hongloumeng_ch030_035.txt --chars 1200
"""

import argparse
import asyncio
import json
import re
from collections import Counter
from pathlib import Path

from canonguard.db.session import SessionLocal
from canonguard.harness.store import ThreadStore
from canonguard.plot.story_state import StoryStateService

CJK = re.compile(r"[\u4e00-\u9fff]")


def _stats(facts: list[str], names: list[str]) -> dict[str, object]:
    lengths = [len(fact) for fact in facts]
    duplicate = [fact for fact, count in Counter(facts).items() if count > 1]
    with_names = [fact for fact in facts if any(name in fact for name in names)]
    translated = [
        fact for fact in facts if _is_english(fact) and any(name in fact for name in names)
    ]
    return {
        "facts": len(facts),
        "avg_chars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "chinese_facts": sum(1 for fact in facts if CJK.search(fact)),
        "with_character_names": len(with_names),
        "english_only": sum(1 for fact in facts if _is_english(fact)),
        "translated_name_facts": len(translated),
        "duplicates": len(duplicate),
    }


def _is_english(text: str) -> bool:
    letters = len(re.findall(r"[A-Za-z]", text))
    return letters > len(CJK.findall(text)) * 2


async def run(args: argparse.Namespace) -> None:
    text = args.text_file.read_text(encoding="utf-8")[: args.chars]
    store = ThreadStore(SessionLocal)
    state = store.create_story_state(
        title=f"fact-eval:{args.text_file.name}",
        source_text=text,
        language="zh",
    )
    service = StoryStateService(store)
    result = await service.ingest_story(state.id)
    facts = [fact.source_span or fact.subject for fact in store.list_story_facts(state.id)]
    print(
        json.dumps(
            {
                "story_state_id": str(state.id),
                "ingest": result,
                "stats": _stats(facts, args.names),
                "facts": facts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Inspect facts extracted from a Chinese draft.")
    parser.add_argument(
        "--text-file",
        type=Path,
        default=root / "data" / "sources" / "hongloumeng_ch030_035.txt",
    )
    parser.add_argument("--chars", type=int, default=1200)
    parser.add_argument("--names", nargs="*", default=["宝玉", "黛玉", "宝钗", "袭人", "王夫人"])
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
