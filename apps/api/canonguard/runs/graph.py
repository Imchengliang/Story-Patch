from typing import Any, TypedDict
from uuid import UUID

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from canonguard.runs.ledger import RunLedger


class DemoState(TypedDict, total=False):
    run_id: str
    message: str


def _run_id(state: DemoState) -> UUID:
    return UUID(state["run_id"])


def build_demo_graph(
    ledger: RunLedger,
    checkpointer: Any | None = None,
) -> Any:
    def prepare(state: DemoState) -> DemoState:
        run_id = _run_id(state)
        step = ledger.start_step(run_id, "prepare", {"message": "preparing"})
        ledger.finish_step(step.id, payload={"message": "prepared"})
        return {"message": "prepared"}

    def finish(state: DemoState) -> DemoState:
        run_id = _run_id(state)
        step = ledger.start_step(run_id, "finish", {"message": "finishing"})
        ledger.finish_step(step.id, payload={"message": "finished"})
        return {"message": "finished"}

    workflow = StateGraph(DemoState)
    workflow.add_node("prepare", prepare)
    workflow.add_node("finish", finish)
    workflow.set_entry_point("prepare")
    workflow.add_edge("prepare", "finish")
    workflow.add_edge("finish", END)
    return workflow.compile(checkpointer=checkpointer or MemorySaver())


def run_demo(
    ledger: RunLedger,
    run_id: str | UUID,
    checkpointer: Any | None = None,
) -> None:
    rid = UUID(str(run_id))
    ledger.mark_running(rid)
    graph = build_demo_graph(ledger, checkpointer)
    try:
        graph.invoke(
            {"run_id": str(rid)},
            config={"configurable": {"thread_id": str(rid)}},
        )
    except Exception as exc:
        ledger.finish_run(rid, "failed", error=str(exc))
        raise
    ledger.finish_run(rid, "succeeded")
