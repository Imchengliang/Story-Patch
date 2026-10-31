from canonguard.harness.context import (
    MAX_FACTS,
    MAX_RECENT_MESSAGES,
    MessageBrief,
    PrecedentBrief,
    ThreadSnapshot,
    compile_context,
    estimate_tokens,
)
from canonguard.plot.schemas import StuckCharacter, StuckPoint


def _stuck() -> StuckPoint:
    return StuckPoint(
        story_state="宝玉在灯下捏着旧帕子。",
        stuck_question="不想马上和解，下一步怎么走？",
        genre="Drama",
        current_node="黛玉摔帕子，宝玉接住。",
        constraints=["不能靠巧合"],
        desired_effect="关系前进一步",
        narrative_functions=["relationship_turn"],
        characters=[StuckCharacter(name="宝玉", function="protagonist")],
    )


def _precedent(index: int = 1) -> PrecedentBrief:
    return PrecedentBrief(
        work_title=f"Work {index}",
        scene_heading=f"SC {index}",
        characters=("Landon", "Jamie"),
        excerpt=f"excerpt {index}",
    )


def _snapshot(**overrides: object) -> ThreadSnapshot:
    base: dict[str, object] = {
        "language": "zh",
        "characters": (
            {"name": "宝玉", "function": "protagonist", "evidence": ["宝玉-DEPENDS_ON-袭人"]},
            {"name": "黛玉", "function": "love_interest", "evidence": []},
        ),
        "facts": (
            {"subject": "宝玉", "predicate": "LOVES", "object": "黛玉"},
            {"subject": "贾政", "predicate": "PUNISHES", "object": "宝玉"},
        ),
        "draft_text": "场景一\n\n宝玉进来。\n\n场景二\n\n黛玉不说话。",
        "stuck": _stuck(),
        "messages": (
            MessageBrief(role="user", content="卡住了"),
            MessageBrief(role="assistant", content="先看先例"),
        ),
        "precedents": (_precedent(1), _precedent(2)),
        "feedback": (
            {"decision": "accept"},
            {"decision": "reject", "reason_code": "character_mismatch"},
            {"decision": "reject", "reason_code": "character_mismatch"},
        ),
    }
    base.update(overrides)
    return ThreadSnapshot(**base)  # type: ignore[arg-type]


def test_estimate_tokens_counts_cjk_per_character() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("宝玉黛玉") == 4
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("宝玉 abcd") == 4


def test_generous_budget_keeps_every_section_in_priority_order() -> None:
    compiled = compile_context(_snapshot(), budget=4000)
    assert compiled.dropped == ()
    assert [section.key for section in compiled.sections] == [
        "active_stuck",
        "story_bible",
        "current_scene",
        "last_turns",
        "precedents",
        "feedback",
    ]
    assert compiled.total_tokens <= compiled.budget
    prompt = compiled.as_prompt()
    assert "[ACTIVE_STUCK]" in prompt
    assert "excerpt 1" in prompt


def test_tight_budget_drops_the_lowest_priority_sections_first() -> None:
    compiled = compile_context(_snapshot(), budget=170)
    keys = {section.key for section in compiled.sections}
    assert "active_stuck" in keys
    assert "feedback" not in keys
    assert compiled.dropped == ("feedback",)
    assert compiled.total_tokens <= 170
    assert compiled.overflow is False


def test_protected_sections_report_overflow_instead_of_being_cut() -> None:
    compiled = compile_context(_snapshot(), budget=60)
    assert [section.key for section in compiled.sections] == ["active_stuck"]
    assert not compiled.sections[0].text.endswith("…")
    assert compiled.overflow is True


def test_stuck_point_is_never_cut_mid_sentence() -> None:
    compiled = compile_context(_snapshot(), budget=40)
    stuck = next(section for section in compiled.sections if section.key == "active_stuck")
    assert stuck.text.startswith("question:")
    assert not stuck.text.endswith("…")


def test_unused_budget_flows_to_sections_that_need_it() -> None:
    long_precedents = tuple(_precedent(index) for index in range(1, 6))
    lean = _snapshot(facts=(), messages=(), feedback=(), draft_text="", precedents=long_precedents)
    compiled = compile_context(lean, budget=600)
    kept = {section.key: section for section in compiled.sections}
    assert kept["precedents"].tokens > 80


def test_current_scene_keeps_the_last_two_blocks() -> None:
    compiled = compile_context(_snapshot(), budget=4000)
    scene = next(section for section in compiled.sections if section.key == "current_scene")
    assert "场景一" not in scene.text
    assert "黛玉不说话。" in scene.text


def test_recent_messages_keep_order_and_window() -> None:
    many = tuple(
        MessageBrief(role="user", content=f"m{index}") for index in range(MAX_RECENT_MESSAGES + 3)
    )
    compiled = compile_context(_snapshot(messages=many), budget=4000)
    turns = next(section for section in compiled.sections if section.key == "last_turns")
    assert turns.text.splitlines() == [f"user: m{index}" for index in range(3, 9)]


def test_story_bible_ranks_facts_by_relevance_and_caps_them() -> None:
    facts = tuple(
        {
            "subject": "宝玉" if index % 2 == 0 else f"路人{index}",
            "predicate": "MEETS",
            "object": f"角色{index}",
        }
        for index in range(MAX_FACTS + 4)
    )
    compiled = compile_context(_snapshot(facts=facts), budget=4000)
    lines = next(s for s in compiled.sections if s.key == "story_bible").text.splitlines()
    relations = [line[2:] for line in lines[lines.index("relations:") + 1 :]]

    assert len(relations) == MAX_FACTS
    assert relations[0].startswith("宝玉 MEETS")
    # 16 facts, 8 of them about 宝玉: the relevance sort keeps all 8 before capping at 12
    assert sum(1 for line in relations if line.startswith("宝玉")) == 8


def test_feedback_section_aggregates_decisions_and_reasons() -> None:
    compiled = compile_context(_snapshot(), budget=4000)
    feedback = next(section for section in compiled.sections if section.key == "feedback")
    assert "accept 1" in feedback.text
    assert "reject 2" in feedback.text
    assert "character_mismatch ×2" in feedback.text


def test_empty_thread_compiles_to_nothing() -> None:
    assert compile_context(ThreadSnapshot(), budget=500).sections == ()
    assert compile_context(_snapshot(), budget=0).total_tokens == 0
