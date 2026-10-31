import json
from typing import Any

import pytest

from canonguard.db.session import SessionLocal
from canonguard.harness.store import ThreadStore
from canonguard.harness.tools import ToolContext, UnknownToolError, default_registry
from canonguard.llm.gateway import RawCompletion, RoleConfig, StructuredGateway
from canonguard.plot.aliases import parse_alias_table
from canonguard.plot.schemas import StuckPoint
from canonguard.runs.ledger import RunLedger

STUCK_DRAFT = {
    "genre": "Drama",
    "characters": [{"name": "宝玉", "function": "protagonist"}],
    "current_node": "黛玉摔帕子，宝玉接住。",
    "stuck_question": "不想马上和解，下一步怎么走？",
    "constraints": ["不能靠巧合"],
    "desired_effect": "关系前进一步",
    "narrative_functions": ["relationship_turn"],
    "value_polarity": "mixed",
}


class ScriptedCompleter:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.roles: list[str] = []

    async def __call__(
        self, model: str, messages: list[dict[str, str]], config: RoleConfig
    ) -> RawCompletion:
        self.roles.append(model)
        return RawCompletion(content=json.dumps(self.payload), model=model)


@pytest.fixture()
def ctx() -> ToolContext:
    run = RunLedger(SessionLocal).create_run("plot_suggest").id
    return ToolContext(
        gateway=StructuredGateway(
            roles={
                role: RoleConfig(model="fake/model") for role in ("extractor", "judge", "writer")
            },
            completer=ScriptedCompleter(STUCK_DRAFT),
        ),
        aliases=parse_alias_table({}),
        store=ThreadStore(SessionLocal),
        run_id=run,
    )


def test_registry_exposes_a_closed_tool_set() -> None:
    assert default_registry.names == (
        "parse_stuck_point",
        "update_stuck_point",
        "retrieve_scenes",
        "suggest_from_scenes",
        "expand_beats",
        "record_feedback",
    )
    first = default_registry.spec()[0]
    assert {"name", "description", "idempotent", "input_schema"} <= set(first)
    assert "story_state" in first["input_schema"]["properties"]
    assert default_registry.get("retrieve_scenes").idempotent is True
    assert default_registry.get("record_feedback").idempotent is False


async def test_unknown_tool_raises_and_records(ctx: ToolContext) -> None:
    with pytest.raises(UnknownToolError):
        default_registry.get("drop_everything")

    result = await default_registry.call("drop_everything", {}, ctx)
    assert result.ok is False
    assert result.error == "unknown tool: drop_everything"

    calls = ctx.store.list_tool_calls(ctx.run_id)  # type: ignore[union-attr]
    assert [(call.name, call.status) for call in calls] == [("drop_everything", "failed")]


async def test_invalid_arguments_never_reach_the_tool(ctx: ToolContext) -> None:
    result = await default_registry.call("parse_stuck_point", {"story_state": ""}, ctx)
    assert result.ok is False
    assert result.error.startswith("invalid arguments for parse_stuck_point")
    (call,) = ctx.store.list_tool_calls(ctx.run_id)  # type: ignore[union-attr]
    assert call.status == "failed"
    assert call.input["story_state"] == ""


async def test_arguments_may_arrive_as_a_json_string(ctx: ToolContext) -> None:
    stuck = StuckPoint(story_state="草稿", stuck_question="原问题")
    arguments = json.dumps({"stuck": stuck.model_dump(), "changes": {"genre": "Family"}})

    result = await default_registry.call("update_stuck_point", arguments, ctx)

    assert result.ok is True
    assert isinstance(result.value, StuckPoint)
    assert result.value.genre == "Family"


async def test_malformed_json_arguments_are_reported(ctx: ToolContext) -> None:
    result = await default_registry.call("update_stuck_point", "{not json", ctx)
    assert result.ok is False
    assert "not JSON" in result.error


async def test_parse_stuck_point_records_a_digest(ctx: ToolContext) -> None:
    result = await default_registry.call(
        "parse_stuck_point",
        {"story_state": "宝玉在灯下捏着旧帕子。", "stuck_question": "下一步？"},
        ctx,
    )

    assert result.ok is True
    assert isinstance(result.value, StuckPoint)
    assert result.digest == "1 characters · functions: relationship_turn"
    (call,) = ctx.store.list_tool_calls(ctx.run_id)  # type: ignore[union-attr]
    assert (call.name, call.status, call.output_digest) == (
        "parse_stuck_point",
        "succeeded",
        result.digest,
    )


async def test_update_stuck_point_rejects_non_editable_fields(ctx: ToolContext) -> None:
    stuck = StuckPoint(story_state="草稿", stuck_question="问题")
    result = await default_registry.call(
        "update_stuck_point",
        {"stuck": stuck, "changes": {"story_state": "偷偷改掉正文"}},
        ctx,
    )
    assert result.ok is False
    assert "not editable" in result.error


async def test_record_feedback_persists_and_digests(ctx: ToolContext) -> None:
    result = await default_registry.call(
        "record_feedback",
        {
            "suggestion_ref": "walk#61|next",
            "decision": "reject",
            "reason_code": "character_mismatch",
        },
        ctx,
    )

    assert result.ok is True
    assert result.digest.startswith("stored feedback ")
    stored = ctx.store.list_feedback()  # type: ignore[union-attr]
    assert [(item.suggestion_ref, item.decision, item.reason_code) for item in stored] == [
        ("walk#61|next", "reject", "character_mismatch")
    ]


async def test_retrieve_scenes_reports_missing_services(ctx: ToolContext) -> None:
    stuck = StuckPoint(story_state="草稿", stuck_question="问题")
    result = await default_registry.call("retrieve_scenes", {"stuck": stuck}, ctx)

    assert result.ok is False
    assert "needs a scene index and an embedder" in result.error
    (call,) = ctx.store.list_tool_calls(ctx.run_id)  # type: ignore[union-attr]
    assert call.status == "failed"
    assert "stuck_question" in json.dumps(call.input)
