"""Budgeted, explainable context assembly for conversation turns.

The compiler is deliberately boring: fixed sections, fixed priorities, a fixed
token estimate, and an explicit report of what was trimmed or dropped. Multi-turn
conversation without that discipline is how local runs silently blow the budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from canonguard.plot.scene_index import SceneHit, scene_excerpt
from canonguard.plot.schemas import StuckPoint

_CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")
_SCENE_SPLIT = re.compile(r"\n\s*\n")
_SCENE_HEADING = re.compile(
    r"^\s*(?:场景|第[0-9一二三四五六七八九十百]+场|内景|外景|INT\.|EXT\.|[A-Z0-9]+、)"
)

SECTION_PRIORITY: dict[str, int] = {
    "active_stuck": 1,
    "story_bible": 2,
    "current_scene": 3,
    "last_turns": 4,
    "precedents": 5,
    "feedback": 6,
}

SECTION_SHARE: dict[str, float] = {
    "active_stuck": 0.10,
    "story_bible": 0.20,
    "current_scene": 0.25,
    "last_turns": 0.20,
    "precedents": 0.15,
    "feedback": 0.10,
}

PROTECTED_PRIORITY = 2
MAX_FACTS = 12
MAX_SCENE_BLOCKS = 2
MAX_RECENT_MESSAGES = 6


def estimate_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate: CJK ~1 token/char, latin ~4 chars/token."""
    cjk = len(_CJK.findall(text))
    return cjk + (len(text) - cjk + 3) // 4


@dataclass(frozen=True)
class ContextSection:
    key: str
    priority: int
    tokens: int
    text: str


@dataclass(frozen=True)
class CompiledContext:
    sections: tuple[ContextSection, ...]
    total_tokens: int
    budget: int
    dropped: tuple[str, ...]
    trimmed: tuple[str, ...]
    overflow: bool = False

    def as_prompt(self) -> str:
        return "\n\n".join(f"[{section.key.upper()}]\n{section.text}" for section in self.sections)


@dataclass(frozen=True)
class MessageBrief:
    role: str
    content: str


@dataclass(frozen=True)
class PrecedentBrief:
    work_title: str
    scene_heading: str
    characters: tuple[str, ...] = ()
    excerpt: str = ""

    @classmethod
    def from_scene(cls, hit: SceneHit) -> PrecedentBrief:
        return cls(
            work_title=hit.scene.work_title,
            scene_heading=hit.scene.heading,
            characters=hit.scene.characters,
            excerpt=scene_excerpt(hit.scene, max_chars=400),
        )


@dataclass(frozen=True)
class ThreadSnapshot:
    language: str = "unknown"
    characters: tuple[dict[str, Any], ...] = ()
    facts: tuple[dict[str, Any], ...] = ()
    draft_text: str = ""
    stuck: StuckPoint | None = None
    messages: tuple[MessageBrief, ...] = ()
    precedents: tuple[PrecedentBrief, ...] = ()
    feedback: tuple[dict[str, Any], ...] = ()


def _truncate(text: str, tokens: int) -> str:
    if estimate_tokens(text) <= tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= tokens:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + " …"


def _fact_relevance(fact: dict[str, Any], names: set[str]) -> int:
    return sum(1 for key in ("subject", "object") if str(fact.get(key, "")) in names)


def _render_stuck(snapshot: ThreadSnapshot) -> str:
    stuck = snapshot.stuck
    if stuck is None:
        return ""
    lines = [
        f"question: {stuck.stuck_question}",
        f"current node: {stuck.current_node}",
        f"genre: {stuck.genre or '-'}",
        f"desired effect: {stuck.desired_effect or '-'}",
        f"narrative functions: {', '.join(stuck.narrative_functions) or '-'}",
        f"value polarity: {stuck.value_polarity}",
    ]
    if stuck.constraints:
        lines.append("constraints: " + " | ".join(stuck.constraints))
    if stuck.characters:
        lines.append(
            "characters: " + ", ".join(f"{item.name}({item.function})" for item in stuck.characters)
        )
    return "\n".join(lines)


def _render_bible(snapshot: ThreadSnapshot) -> str:
    names = {item.name for item in (snapshot.stuck.characters if snapshot.stuck else [])}
    facts = sorted(
        snapshot.facts,
        key=lambda fact: (-_fact_relevance(fact, names), str(fact.get("subject", ""))),
    )[:MAX_FACTS]
    lines: list[str] = []
    if snapshot.characters:
        lines.append("characters:")
        for character in snapshot.characters:
            evidence = character.get("evidence") or []
            suffix = f" — evidence: {'; '.join(map(str, evidence[:2]))}" if evidence else ""
            lines.append(
                f"- {character.get('name')} ({character.get('function', 'other')}){suffix}"
            )
    if facts:
        lines.append("relations:")
        for fact in facts:
            lines.append(f"- {fact.get('subject')} {fact.get('predicate')} {fact.get('object')}")
    return "\n".join(lines)


def _render_scene(snapshot: ThreadSnapshot) -> str:
    text = snapshot.draft_text.strip()
    if not text:
        return ""
    blocks = [block.strip() for block in _SCENE_SPLIT.split(text) if block.strip()]
    if len(blocks) <= 1:
        blocks = [block.strip() for block in _SCENE_HEADING.split(text) if block.strip()]
    return "\n\n".join(blocks[-MAX_SCENE_BLOCKS:])


def _render_turns(snapshot: ThreadSnapshot) -> str:
    recent = snapshot.messages[-MAX_RECENT_MESSAGES:]
    return "\n".join(f"{message.role}: {message.content}" for message in recent)


def _render_precedents(snapshot: ThreadSnapshot) -> str:
    lines: list[str] = []
    for index, precedent in enumerate(snapshot.precedents, start=1):
        characters = ", ".join(precedent.characters[:4]) or "-"
        lines.append(
            f"[{index}] {precedent.work_title} | {precedent.scene_heading}\n"
            f"    characters: {characters}\n"
            f"    excerpt: {precedent.excerpt}"
        )
    return "\n".join(lines)


def _render_feedback(snapshot: ThreadSnapshot) -> str:
    if not snapshot.feedback:
        return ""
    decisions: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for record in snapshot.feedback:
        decision = str(record.get("decision", "unknown"))
        decisions[decision] = decisions.get(decision, 0) + 1
        reason = record.get("reason_code")
        if reason:
            reasons[str(reason)] = reasons.get(str(reason), 0) + 1
    summary = " · ".join(f"{key} {count}" for key, count in sorted(decisions.items()))
    if reasons:
        summary += "\nrejected because: " + ", ".join(
            f"{reason} ×{count}" for reason, count in sorted(reasons.items())
        )
    return summary


_BUILDERS = {
    "active_stuck": _render_stuck,
    "story_bible": _render_bible,
    "current_scene": _render_scene,
    "last_turns": _render_turns,
    "precedents": _render_precedents,
    "feedback": _render_feedback,
}


def compile_context(snapshot: ThreadSnapshot, budget: int) -> CompiledContext:
    """Fit the thread into `budget` tokens, keeping the highest-priority sections whole."""
    if budget <= 0:
        return CompiledContext(sections=(), total_tokens=0, budget=budget, dropped=(), trimmed=())

    ordered = sorted(SECTION_PRIORITY, key=lambda key: SECTION_PRIORITY[key])
    full: dict[str, str] = {}
    for key in ordered:
        text = _BUILDERS[key](snapshot).strip()
        if text:
            full[key] = text

    remaining = budget
    allocated: dict[str, int] = {}
    for key in ordered:
        if key not in full:
            continue
        cap = max(1, int(budget * SECTION_SHARE[key]))
        take = min(estimate_tokens(full[key]), cap, remaining)
        allocated[key] = take
        remaining -= take

    for key in ordered:
        if remaining <= 0 or key not in allocated:
            continue
        deficit = estimate_tokens(full[key]) - allocated[key]
        if deficit <= 0:
            continue
        give = min(deficit, remaining)
        allocated[key] += give
        remaining -= give

    dropped: list[str] = []
    trimmed: list[str] = []
    sections: list[ContextSection] = []
    for key in ordered:
        if key not in allocated:
            continue
        tokens = allocated[key]
        if tokens <= 0:
            dropped.append(key)
            continue
        text = full[key]
        # The stuck point and the story bible are never cut mid-sentence: the
        # reconciliation loop below pays for them by dropping lower sections instead.
        if estimate_tokens(text) > tokens and SECTION_PRIORITY[key] > PROTECTED_PRIORITY:
            text = _truncate(text, tokens)
            trimmed.append(key)
        sections.append(
            ContextSection(
                key=key,
                priority=SECTION_PRIORITY[key],
                tokens=estimate_tokens(text),
                text=text,
            )
        )

    total = sum(section.tokens for section in sections)
    while total > budget and len(sections) > 1:
        lowest = max(sections, key=lambda section: section.priority)
        sections.remove(lowest)
        dropped.append(lowest.key)
        if lowest.key in trimmed:
            trimmed.remove(lowest.key)
        total = sum(section.tokens for section in sections)

    return CompiledContext(
        sections=tuple(sections),
        total_tokens=total,
        budget=budget,
        dropped=tuple(dropped),
        trimmed=tuple(dict.fromkeys(trimmed)),
        overflow=total > budget,
    )
