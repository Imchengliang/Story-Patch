"""Retrieval-only A/B for the genre soft prior.

Compares the current substring match (``current``) against a multi-label
specificity prior (``specificity``) on the same stuck points. No LLM calls:
``stuck_point`` is taken from the eval report and only embeddings are used.
"""

import argparse
import asyncio
import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

from canonguard.api import deps
from canonguard.plot.raw_retrieval import (
    build_scene_query,
    candidate_pool,
    genre_affinity,
    rerank,
    retrieve_scenes,
)
from canonguard.plot.schemas import StuckPoint

CONFIGS = {
    "current": {"genre_prior": "current", "genre_recall": False},
    "recall": {"genre_prior": "current", "genre_recall": True},
    "recall_specificity": {"genre_prior": "specificity", "genre_recall": True},
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _tier_counts(tiers: list[int]) -> dict[int, int]:
    return dict(Counter(tiers))


def _config_metrics(
    stuck: StuckPoint,
    hits: list[Any],
    candidates: list[Any],
    latency_ms: float,
) -> dict[str, Any]:
    tiers = [genre_affinity(stuck, hit.scene.genre)[0] for hit in hits]
    candidate_tiers = [genre_affinity(stuck, hit.scene.genre)[0] for hit in candidates]
    work_counts = Counter(hit.scene.work_id for hit in hits)
    return {
        "top_primary": sum(1 for tier in tiers if tier == 0),
        "top_specific": sum(1 for tier in tiers if tier <= 1),
        "top_cross": sum(1 for tier in tiers if tier == 3),
        "tier_counts": _tier_counts(tiers),
        "distinct_works": len(work_counts),
        "max_work_share": max(work_counts.values()) if work_counts else 0,
        "candidate_primary": sum(1 for tier in candidate_tiers if tier == 0),
        "candidate_specific": sum(1 for tier in candidate_tiers if tier <= 1),
        "candidate_cross": sum(1 for tier in candidate_tiers if tier == 3),
        "candidate_size": len(candidate_tiers),
        "latency_ms": round(latency_ms, 1),
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for config in CONFIGS:
        values = [row["configs"][config] for row in rows]
        tier_totals: Counter[int] = Counter()
        for value in values:
            tier_totals.update({int(key): count for key, count in value["tier_counts"].items()})
        latencies = sorted(value["latency_ms"] for value in values)
        summary[config] = {
            "mean_top_primary": round(statistics.mean(v["top_primary"] for v in values), 2),
            "mean_top_specific": round(statistics.mean(v["top_specific"] for v in values), 2),
            "mean_top_cross": round(statistics.mean(v["top_cross"] for v in values), 2),
            "mean_distinct_works": round(statistics.mean(v["distinct_works"] for v in values), 2),
            "mean_candidate_primary": round(
                statistics.mean(v["candidate_primary"] for v in values), 2
            ),
            "mean_candidate_specific": round(
                statistics.mean(v["candidate_specific"] for v in values), 2
            ),
            "mean_candidate_cross": round(statistics.mean(v["candidate_cross"] for v in values), 2),
            "mean_candidate_size": round(statistics.mean(v["candidate_size"] for v in values), 2),
            "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else 0,
            "top_tier_totals": dict(sorted(tier_totals.items())),
        }
    return summary


async def run(args: argparse.Namespace) -> int:
    source = args.input or _repo_root() / "data" / "evaluations" / "real_stuck_points_report.json"
    report = json.loads(Path(source).read_text(encoding="utf-8"))
    records = report["results"][: args.limit] if args.limit else report["results"]

    index = deps.scene_index()
    embedder = deps.embedder()
    aliases = deps.aliases()

    rows: list[dict[str, Any]] = []
    for offset, record in enumerate(records, start=1):
        stuck = StuckPoint.model_validate(record["stuck_point"])
        query = build_scene_query(stuck, aliases)
        vector = (await embedder.embed([query]))[0]
        row: dict[str, Any] = {
            "id": record.get("id") or f"record_{offset}",
            "stuck_genre": stuck.genre,
            "configs": {},
        }
        for config, settings in CONFIGS.items():
            started = time.perf_counter()
            hits = retrieve_scenes(
                index,
                stuck,
                vector,
                aliases,
                top_k=5,
                candidate_k=30,
                work_cap=1,
                genre_prior=settings["genre_prior"],
                genre_recall=settings["genre_recall"],
            )
            latency_ms = (time.perf_counter() - started) * 1000
            candidates = rerank(
                candidate_pool(
                    index,
                    query,
                    vector,
                    stuck,
                    candidate_k=30,
                    genre_recall=settings["genre_recall"],
                ),
                stuck,
                genre_prior=settings["genre_prior"],
            )
            row["configs"][config] = {
                **_config_metrics(stuck, hits, candidates, latency_ms),
                "top_works": [
                    {
                        "work": hit.scene.work_title,
                        "genre": hit.scene.genre,
                        "tier": genre_affinity(stuck, hit.scene.genre)[0],
                    }
                    for hit in hits
                ],
            }
        rows.append(row)
        print(
            json.dumps(
                {
                    "progress": f"{offset}/{len(records)}",
                    "id": row["id"],
                    "current_primary": row["configs"]["current"]["top_primary"],
                    "recall_primary": row["configs"]["recall"]["top_primary"],
                    "recall_specificity_primary": row["configs"]["recall_specificity"][
                        "top_primary"
                    ],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    summary = _summarize(rows)
    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": str(source),
        "index": {"scenes": len(index), "dim": index.dim},
        "configs": {name: settings for name, settings in CONFIGS.items()},
        "summary": summary,
        "records": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval-only genre prior / recall A/B.")
    parser.add_argument("--input", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=_repo_root() / "data" / "evaluations" / "genre_recall_ab.json",
    )
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
