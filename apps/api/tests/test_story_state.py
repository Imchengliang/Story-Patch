import json

from canonguard.db.session import SessionLocal
from canonguard.harness.store import ThreadStore
from canonguard.llm.gateway import RawCompletion, RoleConfig, StructuredGateway
from canonguard.plot.raw_suggest import generate_raw_suggestions
from canonguard.plot.scene_index import SceneHit, SceneUnit
from canonguard.plot.schemas import StuckPoint
from canonguard.plot.story_kg import StoryFact
from canonguard.plot.story_state import StoryStateService


class FakeBackend:
    def __init__(self, facts: list[str], fail: bool = False) -> None:
        self.facts = facts
        self.fail = fail
        self.ingested: list[tuple[str, str]] = []

    async def ingest(self, name: str, text: str) -> None:
        self.ingested.append((name, text))

    async def search(self, query: str, num_results: int = 10) -> list[StoryFact]:
        if self.fail:
            raise RuntimeError("neo4j down")
        return [
            StoryFact(
                fact=fact,
                name=f"fact-{index}",
                source_node_uuid="s",
                target_node_uuid="t",
                valid_at=None,
                invalid_at=None,
            )
            for index, fact in enumerate(self.facts[:num_results])
        ]


def _service(backend: FakeBackend) -> tuple[StoryStateService, ThreadStore]:
    store = ThreadStore(SessionLocal)
    return StoryStateService(store, backend_factory=lambda group_id: backend), store


async def test_ingest_mirrors_facts_and_remembers_the_group() -> None:
    backend = FakeBackend(["宝玉 依赖 袭人", "宝玉 爱慕 黛玉"])
    service, store = _service(backend)
    state = store.create_story_state(title="草稿", source_text="宝玉与黛玉在灯下说话。")

    result = await service.ingest_story(state.id)

    assert result["facts"] == 2
    assert backend.ingested[0][0] == f"story-{state.id}"
    stored = store.get_story_state(state.id)
    assert stored is not None and stored.kg_group_id == f"story-{state.id}"
    assert [fact.source_span for fact in store.list_story_facts(state.id)] == [
        "宝玉 依赖 袭人",
        "宝玉 爱慕 黛玉",
    ]


async def test_empty_draft_is_not_ingested() -> None:
    backend = FakeBackend([])
    service, store = _service(backend)
    state = store.create_story_state(title="空", source_text="   ")

    result = await service.ingest_story(state.id)

    assert result["facts"] == 0
    assert backend.ingested == []


async def test_facts_for_reads_the_graph_when_available() -> None:
    backend = FakeBackend(["宝玉 爱慕 黛玉"])
    service, store = _service(backend)
    state = store.create_story_state(title="草稿", source_text="宝玉与黛玉在灯下说话。")
    await service.ingest_story(state.id)

    facts = await service.facts_for(state.id, "黛玉 宝玉 关系")

    assert facts == ["宝玉 爱慕 黛玉"]


async def test_facts_for_falls_back_to_the_mirror_when_the_graph_is_down() -> None:
    backend = FakeBackend(["宝玉 依赖 袭人"], fail=False)
    service, store = _service(backend)
    state = store.create_story_state(title="草稿", source_text="宝玉与袭人说话。")
    await service.ingest_story(state.id)

    backend.fail = True
    facts = await service.facts_for(state.id, "袭人 宝玉")

    assert facts == ["宝玉 依赖 袭人"]


class CapturingCompleter:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def __call__(
        self, model: str, messages: list[dict[str, str]], config: RoleConfig
    ) -> RawCompletion:
        self.messages = messages
        payload = {
            "suggestions": [
                {
                    "precedent_index": index,
                    "next_node": f"Beat {index}.",
                    "character_behavior_logic": "He acts.",
                    "emotional_tone": "restrained",
                    "transfer_rationale": "Same structure.",
                    "reference_quote": "q1",
                    "fit_score": 0.8,
                    "novelty_score": 0.6,
                }
                for index in (1, 2, 3)
            ]
        }
        return RawCompletion(content=json.dumps(payload), model=model)


async def test_story_facts_reach_the_writer_prompt() -> None:
    completer = CapturingCompleter()
    gateway = StructuredGateway(
        roles={"writer": RoleConfig(model="fake/writer")}, completer=completer
    )
    scene = SceneUnit(
        scene_id="w:1",
        work_id="w",
        work_title="W",
        language="zh",
        genre="Drama",
        scene_no=1,
        heading="SC",
        text="q1 宝玉把帕子塞进袖子里。",
    )
    stuck = StuckPoint(story_state="草稿", stuck_question="下一步？")

    await generate_raw_suggestions(
        gateway,
        stuck,
        [SceneHit(scene=scene, score=1.0, dense=1.0, lexical=0.0)],
        story_facts=["宝玉 依赖 袭人"],
    )

    user = completer.messages[1]["content"]
    assert "Known facts from the writer's draft" in user
    assert "宝玉 依赖 袭人" in user
