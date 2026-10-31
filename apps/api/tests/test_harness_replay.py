import json
from typing import Any

from canonguard.db.session import SessionLocal
from canonguard.harness.planner import default_plan
from canonguard.harness.replay import (
    compare_outputs,
    remaining_pipeline,
    replay_run,
    restore_state,
    stream_resume,
)
from canonguard.harness.runtime import TurnInput, run_turn
from canonguard.harness.store import ThreadStore
from canonguard.harness.tools import ToolContext, default_registry
from canonguard.llm.gateway import RawCompletion, RoleConfig, StructuredGateway
from canonguard.plot.aliases import parse_alias_table
from canonguard.plot.scene_index import SceneIndex, SceneUnit
from canonguard.runs.ledger import RunLedger

STUCK_DRAFT = {
    "genre": "Drama",
    "characters": [{"name": "Baoyu", "function": "protagonist"}],
    "current_node": "Baoyu holds the handkerchief.",
    "stuck_question": "How do they move on?",
    "constraints": [],
    "desired_effect": "Advance",
    "narrative_functions": ["relationship_turn"],
    "value_polarity": "mixed",
}
SUGGESTIONS = {
    "suggestions": [
        {
            "precedent_index": index,
            "next_node": f"Beat {index}.",
            "character_behavior_logic": "He acts.",
            "emotional_tone": "restrained",
            "transfer_rationale": "Same structure.",
            "reference_quote": f"q{index}",
            "fit_score": 0.8,
            "novelty_score": 0.6,
        }
        for index in (1, 2, 1)
    ]
}


class RoleCompleter:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads

    async def __call__(
        self, model: str, messages: list[dict[str, str]], config: RoleConfig
    ) -> RawCompletion:
        return RawCompletion(content=json.dumps(self.payloads[model.split("/")[-1]]), model=model)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


def _scene_index() -> SceneIndex:
    units = [
        SceneUnit(
            scene_id=f"w:{index}",
            work_id=f"w{index}",
            work_title=f"Work {index}",
            language="zh",
            genre="Drama",
            scene_no=index,
            heading=f"SC {index}",
            text=f"q{index} 宝玉把帕子塞进袖子里。",
        )
        for index in (1, 2)
    ]
    return SceneIndex(units, [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])


def _context(run_id: str | None = None) -> ToolContext:
    run = run_id or str(RunLedger(SessionLocal).create_run("plot_turn").id)
    return ToolContext(
        gateway=StructuredGateway(
            roles={role: RoleConfig(model=f"fake/{role}") for role in ("extractor", "writer")},
            completer=RoleCompleter({"extractor": STUCK_DRAFT, "writer": SUGGESTIONS}),
        ),
        aliases=parse_alias_table({}),
        scene_index=_scene_index(),
        embedder=FakeEmbedder(),
        store=ThreadStore(SessionLocal),
        run_id=run,
    )


TURN = TurnInput(story_state="Baoyu holds a handkerchief.", stuck_question="How do they move on?")


async def test_full_run_can_be_restored_from_the_ledger() -> None:
    ctx = _context()
    await run_turn(default_registry, ctx, TURN)

    calls = ctx.store.list_tool_calls(ctx.run_id)  # type: ignore[union-attr]
    restored = restore_state(calls, _scene_index())

    assert restored.completed == list(default_plan().tools())
    assert restored.state.stuck is not None
    assert sorted(hit.scene.scene_id for hit in restored.state.scenes) == ["w:1", "w:2"]
    assert len(restored.state.suggestions) == 3


async def test_resume_only_executes_what_is_missing() -> None:
    source = _context()
    await default_registry.call(
        "parse_stuck_point", {"story_state": "s", "stuck_question": "q"}, source
    )

    target = _context()
    events = [
        (event, data)
        async for event, data in stream_resume(default_registry, target, TURN, str(source.run_id))
    ]

    assert events[-1][0] == "done"
    calls = target.store.list_tool_calls(target.run_id)  # type: ignore[union-attr]
    assert [call.name for call in calls] == ["retrieve_scenes", "suggest_from_scenes"]


async def test_resuming_a_finished_run_recomputes_nothing() -> None:
    source = _context()
    await run_turn(default_registry, source, TURN)

    target = _context()
    events = [
        (event, data)
        async for event, data in stream_resume(default_registry, target, TURN, str(source.run_id))
    ]

    assert [event for event, _ in events] == ["done"]
    assert events[0][1]["skipped"] == list(default_plan().tools())
    assert target.store.list_tool_calls(target.run_id) == []  # type: ignore[union-attr]


async def test_replay_of_a_deterministic_run_reports_no_drift() -> None:
    source = _context()
    await run_turn(default_registry, source, TURN)

    target = _context()
    report = await replay_run(
        default_registry, target, TURN, str(source.run_id), str(target.run_id)
    )

    assert report.ok is True
    assert [check.tool for check in report.checks] == list(default_plan().tools())
    assert all(check.equal for check in report.checks)


def test_remaining_pipeline_skips_completed_tools() -> None:
    assert remaining_pipeline(["parse_stuck_point"]) == [
        "retrieve_scenes",
        "suggest_from_scenes",
    ]
    assert remaining_pipeline(list(default_plan().tools())) == []


def test_compare_outputs_treats_the_writer_loosely() -> None:
    original = [
        {"next_node": "A", "corpus_reference": "W · SC", "reference_quote": "q1"},
        {"next_node": "B", "corpus_reference": "V · SC", "reference_quote": "q2"},
    ]
    reworded = [
        {"next_node": "A reworded", "corpus_reference": "W · SC", "reference_quote": "q1"},
        {"next_node": "B reworded", "corpus_reference": "V · SC", "reference_quote": "q9"},
    ]
    different_source = [
        {"next_node": "A", "corpus_reference": "OTHER · SC", "reference_quote": "q1"},
        {"next_node": "B", "corpus_reference": "V · SC", "reference_quote": "q2"},
    ]

    assert compare_outputs("suggest_from_scenes", original, reworded).equal is True
    assert compare_outputs("suggest_from_scenes", original, different_source).equal is False
    assert compare_outputs("suggest_from_scenes", original, original[:1]).equal is False


def test_compare_outputs_is_exact_for_retrieval() -> None:
    hits = [{"scene_id": "w:1", "score": 0.9}, {"scene_id": "w:2", "score": 0.8}]

    assert compare_outputs("retrieve_scenes", hits, list(hits)).equal is True
    assert compare_outputs("retrieve_scenes", hits, list(reversed(hits))).equal is False


def test_compare_outputs_tolerates_free_text_parse_variance() -> None:
    original = {
        "genre": "Drama",
        "narrative_functions": ["relationship_turn"],
        "value_polarity": "mixed",
        "characters": [{"name": "Baoyu", "function": "protagonist"}],
        "constraints": ["no coincidence"],
        "current_node": "A",
        "desired_effect": "X",
        "stuck_question": "Q1",
        "story_state": "S",
    }
    reworded = {
        **original,
        "current_node": "A (reworded)",
        "desired_effect": "Y",
        "stuck_question": "Q2",
    }
    changed = {**original, "narrative_functions": ["escalation"]}

    assert compare_outputs("parse_stuck_point", original, reworded).equal is True
    assert compare_outputs("parse_stuck_point", original, changed).equal is False


async def test_replay_needs_a_source_with_steps() -> None:
    empty = str(RunLedger(SessionLocal).create_run("plot_turn").id)
    report = await replay_run(
        default_registry, _context(), TURN, empty, str(RunLedger(SessionLocal).create_run("x").id)
    )
    assert report.ok is False
    assert "no steps" in report.error


async def test_restore_ignores_failed_calls() -> None:
    ctx = _context()
    await default_registry.call(
        "parse_stuck_point", {"story_state": "s", "stuck_question": "q"}, ctx
    )
    await default_registry.call("update_stuck_point", {"changes": {}}, ctx)

    restored = restore_state(ctx.store.list_tool_calls(ctx.run_id), _scene_index())  # type: ignore[union-attr]

    assert restored.completed == ["parse_stuck_point"]
    assert restored.state.stuck is not None
