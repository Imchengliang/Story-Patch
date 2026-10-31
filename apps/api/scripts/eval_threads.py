"""Multi-turn conversation eval: one parse, then follow-ups with no re-paste.

Runs the harness directly (no HTTP, no database) so the same check works locally
and in a deterministic test harness. Round 1 carries the draft; every follow-up
carries only its question and must reuse the parsed stuck point already in
``RunState``.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from canonguard.api import deps
from canonguard.harness.planner import Plan, PlanStep, default_plan
from canonguard.harness.recorder import RecordingGateway
from canonguard.harness.runtime import RunState, TurnInput, stream_turn
from canonguard.harness.tools import ToolContext, default_registry

FOLLOWUPS = (
    "第二条太笼统，换一个更克制的方向，不要靠台词直说。",
    "如果必须保留这个结局，前面的铺垫该怎么改？",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _followup_plan() -> Plan:
    return Plan(
        steps=[
            PlanStep(tool="retrieve_scenes", reason="reuse stored stuck point"),
            PlanStep(tool="suggest_from_scenes", reason="reuse stored stuck point"),
        ],
        note="resume",
    )


class _Usage:
    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd = 0.0
        self.calls = 0
        self.models: set[str] = set()
        self.fallbacks = 0

    def record(self, role: str, result: Any) -> None:
        self.prompt_tokens += result.prompt_tokens
        self.completion_tokens += result.completion_tokens
        self.cost_usd += result.cost_usd
        self.calls += 1
        self.models.add(str(result.model))
        if result.used_fallback:
            self.fallbacks += 1


async def _run_round(
    ctx: ToolContext,
    turn: TurnInput,
    plan: Plan,
    state: RunState,
) -> dict[str, Any]:
    started = time.perf_counter()
    ok = False
    error = ""
    tools: list[str] = []
    async for event, data in stream_turn(default_registry, ctx, turn, plan, state):
        if event == "tool_result":
            tools.append(str(data.get("tool", "")))
        elif event == "done":
            ok = bool(data.get("ok", True))
            error = str(data.get("error", ""))
    suggestions = list(state.suggestions)
    return {
        "ok": ok,
        "error": error,
        "tools": tools,
        "suggestions": len(suggestions),
        "with_quote": sum(1 for item in suggestions if item.reference_quote),
        "latency_s": round(time.perf_counter() - started, 2),
        "stuck_question": state.stuck.stuck_question if state.stuck else None,
    }


async def _run_thread(
    record: dict[str, Any],
    scene_index: Any,
    base_gateway: Any,
    embedder: Any,
    aliases: Any,
    followups: int,
) -> dict[str, Any]:
    usage = _Usage()
    ctx = ToolContext(
        gateway=RecordingGateway(base_gateway, usage.record),
        aliases=aliases,
        scene_index=scene_index,
        embedder=embedder,
    )
    payload = record["input"]
    state = RunState()
    rounds = [
        await _run_round(
            ctx,
            TurnInput(
                story_state=payload["story_state"],
                stuck_question=payload["stuck_question"],
                genre=payload.get("genre", ""),
                characters=payload.get("characters") or [],
                constraints=payload.get("constraints") or [],
                desired_effect=payload.get("desired_effect", ""),
            ),
            default_plan(),
            state,
        )
    ]
    for index in range(followups):
        rounds.append(
            await _run_round(
                ctx,
                TurnInput(story_state="", stuck_question=FOLLOWUPS[index % len(FOLLOWUPS)]),
                _followup_plan(),
                state,
            )
        )
    return {
        "id": record.get("id"),
        "rounds": rounds,
        "usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cost_usd": round(usage.cost_usd, 6),
            "calls": usage.calls,
            "models": sorted(usage.models),
            "fallbacks": usage.fallbacks,
        },
    }


def _summarize(threads: list[dict[str, Any]], followups: int) -> dict[str, Any]:
    rounds = [thread["rounds"] for thread in threads]
    followup_rounds = [round_item for thread in rounds for round_item in thread[1:]]
    successful = [
        item
        for item in followup_rounds
        if item["ok"] and item["suggestions"] >= 1 and "parse_stuck_point" not in item["tools"]
    ]
    flat = [round_item for thread in rounds for round_item in thread]
    all_suggestions = sum(item["suggestions"] for item in flat)
    all_with_quote = sum(item["with_quote"] for item in flat)
    latencies = sorted(item["latency_s"] for item in flat)
    failures = [
        {"id": thread["id"], "round": index, "error": item["error"]}
        for thread in threads
        for index, item in enumerate(thread["rounds"])
        if not item["ok"]
    ]
    return {
        "threads": len(threads),
        "followups_per_thread": followups,
        "followup_rounds": len(followup_rounds),
        "successful_followups": len(successful),
        "success_rate": round(len(successful) / len(followup_rounds), 3) if followup_rounds else 0,
        "suggestions": all_suggestions,
        "citation_coverage": round(all_with_quote / all_suggestions, 3) if all_suggestions else 0,
        "latency_s_p50": round(statistics.median(latencies), 2) if latencies else 0,
        "prompt_tokens": sum(item["usage"]["prompt_tokens"] for item in threads),
        "completion_tokens": sum(item["usage"]["completion_tokens"] for item in threads),
        "cost_usd": round(sum(item["usage"]["cost_usd"] for item in threads), 4),
        "models": sorted({model for item in threads for model in item["usage"]["models"]}),
        "fallbacks": sum(item["usage"]["fallbacks"] for item in threads),
        "failures": failures,
    }


async def run(args: argparse.Namespace) -> int:
    source = args.input or _repo_root() / "data" / "evaluations" / "real_stuck_points_report.json"
    report = json.loads(Path(source).read_text(encoding="utf-8"))
    records = report["results"][: args.limit] if args.limit else report["results"]

    scene_index = deps.scene_index()
    gateway = deps.gateway()
    embedder = deps.embedder()
    aliases = deps.aliases()

    threads: list[dict[str, Any]] = []
    for offset, record in enumerate(records, start=1):
        thread = await _run_thread(record, scene_index, gateway, embedder, aliases, args.followups)
        thread["id"] = thread["id"] or f"thread_{offset}"
        threads.append(thread)
        print(
            json.dumps(
                {
                    "progress": f"{offset}/{len(records)}",
                    "id": thread["id"],
                    "rounds": len(thread["rounds"]),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
            flush=True,
        )

    summary = _summarize(threads, args.followups)
    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": str(source),
        "index": {"scenes": len(scene_index), "dim": scene_index.dim},
        "summary": summary,
        "threads": threads,
    }
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.gate:
        problems = []
        if summary["failures"]:
            problems.append(f"{len(summary['failures'])} failed round(s)")
        if summary["success_rate"] < args.min_success:
            problems.append(f"follow-up success {summary['success_rate']} < {args.min_success}")
        if problems:
            print(json.dumps({"gate": "failed", "problems": problems}, ensure_ascii=False))
            return 1
        print(json.dumps({"gate": "passed"}, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="3+ turn conversation regression eval.")
    parser.add_argument("--input", type=Path, help="Report with results[].input.")
    parser.add_argument(
        "--output", type=Path, default=_repo_root() / "data" / "evaluations" / "eval_threads.json"
    )
    parser.add_argument("--limit", type=int, default=3, help="Threads to run (default: 3).")
    parser.add_argument("--followups", type=int, default=2, help="Follow-up rounds per thread.")
    parser.add_argument("--min-success", type=float, default=0.8)
    parser.add_argument("--gate", action="store_true", help="Exit non-zero when thresholds fail.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
