from canonguard.db.session import SessionLocal
from canonguard.runs.ledger import RunLedger


def test_run_lifecycle() -> None:
    ledger = RunLedger(SessionLocal)
    run = ledger.create_run("demo", scope={"kind": "test"})
    assert run.status == "queued"

    ledger.mark_running(run.id)
    step = ledger.start_step(run.id, "prepare")
    ledger.finish_step(step.id, payload={"ok": True})
    ledger.finish_run(run.id, "succeeded")

    fetched = ledger.get_run(run.id)
    assert fetched is not None
    assert fetched.status == "succeeded"
    assert fetched.finished_at is not None

    steps = ledger.list_steps(run.id)
    assert len(steps) == 1
    assert steps[0].status == "succeeded"
    assert steps[0].payload == {"ok": True}


def test_llm_call_recording() -> None:
    ledger = RunLedger(SessionLocal)
    run = ledger.create_run("demo")
    call = ledger.record_llm_call(
        run_id=run.id,
        role="extractor",
        model="test-model",
        prompt_hash="abc",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.001,
        latency_ms=12.5,
    )

    assert call.role == "extractor"
    assert call.prompt_tokens == 10
