import asyncio

from canonguard.db.session import SessionLocal
from canonguard.runs.graph import run_demo
from canonguard.runs.ledger import RunLedger
from canonguard.runs.sse import step_event_stream


def test_demo_graph_writes_steps() -> None:
    ledger = RunLedger(SessionLocal)
    run = ledger.create_run("demo")

    run_demo(ledger, run.id)

    fetched = ledger.get_run(run.id)
    assert fetched is not None
    assert fetched.status == "succeeded"
    assert [step.step for step in ledger.list_steps(run.id)] == ["prepare", "finish"]


def test_event_stream_emits_done() -> None:
    ledger = RunLedger(SessionLocal)
    run = ledger.create_run("demo")
    run_demo(ledger, run.id)

    async def collect() -> list[dict[str, str]]:
        events = []
        async for event in step_event_stream(SessionLocal, run.id, poll_interval=0):
            events.append(event)
        return events

    events = asyncio.run(collect())

    assert any(event["event"] == "step" for event in events)
    assert any(event["event"] == "done" for event in events)
