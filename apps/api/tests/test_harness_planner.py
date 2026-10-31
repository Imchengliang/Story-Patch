import json

from canonguard.harness.planner import (
    MAX_PLAN_STEPS,
    Plan,
    PlanStep,
    build_plan,
    default_plan,
    sanitize_plan,
    should_plan,
)
from canonguard.harness.tools import default_registry
from canonguard.llm.gateway import RawCompletion, RoleConfig, StructuredGateway


class PlannerCompleter:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def __call__(
        self, model: str, messages: list[dict[str, str]], config: RoleConfig
    ) -> RawCompletion:
        content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return RawCompletion(content=content, model=model)


def _gateway(payload: object) -> StructuredGateway:
    return StructuredGateway(
        roles={"planner": RoleConfig(model="fake/planner")},
        completer=PlannerCompleter(payload),
    )


def test_default_plan_is_the_scene_pipeline() -> None:
    plan = default_plan()
    assert plan.tools() == ("parse_stuck_point", "retrieve_scenes", "suggest_from_scenes")
    assert plan.note == "default"


def test_plain_new_prompt_does_not_need_a_planner() -> None:
    assert should_plan("宝玉和黛玉吵完架，下一步怎么推进？", had_rejection=False) is False
    assert should_plan("黛玉把帕子摔在他手里", had_rejection=False) is False
    assert should_plan("再来一条", had_rejection=False) is True
    assert should_plan("第二条改成母亲视角", had_rejection=False) is True
    assert should_plan("继续", had_rejection=True) is True


def test_sanitize_drops_unknown_tools_and_falls_back_when_nothing_survives() -> None:
    plan = Plan(
        steps=[
            PlanStep(tool="parse_stuck_point"),
            PlanStep(tool="read_the_whole_corpus"),
        ]
    )
    assert sanitize_plan(plan, default_registry).tools() == ("parse_stuck_point",)

    hopeless = Plan(steps=[PlanStep(tool="make_coffee")])
    assert sanitize_plan(hopeless, default_registry).tools() == default_plan().tools()


def test_sanitize_truncates_overlong_plans() -> None:
    plan = Plan(steps=[PlanStep(tool="parse_stuck_point") for _ in range(MAX_PLAN_STEPS + 5)])
    assert len(sanitize_plan(plan, default_registry).steps) == MAX_PLAN_STEPS


async def test_planner_output_is_used_when_it_is_valid() -> None:
    payload = {
        "steps": [
            {"tool": "retrieve_scenes", "args": {"top_k": 3}, "reason": "只要三条先例"},
            {"tool": "suggest_from_scenes", "reason": "直接改建议"},
        ],
        "needs_user_input": False,
        "note": "retry with fewer precedents",
    }
    plan = await build_plan(_gateway(payload), default_registry, "再来三条", {})
    assert plan.tools() == ("retrieve_scenes", "suggest_from_scenes")
    assert plan.steps[0].args == {"top_k": 3}
    assert plan.note == "retry with fewer precedents"


async def test_unparsable_planner_output_falls_back_to_the_pipeline() -> None:
    plan = await build_plan(_gateway("this is not json"), default_registry, "再来三条", {})
    assert plan.tools() == default_plan().tools()


async def test_missing_planner_role_falls_back_instead_of_failing() -> None:
    gateway = StructuredGateway(roles={}, completer=PlannerCompleter({}))
    plan = await build_plan(gateway, default_registry, "换一批先例", {})
    assert plan.tools() == default_plan().tools()
