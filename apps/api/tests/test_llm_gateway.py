from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from canonguard.core.config import Settings
from canonguard.llm.gateway import (
    ConfigurationError,
    LiteLLMCompleter,
    OutputContractError,
    RawCompletion,
    RoleConfig,
    StructuredGateway,
    role_configs_from_settings,
)


class Sample(BaseModel):
    name: str


@dataclass
class FakeCompleter:
    responses: list[str]
    calls: list[tuple[str, list[dict[str, str]], RoleConfig]]

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = []

    async def __call__(
        self,
        model: str,
        messages: list[dict[str, str]],
        config: RoleConfig,
    ) -> RawCompletion:
        self.calls.append((model, messages, config))
        return RawCompletion(content=self.responses.pop(0))


async def test_structured_gateway_repairs_invalid_json() -> None:
    completer = FakeCompleter(["not json", '{"name": "ok"}'])
    gateway = StructuredGateway(
        roles={"extractor": RoleConfig(model="test/model")},
        completer=completer,
        max_repairs=2,
    )

    result = await gateway.complete(
        "extractor",
        [{"role": "user", "content": "extract"}],
        Sample,
    )

    assert result.parsed.model_dump() == {"name": "ok"}
    assert len(completer.calls) == 2
    assert len(completer.calls[0][1]) == 1
    assert "Return valid JSON only" in completer.calls[1][1][-1]["content"]


async def test_structured_gateway_fails_after_max_repairs() -> None:
    completer = FakeCompleter(["bad", "still bad"])
    gateway = StructuredGateway(
        roles={"extractor": RoleConfig(model="test/model")},
        completer=completer,
        max_repairs=1,
    )

    with pytest.raises(OutputContractError):
        await gateway.complete(
            "extractor",
            [{"role": "user", "content": "extract"}],
            Sample,
        )


async def test_unknown_role_raises_configuration_error() -> None:
    gateway = StructuredGateway(roles={}, completer=FakeCompleter([]))

    with pytest.raises(ConfigurationError):
        await gateway.complete("missing", [], Sample)


def test_role_configs_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        llm_extractor_model="test/extractor",
        llm_gap_model="test/gap",
    )

    roles = role_configs_from_settings(settings)

    assert roles["extractor"].model == "test/extractor"
    assert roles["gap_analyst"].model == "test/gap"
    assert "writer" not in roles


def test_role_configs_require_at_least_one_model() -> None:
    settings = Settings(_env_file=None)

    with pytest.raises(ConfigurationError):
        role_configs_from_settings(settings)


def test_cost_falls_back_to_estimates_when_provider_reports_zero() -> None:
    completer = LiteLLMCompleter()

    assert completer._cost_usd("openai/deepseek-flash", 1_000_000, 0, 0.0) == pytest.approx(0.28)
    assert completer._cost_usd("openai/deepseek-flash", 0, 1_000_000, 0.0) == pytest.approx(1.10)
    assert completer._cost_usd("openai/deepseek-flash", 100, 100, 0.5) == pytest.approx(0.5)


def test_cost_estimate_respects_explicit_prices() -> None:
    completer = LiteLLMCompleter(price_input_per_1m=1.0, price_output_per_1m=2.0)

    assert completer._cost_usd("x/unknown", 1_000_000, 1_000_000, 0.0) == pytest.approx(3.0)


def test_cost_unknown_model_returns_zero() -> None:
    completer = LiteLLMCompleter()

    assert completer._cost_usd("x/unknown", 1000, 1000, 0.0) == 0.0
