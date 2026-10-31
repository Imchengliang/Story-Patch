import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

import canonguard.api.plot as plot_api
from canonguard.api.plot import LlmChoice, _gateway_for_choice
from canonguard.db.models import LLMCall, ToolCall
from canonguard.db.models import SuggestionFeedback as FeedbackRow
from canonguard.db.session import SessionLocal
from canonguard.harness.store import ThreadStore
from canonguard.llm.gateway import (
    ModelEndpoint,
    RawCompletion,
    RoleConfig,
    StructuredGateway,
)
from canonguard.llm.providers import EndpointPair
from canonguard.main import app
from canonguard.plot.scene_index import SceneIndex, SceneUnit
from canonguard.runs.ledger import RunLedger


def test_custom_gateway_uses_request_endpoint() -> None:
    gateway, provider, model = _gateway_for_choice(
        LlmChoice(
            provider="custom",
            base_url="http://example.test/v1",
            model="my-model",
            api_key="secret",
        )
    )
    assert provider == "custom"
    assert model == "my-model"
    assert gateway.roles["writer"].api_base == "http://example.test/v1"
    assert gateway.roles["extractor"].api_key == "secret"


def test_custom_gateway_defaults_to_local_key() -> None:
    gateway, _, _ = _gateway_for_choice(
        LlmChoice(provider="custom", base_url="http://example.test/v1", model="m")
    )
    assert gateway.roles["extractor"].api_key == "local"


def test_custom_requires_base_url_and_model() -> None:
    with pytest.raises(HTTPException):
        _gateway_for_choice(LlmChoice(provider="custom"))


def test_missing_provider_config_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("canonguard.api.plot.load_endpoints", lambda: EndpointPair(None, None))
    with pytest.raises(HTTPException):
        _gateway_for_choice(LlmChoice(provider="qwen"))
    with pytest.raises(HTTPException):
        _gateway_for_choice(LlmChoice(provider="deepseek"))


def test_auto_prefers_deepseek_then_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plot_api, "_gateway", lambda: object())
    pair = EndpointPair(
        qwen=ModelEndpoint(name="qwen", model="openai/qwen"),
        deepseek=ModelEndpoint(name="deepseek", model="openai/deepseek-flash"),
    )
    monkeypatch.setattr(plot_api, "load_endpoints", lambda: pair)
    monkeypatch.setattr(
        plot_api, "load_model_endpoints", lambda preference="deepseek": pair.ordered(preference)
    )

    _, provider, model = _gateway_for_choice(LlmChoice(provider="auto"))

    assert provider == "auto"
    assert model == "deepseek-flash → qwen"


def test_stream_emits_stage_result_done(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_events(
        request: object, story_facts: object = None, story_status: str = "absent"
    ):
        yield "stage", {"stage": "parse", "message": "解析卡点…"}
        yield "result", {"provider": "qwen", "model": "m"}
        yield "done", {}

    async def no_facts(request: object, background: object) -> tuple[list[str], str]:
        return [], "absent"

    monkeypatch.setattr(plot_api, "_suggest_events", fake_events)
    monkeypatch.setattr(plot_api, "_story_facts_for", no_facts)
    client = TestClient(app)
    with client.stream(
        "POST",
        "/v1/plot/suggest/stream",
        json={"story_state": "s", "stuck_question": "q"},
    ) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: stage" in body
    assert "event: result" in body
    assert "event: done" in body


def test_feedback_writes_table_row_with_thread_and_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = ThreadStore(SessionLocal)
    thread = store.create_thread(title="feedback test")
    run = RunLedger(SessionLocal).create_run("plot_turn", thread_id=thread.id)
    monkeypatch.setattr(plot_api, "_feedback_path", lambda: tmp_path / "feedback.jsonl")

    response = TestClient(app).post(
        "/v1/plot/feedback",
        json={
            "decision": "adopt",
            "reason_code": "other",
            "stuck_question": "q",
            "corpus_reference": "Work · Scene",
            "next_node": "next",
            "thread_id": str(thread.id),
            "run_id": str(run.id),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["decisions"]["adopt"] == 1
    with SessionLocal() as session:
        rows = list(session.scalars(select(FeedbackRow)).all())
    assert len(rows) == 1
    assert str(rows[0].thread_id) == str(thread.id)
    assert str(rows[0].run_id) == str(run.id)
    assert rows[0].suggestion_ref
    assert (tmp_path / "feedback.jsonl").exists()


def test_feedback_rejects_unknown_thread(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(plot_api, "_feedback_path", lambda: tmp_path / "feedback.jsonl")

    response = TestClient(app).post(
        "/v1/plot/feedback",
        json={"decision": "adopt", "thread_id": str(uuid4())},
    )

    assert response.status_code == 404


def test_beats_endpoint_records_tool_and_llm_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = SceneUnit(
        scene_id="s1",
        work_id="w",
        work_title="W",
        language="zh",
        genre="Drama",
        scene_no=1,
        heading="SC",
        text="宝玉把帕子塞进袖子里，没有说话。",
    )
    index = SceneIndex([scene], [[1.0, 0.0]])

    async def fake_completer(model: str, messages: object, config: object) -> RawCompletion:
        return RawCompletion(
            content=json.dumps(
                {
                    "beats": [
                        {"index": 1, "next_node": "他把帕子收起来。"},
                        {"index": 2, "next_node": "她看见了，没有问。"},
                    ],
                    "risk": "",
                    "still_unresolved": "",
                },
                ensure_ascii=False,
            ),
            prompt_tokens=100,
            completion_tokens=200,
            cost_usd=0.001,
            model="fake/writer",
        )

    gateway = StructuredGateway(
        roles={"writer": RoleConfig(model="fake/writer")},
        completer=fake_completer,
    )
    monkeypatch.setattr(plot_api.deps, "scene_index", lambda: index)
    monkeypatch.setattr(plot_api.deps, "gateway", lambda: gateway)

    store = ThreadStore(SessionLocal)
    thread = store.create_thread(title="beats persistence")
    run = RunLedger(SessionLocal).create_run("plot_turn", thread_id=thread.id)
    store.append_message(
        thread.id,
        "assistant",
        payload={
            "suggestions": [
                {
                    "next_node": "他把帕子收起来。",
                    "character_behavior_logic": "不解释。",
                    "emotional_tone": "克制",
                    "corpus_reference": "W · SC",
                    "transfer_rationale": "用动作替代对白。",
                }
            ]
        },
        run_id=run.id,
    )

    client = TestClient(app)
    response = client.post(
        "/v1/plot/beats",
        json={
            "stuck": {
                "story_state": "草稿",
                "stuck_question": "接下来怎么走？",
                "genre": "Drama",
            },
            "suggestion": {
                "next_node": "他把帕子收起来。",
                "character_behavior_logic": "不解释。",
                "emotional_tone": "克制",
                "corpus_reference": "W · SC",
                "transfer_rationale": "用动作替代对白。",
            },
            "scene_id": "s1",
            "thread_id": str(thread.id),
            "source_run_id": str(run.id),
        },
    )

    assert response.status_code == 200
    assert len(response.json()["beats"]) == 2
    detail = client.get(f"/v1/threads/{thread.id}").json()
    assistant = next(item for item in detail["messages"] if item["role"] == "assistant")
    assert assistant["payload"]["beats"][0]["beats"][0]["next_node"] == "他把帕子收起来。"
    with SessionLocal() as session:
        tool_calls = list(session.scalars(select(ToolCall).where(ToolCall.name == "expand_beats")))
        llm_calls = list(session.scalars(select(LLMCall).where(LLMCall.role == "writer")))
    assert tool_calls
    assert llm_calls
