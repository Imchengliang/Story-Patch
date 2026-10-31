"""Gateway wrapper that records every model call against the run ledger."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from canonguard.llm.gateway import LLMGateway, LLMResult

Recorder = Callable[[str, LLMResult], None]


class RecordingGateway:
    """Keeps tool code ignorant of accounting: it still calls ``complete`` as usual."""

    def __init__(self, inner: LLMGateway, on_call: Recorder) -> None:
        self._inner = inner
        self._on_call = on_call

    async def complete(
        self,
        role: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> LLMResult:
        result = await self._inner.complete(role, messages, schema)
        self._on_call(role, result)
        return result
