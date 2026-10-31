"""Run budgets: the limits declared in settings finally get enforced.

The check runs after every tool step, so one in-flight LLM call may overshoot;
that is stated in the event rather than hidden. Anything cheaper would require
predicting token counts before the model answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from canonguard.core.config import Settings


@dataclass(frozen=True)
class Budget:
    max_tokens: int
    max_cost_usd: float

    @classmethod
    def from_settings(cls, settings: Settings) -> Budget:
        return cls(
            max_tokens=settings.run_max_tokens,
            max_cost_usd=settings.run_max_cost_usd,
        )


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "calls": self.calls,
        }

    @classmethod
    def from_row(cls, row: Any) -> Usage:
        if row is None:
            return cls()
        return cls(
            prompt_tokens=int(row[0] or 0),
            completion_tokens=int(row[1] or 0),
            cost_usd=float(row[2] or 0.0),
            calls=int(row[3] or 0),
        )


def exceeded(usage: Usage, budget: Budget) -> str | None:
    """Return a human-readable reason when the run is over budget, else None."""
    if budget.max_tokens and usage.total_tokens > budget.max_tokens:
        return (
            f"budget_exceeded: {usage.total_tokens} tokens > limit {budget.max_tokens} "
            f"(one in-flight call may overshoot)"
        )
    if budget.max_cost_usd and usage.cost_usd > budget.max_cost_usd:
        return (
            f"budget_exceeded: ${usage.cost_usd:.4f} > limit ${budget.max_cost_usd:.2f} "
            f"(one in-flight call may overshoot)"
        )
    return None
