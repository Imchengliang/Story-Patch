"""In-process event buffer so a browser can follow a run it did not start.

Deliberately not durable: the ledger keeps the authoritative record, and the
assistant message keeps the final payload. This only carries live progress, and
a restart simply means the client re-reads the thread.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunBuffer:
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    closed: bool = False


@dataclass
class RunEventBus:
    max_runs: int = 20
    poll_interval: float = 0.05
    _buffers: OrderedDict[str, RunBuffer] = field(default_factory=OrderedDict)

    def start(self, run_id: str) -> RunBuffer:
        buffer = self._buffers.get(run_id) or RunBuffer()
        buffer.events = []
        buffer.closed = False
        self._buffers[run_id] = buffer
        self._buffers.move_to_end(run_id)
        self._evict()
        return buffer

    def _evict(self) -> None:
        """Drop the oldest finished buffers; never evict a run that is still streaming."""
        while len(self._buffers) > self.max_runs:
            oldest = next((key for key, buf in self._buffers.items() if buf.closed), None)
            if oldest is None:
                return
            self._buffers.pop(oldest)

    def publish(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        buffer = self._buffers.get(run_id)
        if buffer is None:
            return
        buffer.events.append((event, data))

    def close(self, run_id: str) -> None:
        buffer = self._buffers.get(run_id)
        if buffer is not None:
            buffer.closed = True

    def known(self, run_id: str) -> bool:
        return run_id in self._buffers

    async def stream(self, run_id: str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Replay from the first event, then follow until the run closes."""
        buffer = self._buffers.get(run_id)
        if buffer is None:
            return
        cursor = 0
        while True:
            while cursor < len(buffer.events):
                event, data = buffer.events[cursor]
                cursor += 1
                yield event, data
            if buffer.closed:
                return
            await asyncio.sleep(self.poll_interval)


event_bus = RunEventBus()
