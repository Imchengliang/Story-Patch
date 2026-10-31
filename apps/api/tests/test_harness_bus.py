import asyncio

from canonguard.harness.bus import RunEventBus


def test_publish_is_visible_to_a_late_subscriber() -> None:
    bus = RunEventBus()
    bus.start("r1")
    bus.publish("r1", "plan", {"steps": ["a"]})
    bus.publish("r1", "done", {"ok": True})
    bus.close("r1")

    async def collect() -> list[str]:
        return [event async for event, _ in bus.stream("r1")]

    assert asyncio.run(collect()) == ["plan", "done"]


def test_stream_follows_a_run_that_is_still_open() -> None:
    bus = RunEventBus(poll_interval=0.001)
    bus.start("r2")
    bus.publish("r2", "tool_result", {"tool": "parse_stuck_point"})

    async def run() -> list[str]:
        async def producer() -> None:
            await asyncio.sleep(0.005)
            bus.publish("r2", "done", {"ok": True})
            bus.close("r2")

        task = asyncio.create_task(producer())
        events = [event async for event, _ in bus.stream("r2")]
        await task
        return events

    assert asyncio.run(run()) == ["tool_result", "done"]


def test_publishing_to_an_unknown_run_is_ignored() -> None:
    bus = RunEventBus()
    bus.publish("ghost", "plan", {})
    assert bus.known("ghost") is False


def test_closed_runs_are_evicted_but_live_ones_are_kept() -> None:
    bus = RunEventBus(max_runs=2)
    bus.start("live")
    bus.publish("live", "plan", {})
    for name in ("a", "b", "c"):
        bus.start(name)
        bus.close(name)

    assert bus.known("live") is True
    assert bus.known("a") is False
    assert bus.known("c") is True
