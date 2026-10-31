from typing import Literal

from pydantic import BaseModel, Field

NarrativeFunction = Literal[
    "setup",
    "inciting_incident",
    "escalation",
    "reveal",
    "reversal",
    "relationship_turn",
    "breather",
    "crisis",
    "climax",
    "resolution",
    "payoff",
    "other",
]
ValuePolarity = Literal["positive", "negative", "ironic", "mixed", "unclear"]
CharacterFunction = Literal[
    "protagonist",
    "antagonist",
    "ally",
    "mentor",
    "love_interest",
    "foil",
    "comic_relief",
    "other",
]


class PlotEvidence(BaseModel):
    scene_heading: str
    quote: str = Field(min_length=1)


class CharacterFunctionSpec(BaseModel):
    name: str
    function: CharacterFunction = "other"
    goal: str | None = None
    obstacle: str | None = None


class ValueShift(BaseModel):
    from_value: str = ""
    to_value: str = ""
    polarity: ValuePolarity = "unclear"
    description: str = ""


class PlotUnit(BaseModel):
    plot_unit_id: str
    work_title: str
    source_language: str = "unknown"
    scene_heading: str
    scene_order: int = Field(ge=1)
    genre: str = ""
    characters: list[CharacterFunctionSpec] = Field(default_factory=list)
    situation: str = ""
    trigger: str = ""
    goal: str = ""
    obstacle: str = ""
    conflict: str = ""
    turning_point: str = ""
    value_shift: ValueShift = Field(default_factory=ValueShift)
    outcome: str = ""
    emotional_tone: str = ""
    narrative_functions: list[NarrativeFunction] = Field(default_factory=list)
    tropes: list[str] = Field(default_factory=list)
    evidence: list[PlotEvidence] = Field(min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class StuckCharacter(BaseModel):
    name: str
    function: CharacterFunction = "other"


class StuckPoint(BaseModel):
    story_state: str = Field(min_length=1)
    genre: str = ""
    characters: list[StuckCharacter] = Field(default_factory=list)
    current_node: str = ""
    stuck_question: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    desired_effect: str = ""
    narrative_functions: list[NarrativeFunction] = Field(default_factory=list)
    value_polarity: ValuePolarity = "unclear"


class PlotSuggestion(BaseModel):
    next_node: str
    character_behavior_logic: str
    emotional_tone: str
    corpus_reference: str
    reference_quote: str | None = None
    transfer_rationale: str
    fit_score: float = Field(default=0.5, ge=0.0, le=1.0)
    novelty_score: float = Field(default=0.5, ge=0.0, le=1.0)


class Beat(BaseModel):
    index: int = Field(ge=1, le=3)
    next_node: str = Field(min_length=1)
    character_behavior_logic: str = ""
    emotional_tone: str = ""
    corpus_reference: str = ""
    reference_quote: str | None = None
    transfer_rationale: str = ""


class BeatSequence(BaseModel):
    suggestion_id: str
    beats: list[Beat] = Field(min_length=2, max_length=3)
    risk: str = ""
    still_unresolved: str = ""
