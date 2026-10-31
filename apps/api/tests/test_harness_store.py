import pytest

from canonguard.db.session import SessionLocal
from canonguard.harness.store import ThreadStore
from canonguard.runs.ledger import RunLedger


@pytest.fixture()
def store() -> ThreadStore:
    return ThreadStore(SessionLocal)


def test_thread_and_story_state_round_trip(store: ThreadStore) -> None:
    state = store.create_story_state(
        title="第一幕",
        source_text="宝玉在灯下捏着旧帕子。",
        language="zh",
        characters=[{"name": "宝玉", "function": "protagonist", "evidence": []}],
    )
    thread = store.create_thread(title="宝玉黛玉", story_id=state.id)

    fetched = store.get_thread(thread.id)
    assert fetched is not None
    assert fetched.title == "宝玉黛玉"
    assert fetched.story_id == state.id
    assert fetched.archived is False


def test_messages_get_gapless_increasing_sequence(store: ThreadStore) -> None:
    thread = store.create_thread(title="t")
    first = store.append_message(thread.id, "user", "卡住了")
    second = store.append_message(thread.id, "assistant", "先看先例", payload={"suggestions": 3})
    third = store.append_message(thread.id, "user", "第二条改一下")

    assert [first.seq, second.seq, third.seq] == [1, 2, 3]
    stored = store.list_messages(thread.id)
    assert [message.content for message in stored] == ["卡住了", "先看先例", "第二条改一下"]
    assert stored[1].payload == {"suggestions": 3}


def test_message_limit_returns_the_most_recent_window(store: ThreadStore) -> None:
    thread = store.create_thread()
    for index in range(5):
        store.append_message(thread.id, "user", f"m{index}")
    tail = store.list_messages(thread.id, limit=3)
    assert [message.seq for message in tail] == [3, 4, 5]
    assert [message.content for message in tail] == ["m2", "m3", "m4"]


def test_message_requires_an_existing_thread(store: ThreadStore) -> None:
    missing = "0f2b1b3a-0000-4000-8000-000000000000"
    assert store.get_thread(missing) is None
    with pytest.raises(KeyError):
        store.append_message(missing, "user", "orphan")


def test_active_stuck_can_be_edited_in_place(store: ThreadStore) -> None:
    thread = store.create_thread(active_stuck={"stuck_question": "原问题"})
    store.set_active_stuck(thread.id, {"stuck_question": "改后的问题"})

    stored = store.get_thread(thread.id)
    assert stored is not None
    assert stored.active_stuck == {"stuck_question": "改后的问题"}


def test_archived_threads_leave_the_default_list(store: ThreadStore) -> None:
    keep = store.create_thread(title="keep")
    drop = store.create_thread(title="drop")
    store.archive_thread(drop.id)

    assert [thread.id for thread in store.list_threads()] == [keep.id]
    assert {thread.id for thread in store.list_threads(include_archived=True)} == {keep.id, drop.id}


def test_tool_calls_are_recorded_in_order(store: ThreadStore) -> None:
    run = RunLedger(SessionLocal).create_run("plot_suggest").id
    parse = store.record_tool_call(run, "parse_stuck_point", {"question": "q"})
    store.finish_tool_call(parse.id, output_digest="StuckPoint(characters=2)")
    retrieve = store.record_tool_call(run, "retrieve_precedents", {"top_k": 5})
    store.finish_tool_call(retrieve.id, status="failed", error="index missing")

    calls = store.list_tool_calls(run)
    assert [call.name for call in calls] == ["parse_stuck_point", "retrieve_precedents"]
    assert calls[0].status == "succeeded"
    assert calls[0].finished_at is not None
    assert calls[1].status == "failed"
    assert calls[1].error == "index missing"


def test_story_facts_are_replaced_not_duplicated(store: ThreadStore) -> None:
    state = store.create_story_state(title="s")
    store.replace_story_facts(
        state.id,
        [
            {"subject": "宝玉", "predicate": "DEPENDS_ON", "object": "袭人"},
            {"subject": "宝玉", "predicate": "LOVES", "object": "黛玉"},
        ],
    )
    replaced = store.replace_story_facts(
        state.id,
        [{"subject": "宝玉", "predicate": "SUPPORTS", "object": "袭人"}],
    )

    assert replaced == 1
    facts = store.list_story_facts(state.id)
    assert [(fact.subject, fact.predicate, fact.object) for fact in facts] == [
        ("宝玉", "SUPPORTS", "袭人")
    ]


def test_feedback_can_be_filtered_by_thread(store: ThreadStore) -> None:
    thread = store.create_thread()
    store.record_feedback("walk#61|next", "accept", thread_id=thread.id)
    store.record_feedback(
        "walk#61|other",
        "reject",
        thread_id=thread.id,
        reason_code="character_mismatch",
        note="不是恋人",
    )
    store.record_feedback("elsewhere", "accept")

    scoped = store.list_feedback(thread_id=thread.id)
    assert [item.decision for item in scoped] == ["accept", "reject"]
    assert scoped[1].reason_code == "character_mismatch"
    assert scoped[1].note == "不是恋人"
    assert len(store.list_feedback()) == 3


def test_runs_can_be_linked_to_a_thread(store: ThreadStore) -> None:
    thread = store.create_thread(title="linked")
    ledger = RunLedger(SessionLocal)
    run = ledger.create_run("plot_suggest", thread_id=thread.id)
    ledger.mark_running(run.id)
    ledger.finish_run(run.id, "succeeded")

    assert run.thread_id == thread.id
