import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from canonguard.plot.story_kg import StoryKG, load_story_kg_config


def _default_draft() -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / "apps" / "api" / "tests" / "fixtures" / "sample_screenplay.txt"


def _config_summary() -> dict[str, object]:
    config = load_story_kg_config()
    return {
        "neo4j_uri": config.neo4j_uri,
        "llm_base_url": config.llm_base_url,
        "llm_model": config.llm_model,
        "embed_base_url": config.embed_base_url,
        "embed_model": config.embed_model,
        "embedding_dim": config.embedding_dim,
    }


async def run(args: argparse.Namespace) -> None:
    text = args.draft.read_text(encoding="utf-8")
    kg = StoryKG.from_env(group_id=args.group)
    try:
        if not args.skip_setup:
            await kg.setup()
        await kg.ingest(
            name=args.name,
            text=text,
            source_description=f"draft:{args.draft.name}",
            reference_time=datetime.now(UTC),
        )
        facts = await kg.search(args.query, num_results=args.limit)
        print(
            json.dumps(
                {
                    "config": _config_summary(),
                    "group_id": args.group,
                    "draft": str(args.draft),
                    "facts": [
                        {
                            "fact": fact.fact,
                            "name": fact.name,
                            "valid_at": fact.valid_at,
                            "invalid_at": fact.invalid_at,
                        }
                        for fact in facts
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await kg.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a draft into a Graphiti story graph and query it."
    )
    parser.add_argument("--draft", type=Path, default=_default_draft())
    parser.add_argument("--group", default="story-smoke")
    parser.add_argument("--name", default="smoke-episode")
    parser.add_argument("--query", default="主要人物之间是什么关系？")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--skip-setup", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
