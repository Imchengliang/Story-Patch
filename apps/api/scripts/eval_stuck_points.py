"""Quick regression eval: run real stuck points through parse -> retrieve -> suggest.

No database, no threads: this measures the retrieval + writer path directly so a
corpus change (like the full 151-film index) can be compared before/after. Reports
citation coverage, precedent diversity, latency, tokens and cost.

``--gate`` turns the report into a pass/fail check for CI.
"""

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from canonguard.api import deps
from canonguard.corpus.normalize import normalize_for_match
from canonguard.plot.raw_retrieval import build_scene_query, genre_affinity, retrieve_scenes
from canonguard.plot.raw_suggest import generate_raw_suggestions
from canonguard.plot.scene_index import SceneHit, SceneIndex
from canonguard.plot.schemas import StuckPoint
from canonguard.plot.stuck_point import parse_stuck_point


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _quote_is_verifiable(quote: str | None, hits: list[SceneHit]) -> bool:
    if not quote:
        return False
    normalized = normalize_for_match(quote)
    if len(normalized) < 2:
        return False
    return any(normalized in normalize_for_match(hit.scene.text) for hit in hits)


def _record_metrics(
    stuck: StuckPoint,
    hits: list[SceneHit],
    suggestions: list[Any],
    elapsed_s: float,
    parse_result: Any,
    writer_result: Any,
) -> dict[str, Any]:
    works = Counter(hit.scene.work_id for hit in hits)
    with_quote = [item for item in suggestions if item.reference_quote]
    unverifiable = [
        item.reference_quote
        for item in with_quote
        if not _quote_is_verifiable(item.reference_quote, hits)
    ]
    tiers = [genre_affinity(stuck, hit.scene.genre)[0] for hit in hits]
    by_reference = {f"{hit.scene.work_title} · {hit.scene.heading}": hit for hit in hits}
    cited_tiers = [
        genre_affinity(stuck, hit.scene.genre)[0]
        for item in suggestions
        if (hit := by_reference.get(item.corpus_reference)) is not None
    ]
    return {
        "stuck_question": stuck.stuck_question,
        "suggestions": len(suggestions),
        "with_quote": len(with_quote),
        "unverifiable_quotes": len(unverifiable),
        "distinct_works": len(works),
        "max_work_share": max(works.values()) if works else 0,
        "top_primary": sum(1 for tier in tiers if tier == 0),
        "top_specific": sum(1 for tier in tiers if tier <= 1),
        "top_cross": sum(1 for tier in tiers if tier == 3),
        "cited_total": len(cited_tiers),
        "cited_primary": sum(1 for tier in cited_tiers if tier == 0),
        "cited_specific": sum(1 for tier in cited_tiers if tier <= 1),
        "cited_cross": sum(1 for tier in cited_tiers if tier == 3),
        "suggestions_detail": [
            {
                "next_node": item.next_node,
                "character_behavior_logic": item.character_behavior_logic,
                "emotional_tone": item.emotional_tone,
                "corpus_reference": item.corpus_reference,
                "reference_quote": item.reference_quote,
                "transfer_rationale": item.transfer_rationale,
                "fit_score": item.fit_score,
                "novelty_score": item.novelty_score,
            }
            for item in suggestions
        ],
        "top_works": [hit.scene.work_title for hit in hits],
        "latency_s": round(elapsed_s, 2),
        "prompt_tokens": parse_result.prompt_tokens + writer_result.prompt_tokens,
        "completion_tokens": parse_result.completion_tokens + writer_result.completion_tokens,
        "cost_usd": round(parse_result.cost_usd + writer_result.cost_usd, 6),
        "models": sorted({parse_result.model, writer_result.model}),
        "used_fallback": parse_result.used_fallback or writer_result.used_fallback,
    }


async def _run_one(
    record: dict[str, Any],
    index: SceneIndex,
    gateway: Any,
    embedder: Any,
    aliases: Any,
    parsed_only: bool,
    genre_prior: str = "specificity",
    genre_recall: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    if parsed_only:
        stuck = StuckPoint.model_validate(record["stuck_point"])
        parse_result = SimpleNamespace(
            prompt_tokens=0, completion_tokens=0, cost_usd=0.0, model="none", used_fallback=False
        )
    else:
        payload = record["input"]
        stuck, parse_result = await parse_stuck_point(
            gateway,
            payload["story_state"],
            payload["stuck_question"],
            genre=payload.get("genre", ""),
            characters=payload.get("characters") or [],
            constraints=payload.get("constraints") or [],
            desired_effect=payload.get("desired_effect", ""),
            alias_table=aliases,
        )

    vector = (await embedder.embed([build_scene_query(stuck, aliases)]))[0]
    hits = retrieve_scenes(
        index,
        stuck,
        vector,
        aliases,
        top_k=5,
        candidate_k=30,
        work_cap=1,
        genre_prior=genre_prior,
        genre_recall=genre_recall,
    )
    suggestions, writer_result = await generate_raw_suggestions(gateway, stuck, hits)
    return _record_metrics(
        stuck,
        hits,
        suggestions,
        time.perf_counter() - started,
        parse_result,
        writer_result,
    )


def _summarize(records: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [record for record in records if "error" not in record]
    total_suggestions = sum(record["suggestions"] for record in ok)
    total_with_quote = sum(record["with_quote"] for record in ok)
    latencies = sorted(record["latency_s"] for record in ok)
    return {
        "records": len(records) + len(failures),
        "ok_records": len(ok),
        "failed_records": len(failures),
        "suggestions_total": total_suggestions,
        "suggestions_per_record": round(total_suggestions / len(ok), 2) if ok else 0,
        "citation_coverage": round(total_with_quote / total_suggestions, 3)
        if total_suggestions
        else 0,
        "unverifiable_quotes": sum(record["unverifiable_quotes"] for record in ok),
        "mean_distinct_works": round(statistics.mean(r["distinct_works"] for r in ok), 2)
        if ok
        else 0,
        "max_work_share": max((r["max_work_share"] for r in ok), default=0),
        "mean_top_primary": round(statistics.mean(r["top_primary"] for r in ok), 2) if ok else 0,
        "mean_top_specific": round(statistics.mean(r["top_specific"] for r in ok), 2) if ok else 0,
        "mean_top_cross": round(statistics.mean(r["top_cross"] for r in ok), 2) if ok else 0,
        "cited_total": sum(r["cited_total"] for r in ok),
        "cited_primary": sum(r["cited_primary"] for r in ok),
        "cited_specific": sum(r["cited_specific"] for r in ok),
        "cited_cross": sum(r["cited_cross"] for r in ok),
        "cited_cross_rate": round(
            sum(r["cited_cross"] for r in ok) / sum(r["cited_total"] for r in ok), 3
        )
        if ok and sum(r["cited_total"] for r in ok)
        else 0,
        "latency_s_p50": round(statistics.median(latencies), 2) if latencies else 0,
        "latency_s_p95": latencies[min(len(latencies) - 1, math.ceil(len(latencies) * 0.95) - 1)]
        if latencies
        else 0,
        "prompt_tokens": sum(record["prompt_tokens"] for record in ok),
        "completion_tokens": sum(record["completion_tokens"] for record in ok),
        "cost_usd": round(sum(record["cost_usd"] for record in ok), 4),
        "fallbacks": sum(1 for record in ok if record["used_fallback"]),
        "models": sorted({model for record in ok for model in record["models"]}),
        "failures": failures,
    }


def _gate(summary: dict[str, Any], args: argparse.Namespace) -> list[str]:
    problems: list[str] = []
    if summary["failed_records"]:
        problems.append(f"{summary['failed_records']} record(s) errored")
    if summary["unverifiable_quotes"]:
        problems.append(f"{summary['unverifiable_quotes']} fabricated/mismatched quote(s)")
    if summary["citation_coverage"] < args.min_citation:
        problems.append(f"citation coverage {summary['citation_coverage']} < {args.min_citation}")
    if summary["mean_distinct_works"] < args.min_distinct_works:
        problems.append(
            f"mean distinct works {summary['mean_distinct_works']} < {args.min_distinct_works}"
        )
    return problems


async def run(args: argparse.Namespace) -> int:
    source = args.input or _repo_root() / "data" / "evaluations" / "real_stuck_points_report.json"
    report = json.loads(Path(source).read_text(encoding="utf-8"))
    records = report["results"]
    if args.limit is not None:
        records = records[: args.limit]

    index = deps.scene_index()
    gateway = deps.gateway()
    embedder = deps.embedder()
    aliases = deps.aliases()

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for offset, record in enumerate(records, start=1):
        record_id = record.get("id") or f"record_{offset}"
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                result = await _run_one(
                    record,
                    index,
                    gateway,
                    embedder,
                    aliases,
                    args.parsed_only,
                    args.genre_prior,
                    args.genre_recall,
                )
                result["id"] = record_id
                results.append(result)
                last_error = None
                break
            except Exception as error:  # noqa: BLE001 - one bad record must not hide the rest
                last_error = error
                if attempt == 0:
                    print(
                        json.dumps(
                            {
                                "retry": record_id,
                                "error": f"{type(error).__name__}: {error}",
                            },
                            ensure_ascii=False,
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
        if last_error is not None:
            failures.append(
                {
                    "id": record_id,
                    "error": f"{type(last_error).__name__}: {last_error}",
                }
            )
        print(
            json.dumps(
                {"progress": f"{offset}/{len(records)}", "id": record.get("id")},
                ensure_ascii=False,
            ),
            file=sys.stderr,
            flush=True,
        )

    summary = _summarize(results, failures)
    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": str(source),
        "index": {"scenes": len(index), "dim": index.dim},
        "mode": "parsed-only" if args.parsed_only else "full-chain",
        "genre_prior": args.genre_prior,
        "genre_recall": args.genre_recall,
        "summary": summary,
        "records": results,
    }
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))

    if args.gate:
        problems = _gate(summary, args)
        if problems:
            print(json.dumps({"gate": "failed", "problems": problems}, ensure_ascii=False))
            return 1
        print(json.dumps({"gate": "passed"}, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick regression eval over real stuck points.")
    parser.add_argument("--input", type=Path, help="Report with results[].input / stuck_point.")
    parser.add_argument(
        "--output", type=Path, default=_repo_root() / "data" / "evaluations" / "eval_quick.json"
    )
    parser.add_argument("--limit", type=int, help="Only the first N records.")
    parser.add_argument(
        "--parsed-only",
        action="store_true",
        help="Skip the extractor; reuse the pre-parsed stuck_point (retrieval-only).",
    )
    parser.add_argument(
        "--genre-prior",
        choices=["current", "specificity"],
        default="specificity",
        help="Genre soft prior used by retrieval.",
    )
    parser.add_argument(
        "--genre-recall",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add a same-primary-genre quota to the candidate pool.",
    )
    parser.add_argument("--min-citation", type=float, default=0.85)
    parser.add_argument("--min-distinct-works", type=float, default=3.5)
    parser.add_argument("--gate", action="store_true", help="Exit non-zero when thresholds fail.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
