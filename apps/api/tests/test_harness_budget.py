import json
from typing import Any

from pydantic import BaseModel

from canonguard.db.session import SessionLocal
from canonguard.harness.budget import Budget, Usage, exceeded
from canonguard.harness.planner import default_plan
from canonguard.harness.recorder import RecordingGateway
from canonguard.harness.runtime import TurnInput, run_turn
from canonguard.harness.store import ThreadStore
from canonguard.harness.tools import ToolContext, default_registry
from canonguard.llm.gateway import LLMResult, RawCompletion, RoleConfig, StructuredGateway
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
        self.models: list[str] = []

    async def __call__(
        self, model: str, messages: list[dict[str, str]], config: RoleConfig
    ) -> RawCompletion:
        self.models.append(model)
        return RawCompletion(content=json.dumps(self.payloads[model.split("/")[-1]]), model=model)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


def _index() -> SceneIndex:
    unit = SceneUnit(
        scene_id="w:1",
        work_id="w",
        work_title="Work 1",
        language="zh",
        genre="Drama",
        scene_no=1,
        heading="SC 1",
        text="q1 宝玉把帕子塞进袖子里。",
        characters=("Baoyu",),
    )
    return SceneIndex([unit], [[1.0, 0.0, 0.0, 0.0]])


def _gateway() -> StructuredGateway:
    return StructuredGateway(
        roles={role: RoleConfig(model=f"fake/{role}") for role in ("extractor", "judge", "writer")},
        completer=RoleCompleter(
            {
                "extractor": STUCK_DRAFT,
                "judge": {"corrections": [], "notes": []},
                "writer": SUGGESTIONS,
            }
        ),
    )


def _context(run_id: str) -> ToolContext:
    return ToolContext(
        gateway=_gateway(),
        aliases=parse_alias_table({}),
        scene_index=_index(),
        embedder=FakeEmbedder(),
        store=ThreadStore(SessionLocal),
        run_id=run_id,
    )


def _new_run_id(task: str = "plot_turn") -> str:
    return str(RunLedger(SessionLocal).create_run(task).id)


TURN = TurnInput(story_state="Baoyu holds a handkerchief.", stuck_question="How do they move on?")


def test_exceeded_reports_tokens_and_cost() -> None:
    assert exceeded(Usage(prompt_tokens=10, completion_tokens=10), Budget(100, 0.0)) is None
    token_reason = exceeded(Usage(prompt_tokens=80, completion_tokens=40), Budget(100, 0.0))
    assert token_reason is not None and "budget_exceeded" in token_reason
    cost_reason = exceeded(Usage(cost_usd=0.02), Budget(0, 0.01))
    assert cost_reason is not None and "$0.0200" in cost_reason


class Payload(BaseModel):
    name: str = ""


async def test_recording_gateway_writes_every_call() -> None:
    recorded: list[tuple[str, LLMResult]] = []
    gateway = RecordingGateway(_gateway(), lambda role, result: recorded.append((role, result)))

    result = await gateway.complete("extractor", [{"role": "user", "content": "x"}], Payload)

    assert isinstance(result, LLMResult)
    assert [role for role, _ in recorded] == ["extractor"]
    assert recorded[0][1].model.endswith("/extractor")


async def test_budget_stops_the_run_and_names_the_reason() -> None:
    run_id = _new_run_id()
    ctx = _context(run_id)
    # the run already spent 120 tokens, so the first step must trip the limit
    RunLedger(SessionLocal).record_llm_call(
        run_id, "extractor", "fake/extractor", None, 80, 40, 0.0, 10.0
    )

    outcome = await run_turn(
        default_registry,
        ctx,
        TURN,
        budget=Budget(max_tokens=100, max_cost_usd=0.0),
    )

    assert outcome.ok is False
    assert "budget_exceeded" in outcome.error
    assert [step.tool for step in outcome.steps] == ["parse_stuck_point"]
    assert any(event == "budget" for event, _ in outcome.events)


async def test_budget_within_limits_completes_the_pipeline() -> None:
    run_id = _new_run_id()
    outcome = await run_turn(
        default_registry,
        _context(run_id),
        TURN,
        budget=Budget(max_tokens=10_000, max_cost_usd=0.0),
    )

    assert outcome.ok is True
    assert [step.tool for step in outcome.steps] == list(default_plan().tools())
    done = next(data for event, data in outcome.events if event == "done")
    assert done["usage"]["total_tokens"] == 0  # this fake context records nothing


async def test_usage_for_run_aggregates_recorded_calls() -> None:
    run_id = _new_run_id()
    store = ThreadStore(SessionLocal)
    ledger = RunLedger(SessionLocal)
    ledger.record_llm_call(run_id, "extractor", "m", None, 10, 5, 0.001, 1.0)
    ledger.record_llm_call(run_id, "writer", "m", None, 20, 30, 0.002, 1.0)

    usage = Usage.from_row(store.usage_for_run(run_id))

    assert usage.total_tokens == 65
    assert usage.calls == 2
    assert round(usage.cost_usd, 4) == 0.003
