"""User story state: ingest the writer's draft and read facts back.

Graphiti is the writer's temporal knowledge graph. Postgres keeps a mirror so a
stopped Neo4j degrades the turn instead of breaking it, and so the prompt can be
assembled without a graph round-trip per tool call.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from canonguard.harness.store import ThreadStore
from canonguard.plot.story_kg import StoryFact, StoryKG


class FactBackend(Protocol):
    async def ingest(self, name: str, text: str) -> None: ...

    async def search(self, query: str, num_results: int = 10) -> list[StoryFact]: ...


BackendFactory = Callable[[str], FactBackend]


def _default_backend(group_id: str) -> FactBackend:
    return StoryKG.from_env(group_id)


class StoryStateService:
    def __init__(
        self,
        store: ThreadStore,
        backend_factory: BackendFactory = _default_backend,
    ) -> None:
        self._store = store
        self._backend_factory = backend_factory
        self._backends: dict[str, FactBackend] = {}

    def _backend(self, group_id: str) -> FactBackend:
        if group_id not in self._backends:
            self._backends[group_id] = self._backend_factory(group_id)
        return self._backends[group_id]

    async def ingest_story(self, story_state_id: UUID | str) -> dict[str, Any]:
        """Read the stored draft, add it to the graph, mirror the resulting facts."""
        state = self._store.get_story_state(story_state_id)
        if state is None:
            raise KeyError(f"story state not found: {story_state_id}")
        text = (state.source_text or "").strip()
        if not text:
            return {"facts": 0, "reason": "empty draft"}
        group_id = state.kg_group_id or f"story-{state.id}"
        backend = self._backend(group_id)
        await backend.ingest(f"story-{state.id}", text)
        facts = await backend.search(text[:500], num_results=20)
        mirrored = self._store.replace_story_facts(
            state.id,
            [
                {
                    "subject": fact.fact[:200],
                    "predicate": "",
                    "object": "",
                    "source_span": fact.fact,
                }
                for fact in facts
            ],
        )
        self._store.set_kg_group(state.id, group_id)
        return {"facts": mirrored, "group_id": group_id}

    async def facts_for(
        self,
        story_state_id: UUID | str,
        query: str,
        limit: int = 8,
    ) -> list[str]:
        """Relevant facts for this turn; falls back to the Postgres mirror."""
        state = self._store.get_story_state(story_state_id)
        if state is None or not query.strip():
            return []
        group_id = state.kg_group_id
        if group_id:
            try:
                facts = await self._backend(group_id).search(query, num_results=limit)
                if facts:
                    return [fact.fact for fact in facts]
            except Exception:  # noqa: BLE001 - a stopped graph must not stop the turn
                pass
        mirrored = self._store.list_story_facts(story_state_id)
        return [fact.source_span or fact.subject for fact in mirrored[:limit]]
