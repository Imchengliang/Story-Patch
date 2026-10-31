"""Re-run recorded turns and report whether the pipeline still agrees with itself.

Usage:
    make replay-check                 # last 3 runs
    uv run python scripts/replay_check.py --limit 5
"""

import argparse
import asyncio
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from canonguard.api import deps
from canonguard.db.models import Run
from canonguard.db.session import SessionLocal
from canonguard.harness.replay import EXACT_TOOLS, replay_run
from canonguard.harness.runtime import RunState, TurnInput
from canonguard.harness.store import ThreadStore
from canonguard.harness.tools import ToolContext, default_registry
from canonguard.plot.schemas import StuckPoint
from canonguard.runs.ledger import RunLedger

REPLAYABLE_TASKS = ("plot_turn", "plot_suggest")


def _recent_runs(session: Session, limit: int) -> list[Run]:
    stmt = (
        select(Run)
        .where(Run.task.in_(REPLAYABLE_TASKS), Run.status == "succeeded")
        .order_by(Run.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def _turn_for(run: Run, store: ThreadStore) -> TurnInput:
    """Recover the writer message and story text that produced this run."""
    if run.thread_id is None:
        return TurnInput(story_state="", stuck_question="")
    messages = store.list_messages(run.thread_id)
    user = next(
        (
            message
            for message in reversed(messages)
            if message.role == "user" and message.created_at <= run.created_at
        ),
        None,
    )
    thread = store.get_thread(run.thread_id)
    story = store.get_story_state(thread.story_id) if thread and thread.story_id else None
    return TurnInput(
        story_state=story.source_text if story else "",
        stuck_question=user.content if user else "",
        genre="Drama",
    )


def _seed(run: Run, store: ThreadStore) -> RunState | None:
    """A follow-up turn was handed the thread's stuck point rather than producing one."""
    if run.thread_id is None:
        return None
    thread = store.get_thread(run.thread_id)
    if thread is None or not thread.active_stuck:
        return None
    return RunState(stuck=StuckPoint.model_validate(thread.active_stuck))


async def _replay(run: Run, store: ThreadStore) -> dict[str, Any]:
    new_run = RunLedger(SessionLocal).create_run(
        "plot_turn_replay",
        scope={"source_run_id": str(run.id)},
        thread_id=run.thread_id,
    )
    ctx = ToolContext(
        gateway=deps.gateway(),
        aliases=deps.aliases(),
        scene_index=deps.scene_index(),
        embedder=deps.embedder(),
        store=store,
        run_id=str(run.id),
        thread_id=run.thread_id,
    )
    report = await replay_run(
        default_registry,
        ctx,
        _turn_for(run, store),
        str(run.id),
        str(new_run.id),
        _seed(run, store),
    )
    return {
        "source_run_id": report.source_run_id,
        "new_run_id": report.new_run_id,
        "ok": report.ok,
        "error": report.error,
        "checks": [
            {"tool": check.tool, "equal": check.equal, "detail": check.detail}
            for check in report.checks
        ],
    }


async def run(args: argparse.Namespace) -> None:
    store = ThreadStore(SessionLocal)
    with SessionLocal() as session:
        runs = _recent_runs(session, args.limit)
    if not runs:
        print(json.dumps({"error": "no replayable runs found", "hint": "run a turn first"}))
        raise SystemExit(1)

    results = []
    for source in runs:
        if args.run_id and str(source.id) != args.run_id:
            continue
        results.append(await _replay(source, store))

    hard_drift = [
        item
        for item in results
        if any(check["tool"] in EXACT_TOOLS and not check["equal"] for check in item["checks"])
        or item["error"]
    ]
    writer_drift = [item for item in results if not item["ok"]]
    print(
        json.dumps(
            {
                "replayed": len(results),
                "deterministic_drift": len(hard_drift),
                "writer_variance": len(writer_drift),
                "note": (
                    "writer steps run at temperature 0.6: a different count or precedent mix "
                    "is variance, not a regression; deterministic steps must match exactly"
                ),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if hard_drift:
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay recorded turns and compare outputs.")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--run-id", help="Replay one specific run id.")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
