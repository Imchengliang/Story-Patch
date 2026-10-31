import asyncio
import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from canonguard.api import threads
from canonguard.db.session import SessionLocal
from canonguard.harness.store import ThreadStore
from canonguard.harness.tools import ToolContext
from canonguard.llm.gateway import RawCompletion, RoleConfig, StructuredGateway
from canonguard.main import app
from canonguard.plot.aliases import parse_alias_table
from canonguard.plot.scene_index import SceneIndex, SceneUnit

STUCK_DRAFT = {
    "genre": "Drama",
    "characters": [{"name": "Baoyu", "function": "protagonist"}],
    "current_node": "Baoyu holds the handkerchief.",
    "stuck_question": "How do they move on without reconciling?",
    "constraints": [],
    "desired_effect": "Advance the relationship",
    "narrative_functions": ["relationship_turn"],
    "value_polarity": "mixed",
}
SUGGESTIONS = {
    "suggestions": [
        {
            "precedent_index": index,
            "next_node": f"Beat {index}.",
            "character_behavior_logic": "He acts instead of explaining.",
            "emotional_tone": "restrained",
            "transfer_rationale": "Same negotiation structure.",
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


def _unit(index: int) -> SceneUnit:
    return SceneUnit(
        scene_id=f"w:{index}",
        work_id=f"w{index}",
        work_title=f"Work {index}",
        language="zh",
        genre="Drama",
        scene_no=index,
        heading=f"SC {index}",
        text=f"q{index} 宝玉把帕子塞进袖子里。",
        characters=("Baoyu",),
    )


@pytest.fixture()
def fake_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def build(run_id: str, thread_id: Any) -> ToolContext:
        return ToolContext(
            gateway=StructuredGateway(
                roles={role: RoleConfig(model=f"fake/{role}") for role in ("extractor", "writer")},
                completer=RoleCompleter(
                    {
                        "extractor": STUCK_DRAFT,
                        "writer": SUGGESTIONS,
                    }
                ),
            ),
            aliases=parse_alias_table({}),
            scene_index=SceneIndex(
                [_unit(1), _unit(2)], [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
            ),
            embedder=FakeEmbedder(),
            store=ThreadStore(SessionLocal),
            run_id=run_id,
            thread_id=thread_id,
        )

    monkeypatch.setattr(threads, "tool_context", build)


FIRST_TURN = {
    "content": "宝玉和黛玉吵完架，下一步怎么推进？",
    "story_state": "Baoyu holds an old handkerchief.",
    "stuck_question": "How do they move on without reconciling?",
    "genre": "Drama",
    "characters": ["Baoyu", "Daiyu"],
}


def _create_thread(client: TestClient) -> str:
    response = client.post(
        "/v1/threads", json={"title": "第一幕", "story_state": "Baoyu holds an old handkerchief."}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["story_id"] is not None
    return body["id"]


def test_create_and_list_threads(fake_context: None) -> None:
    with TestClient(app) as client:
        thread_id = _create_thread(client)
        listed = client.get("/v1/threads").json()

    assert [item["id"] for item in listed] == [thread_id]
    assert listed[0]["title"] == "第一幕"


def test_first_turn_without_a_stuck_point_is_rejected(fake_context: None) -> None:
    with TestClient(app) as client:
        thread_id = _create_thread(client)
        response = client.post(f"/v1/threads/{thread_id}/messages", json={"content": "继续"})

    assert response.status_code == 422
    assert "story_state and stuck_question" in response.json()["detail"]


def test_turn_streams_then_persists_an_assistant_message(fake_context: None) -> None:
    with TestClient(app) as client:
        thread_id = _create_thread(client)
        accepted = client.post(f"/v1/threads/{thread_id}/messages", json=FIRST_TURN)
        assert accepted.status_code == 202
        run_id = accepted.json()["run_id"]

        detail = client.get(f"/v1/threads/{thread_id}").json()
        events = client.get(f"/v1/threads/{thread_id}/events", params={"run_id": run_id})

    assert detail["last_run"]["status"] == "succeeded"
    roles = [message["role"] for message in detail["messages"]]
    assert roles == ["user", "assistant"]
    payload = detail["messages"][1]["payload"]
    assert len(payload["suggestions"]) == 3
    assert payload["plan"] == [
        "parse_stuck_point",
        "retrieve_scenes",
        "suggest_from_scenes",
    ]
    assert detail["thread"]["active_stuck"]["stuck_question"]
    # the buffer survives the run, so a late subscriber can replay the whole turn
    assert events.status_code == 200
    assert "event: plan" in events.text
    assert "event: done" in events.text


def test_follow_up_turn_reuses_the_stored_stuck_point(fake_context: None) -> None:
    with TestClient(app) as client:
        thread_id = _create_thread(client)
        client.post(f"/v1/threads/{thread_id}/messages", json=FIRST_TURN)
        second = client.post(
            f"/v1/threads/{thread_id}/messages", json={"content": "帕子这个物件还能怎么用？"}
        )
        assert second.status_code == 202
        detail = client.get(f"/v1/threads/{thread_id}").json()

    plans = [message["payload"]["plan"] for message in detail["messages"] if message["payload"]]
    assert plans[1] == ["retrieve_scenes", "suggest_from_scenes"]
    assert len(detail["messages"]) == 4


def test_stuck_point_can_be_patched_then_respected(fake_context: None) -> None:
    with TestClient(app) as client:
        thread_id = _create_thread(client)
        client.post(f"/v1/threads/{thread_id}/messages", json=FIRST_TURN)

        conflict = client.patch(f"/v1/threads/{thread_id}/stuck-point", json={})
        patched = client.patch(f"/v1/threads/{thread_id}/stuck-point", json={"genre": "Family"})
        detail = client.get(f"/v1/threads/{thread_id}").json()

    assert conflict.status_code == 422
    assert patched.json()["active_stuck"]["genre"] == "Family"
    assert detail["thread"]["active_stuck"]["genre"] == "Family"


def test_usage_endpoint_reports_costs_and_limits(fake_context: None) -> None:
    with TestClient(app) as client:
        thread_id = _create_thread(client)
        accepted = client.post(f"/v1/threads/{thread_id}/messages", json=FIRST_TURN)
        run_id = accepted.json()["run_id"]
        _ledger_record(run_id)
        usage = client.get(f"/v1/threads/{thread_id}/usage")

    assert usage.status_code == 200
    body = usage.json()
    assert body["thread"]["calls"] == 1
    assert body["thread"]["total_tokens"] == 30
    assert body["runs"][0]["run_id"] == run_id
    assert body["limits"]["max_tokens"] > 0


def _ledger_record(run_id: str) -> None:
    from canonguard.runs.ledger import RunLedger

    RunLedger(SessionLocal).record_llm_call(run_id, "writer", "fake/writer", None, 20, 10, 0.0, 5.0)


def test_unknown_thread_returns_404(fake_context: None) -> None:
    missing = "0f2b1b3a-0000-4000-8000-000000000000"
    with TestClient(app) as client:
        assert client.get(f"/v1/threads/{missing}").status_code == 404
        assert client.post(f"/v1/threads/{missing}/messages", json=FIRST_TURN).status_code == 404
        assert (
            client.get(f"/v1/threads/{missing}/events", params={"run_id": "x"}).status_code == 404
        )


def test_story_ingest_reports_mirrored_facts(
    fake_context: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeStory:
        async def ingest_story(self, story_id: Any) -> dict[str, Any]:
            return {"facts": 3, "group_id": "story-x"}

    monkeypatch.setattr(threads, "_story", FakeStory())
    with TestClient(app) as client:
        thread_id = _create_thread(client)
        response = client.post(f"/v1/threads/{thread_id}/story/ingest")

    assert response.status_code == 200
    assert response.json() == {"facts": 3, "group_id": "story-x"}


def test_story_ingest_requires_a_draft(fake_context: None) -> None:
    with TestClient(app) as client:
        created = client.post("/v1/threads", json={"title": "无稿"}).json()
        response = client.post(f"/v1/threads/{created['id']}/story/ingest")

    assert response.status_code == 409


def test_thread_archive_and_delete(fake_context: None) -> None:
    with TestClient(app) as client:
        thread_id = _create_thread(client)

        patched = client.patch(f"/v1/threads/{thread_id}", json={"archived": True})
        assert patched.status_code == 200
        assert patched.json()["archived"] is True
        assert all(item["id"] != thread_id for item in client.get("/v1/threads").json())
        assert any(
            item["id"] == thread_id
            for item in client.get("/v1/threads?include_archived=true").json()
        )

        deleted = client.delete(f"/v1/threads/{thread_id}")
        assert deleted.status_code == 204

        missing = client.patch(
            "/v1/threads/0f2b1b3a-0000-4000-8000-000000000000",
            json={"archived": True},
        )
        assert missing.status_code == 404


async def test_ingest_runs_in_background_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[object] = []

    async def slow_ingest(story_id: object) -> None:
        calls.append(story_id)
        started.set()
        await release.wait()

    monkeypatch.setattr(threads, "_story", SimpleNamespace(ingest_story=slow_ingest))
    story_id = uuid4()
    key = str(story_id)
    try:
        threads._start_ingest(story_id, "run-1")
        await asyncio.wait_for(started.wait(), timeout=1)
        first = threads._ingest_tasks[key]
        threads._start_ingest(story_id, "run-2")
        assert threads._ingest_tasks[key] is first
        assert len(calls) == 1
        release.set()
        await asyncio.sleep(0.01)
        assert key not in threads._ingest_tasks
    finally:
        release.set()
        threads._ingest_tasks.pop(key, None)
