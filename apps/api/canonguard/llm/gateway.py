from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from canonguard.core.config import Settings
from canonguard.core.errors import CanonGuardError
from canonguard.core.logging import get_logger

logger = get_logger(__name__)


class ConfigurationError(CanonGuardError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            title="Configuration Error",
            detail=detail,
            status_code=500,
            code="configuration_error",
        )


class OutputContractError(CanonGuardError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            title="LLM Output Contract Error",
            detail=detail,
            status_code=502,
            code="output_contract_error",
        )


@dataclass(frozen=True)
class ModelEndpoint:
    name: str
    model: str
    api_base: str | None = None
    api_key: str | None = None


@dataclass(frozen=True)
class RoleConfig:
    model: str
    temperature: float = 0.0
    max_output_tokens: int = 4096
    api_base: str | None = None
    api_key: str | None = None
    fallback: ModelEndpoint | None = None


@dataclass(frozen=True)
class RawCompletion:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    model: str | None = None
    used_fallback: bool = False


@dataclass(frozen=True)
class LLMResult:
    parsed: BaseModel
    raw: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    used_fallback: bool = False


class LLMGateway(Protocol):
    """Minimal surface every caller needs: one structured completion."""

    async def complete(
        self,
        role: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> LLMResult: ...


Completer = Callable[[str, list[dict[str, str]], RoleConfig], Awaitable[RawCompletion]]


class StructuredGateway:
    def __init__(
        self,
        roles: dict[str, RoleConfig],
        completer: Completer,
        max_repairs: int = 2,
    ) -> None:
        self._roles = roles
        self._completer = completer
        self._max_repairs = max_repairs

    @property
    def roles(self) -> dict[str, RoleConfig]:
        return dict(self._roles)

    async def complete(
        self,
        role: str,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> LLMResult:
        config = self._roles.get(role)
        if config is None:
            raise ConfigurationError(f"LLM role is not configured: {role}")

        working_messages = list(messages)
        for attempt in range(self._max_repairs + 1):
            started = perf_counter()
            raw = await self._completer(config.model, working_messages, config)
            latency_ms = (perf_counter() - started) * 1000
            try:
                parsed = schema.model_validate_json(raw.content)
            except ValidationError as exc:
                if attempt == self._max_repairs:
                    raise OutputContractError(
                        f"role={role} did not return valid JSON after "
                        f"{self._max_repairs + 1} attempts: {exc}"
                    ) from exc
                working_messages = [
                    *working_messages,
                    {
                        "role": "user",
                        "content": (
                            "The previous response did not match the required JSON "
                            f"schema. Return valid JSON only. Errors: {exc}"
                        ),
                    },
                ]
                continue

            return LLMResult(
                parsed=parsed,
                raw=raw.content,
                model=raw.model or config.model,
                prompt_tokens=raw.prompt_tokens,
                completion_tokens=raw.completion_tokens,
                cost_usd=raw.cost_usd,
                latency_ms=round(latency_ms, 2),
                used_fallback=raw.used_fallback,
            )

        raise AssertionError("unreachable")


class LiteLLMCompleter:
    # Conservative list prices (USD per 1M tokens) for models litellm does not
    # know. Estimates, not billing truth; override with CANONGUARD_LLM_PRICE_*.
    _ESTIMATED_PRICES: dict[str, tuple[float, float]] = {
        "deepseek-flash": (0.28, 1.10),
        "deepseek-chat": (0.27, 1.10),
        "deepseek-reasoner": (0.55, 2.19),
    }

    def __init__(
        self,
        timeout_seconds: int = 120,
        price_input_per_1m: float = 0.0,
        price_output_per_1m: float = 0.0,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._price_input_per_1m = price_input_per_1m
        self._price_output_per_1m = price_output_per_1m
        self._warned_models: set[str] = set()

    def _price_for(self, model: str) -> tuple[float, float]:
        if self._price_input_per_1m or self._price_output_per_1m:
            return self._price_input_per_1m, self._price_output_per_1m
        return self._ESTIMATED_PRICES.get(model.rsplit("/", 1)[-1], (0.0, 0.0))

    def _cost_usd(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        reported_cost: float,
    ) -> float:
        """Prefer the provider's number; fall back to an estimate, never silence."""
        if reported_cost:
            return reported_cost
        if not (prompt_tokens or completion_tokens):
            return 0.0
        price_in, price_out = self._price_for(model)
        if price_in or price_out:
            return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
        if model not in self._warned_models:
            self._warned_models.add(model)
            logger.warning(
                "llm_cost_unknown",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                hint="set CANONGUARD_LLM_PRICE_INPUT_PER_1M / _OUTPUT_PER_1M",
            )
        return 0.0

    async def __call__(
        self,
        model: str,
        messages: list[dict[str, str]],
        config: RoleConfig,
    ) -> RawCompletion:
        try:
            return await self._call_endpoint(
                model=model,
                api_base=config.api_base,
                api_key=config.api_key,
                messages=messages,
                config=config,
                used_fallback=False,
            )
        except Exception as primary_error:
            if config.fallback is None:
                raise
            logger.warning(
                "llm_primary_failed",
                primary_model=config.model,
                fallback_model=config.fallback.model,
                error_type=type(primary_error).__name__,
            )
            return await self._call_endpoint(
                model=config.fallback.model,
                api_base=config.fallback.api_base,
                api_key=config.fallback.api_key,
                messages=messages,
                config=config,
                used_fallback=True,
            )

    async def _call_endpoint(
        self,
        *,
        model: str,
        api_base: str | None,
        api_key: str | None,
        messages: list[dict[str, str]],
        config: RoleConfig,
        used_fallback: bool,
    ) -> RawCompletion:
        import litellm

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": config.temperature,
            "max_tokens": config.max_output_tokens,
            "timeout": self._timeout_seconds,
        }
        if api_base:
            kwargs["api_base"] = api_base
        if api_key:
            kwargs["api_key"] = api_key

        try:
            response: Any = await litellm.acompletion(
                **kwargs,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            message = str(exc).lower()
            if "response_format" not in message and "json_object" not in message:
                raise
            response = await litellm.acompletion(**kwargs)

        content = response.choices[0].message.content or ""
        if not str(content).strip():
            response = await litellm.acompletion(**kwargs)
            content = response.choices[0].message.content or ""
        if not str(content).strip():
            raise RuntimeError("empty completion from model")

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        reported_cost = 0.0
        try:
            reported_cost = float(litellm.completion_cost(completion_response=response) or 0.0)
        except Exception:
            reported_cost = 0.0
        cost_usd = self._cost_usd(model, prompt_tokens, completion_tokens, reported_cost)

        return RawCompletion(
            content=str(content),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            model=model,
            used_fallback=used_fallback,
        )


def role_configs_from_settings(settings: Settings) -> dict[str, RoleConfig]:
    role_models = {
        "extractor": (settings.llm_extractor_model, 0.0),
        "gap_analyst": (settings.llm_gap_model, 0.1),
        "planner": (settings.llm_planner_model, 0.2),
        "writer": (settings.llm_writer_model, 0.6),
        "reviewer": (settings.llm_reviewer_model, 0.0),
        "auditor": (settings.llm_auditor_model, 0.0),
        "judge": (settings.llm_judge_model, 0.0),
    }
    roles = {
        name: RoleConfig(model=model, temperature=temperature)
        for name, (model, temperature) in role_models.items()
        if model
    }
    if not roles:
        raise ConfigurationError(
            "No LLM roles are configured. Set CANONGUARD_LLM_EXTRACTOR_MODEL "
            "or provide QWEN38_27B_FP8_* / DEEPSEEK_* in the root .env."
        )
    return roles
