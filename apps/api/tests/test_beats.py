from canonguard.harness.tools import default_registry
from canonguard.plot.beats import BeatDraft, bind_beats, build_beat_messages
from canonguard.plot.scene_index import SceneUnit
from canonguard.plot.schemas import PlotSuggestion, StuckPoint


def _scene() -> SceneUnit:
    return SceneUnit(
        scene_id="s1",
        work_id="w",
        work_title="Work",
        language="zh",
        genre="Drama",
        scene_no=1,
        heading="SC 1",
        text="宝玉把帕子塞进袖子里，没有说话。",
    )


def _stuck() -> StuckPoint:
    return StuckPoint(
        story_state="宝玉与黛玉刚吵完。",
        stuck_question="怎样让关系前进一步？",
        genre="Drama",
    )


def _suggestion() -> PlotSuggestion:
    return PlotSuggestion(
        next_node="他把帕子收起来。",
        character_behavior_logic="不解释。",
        emotional_tone="克制",
        corpus_reference="Work · SC 1",
        transfer_rationale="用动作替代对白。",
    )


def test_bind_beats_reindexes_and_drops_unverifiable_quotes() -> None:
    drafts = [
        BeatDraft(index=2, next_node="第二拍", reference_quote="宝玉把帕子塞进袖子里"),
        BeatDraft(index=1, next_node="第一拍", reference_quote="这句原文不存在"),
    ]

    beats = bind_beats(drafts, _scene())

    assert [beat.index for beat in beats] == [1, 2]
    assert beats[0].reference_quote is None
    assert beats[1].reference_quote == "宝玉把帕子塞进袖子里"
    assert beats[0].corpus_reference == "Work · SC 1"


def test_beat_prompt_includes_precedent_and_no_prose_rule() -> None:
    messages = build_beat_messages(_stuck(), _suggestion(), _scene())

    assert "Do not write finished prose or dialogue" in messages[0]["content"]
    assert "Work · SC 1" in messages[1]["content"]
    assert "宝玉把帕子塞进袖子里" in messages[1]["content"]


def test_expand_beats_is_registered() -> None:
    assert "expand_beats" in default_registry.names
