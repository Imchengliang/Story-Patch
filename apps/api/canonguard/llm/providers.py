import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from canonguard.core.config import Settings
from canonguard.llm.gateway import (
    LiteLLMCompleter,
    ModelEndpoint,
    RoleConfig,
    StructuredGateway,
    role_configs_from_settings,
)

ROLE_TEMPERATURES = {
    "extractor": 0.0,
    "gap_analyst": 0.1,
    "planner": 0.2,
    "writer": 0.6,
    "reviewer": 0.0,
    "auditor": 0.0,
    "judge": 0.0,
}

DEEPSEEK_MODEL_ALIASES = {
    "deepseek-v4.1-flash": "deepseek-flash",
    "deepseekv4.1-flash": "deepseek-flash",
    "deepseek-v4.1": "deepseek-flash",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_values() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = _repo_root() / ".env"
    if env_path.exists():
        values.update(
            {key: value for key, value in dotenv_values(env_path).items() if value is not None}
        )
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def _first(values: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if value:
            return value
    return ""


def to_litellm_model(model: str) -> str:
    return model if "/" in model else f"openai/{model}"


@dataclass(frozen=True)
class EndpointPair:
    qwen: ModelEndpoint | None
    deepseek: ModelEndpoint | None

    def ordered(
        self, preference: str = "deepseek"
    ) -> tuple[ModelEndpoint | None, ModelEndpoint | None]:
        """Return (primary, fallback) for Auto mode."""
        if preference == "qwen":
            return self.qwen, self.deepseek
        return self.deepseek or self.qwen, self.qwen if self.deepseek else None


def load_endpoints() -> EndpointPair:
    values = _load_values()

    qwen_base = _first(values, "QWEN38_27B_FP8_BASE_URL", "QWEN_BASE_URL")
    qwen_key = _first(
        values,
        "QWEN38_27B_FP8_API_KEY",
        "QWEN_API_KEY",
        "QWEN35_4B_API_KEY",
    )
    qwen_model = _first(values, "QWEN38_27B_FP8_MODEL", "QWEN_MODEL")
    qwen = (
        ModelEndpoint(
            name="qwen",
            model=to_litellm_model(qwen_model or "qwen38-27b-fp8"),
            api_base=qwen_base or None,
            api_key=qwen_key or None,
        )
        if qwen_base and qwen_key
        else None
    )

    deepseek_base = _first(values, "DEEPSEEK_BASE_URL", "OPENAI_BASE_URL")
    deepseek_key = _first(values, "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
    deepseek_model = _first(values, "DEEPSEEK_MODEL", "OPENAI_MODEL")
    deepseek_model = DEEPSEEK_MODEL_ALIASES.get(
        deepseek_model or "",
        deepseek_model or "deepseek-flash",
    )
    deepseek = (
        ModelEndpoint(
            name="deepseek",
            model=to_litellm_model(deepseek_model),
            api_base=deepseek_base or None,
            api_key=deepseek_key or None,
        )
        if deepseek_base and deepseek_key
        else None
    )
    return EndpointPair(qwen=qwen, deepseek=deepseek)


def load_model_endpoints(
    preference: str = "deepseek",
) -> tuple[ModelEndpoint | None, ModelEndpoint | None]:
    """Backwards-compatible tuple form: (primary, fallback) following Auto order."""
    return load_endpoints().ordered(preference)


def build_gateway(settings: Settings) -> StructuredGateway:
    primary, fallback = load_model_endpoints(settings.model_preference)
    completer = LiteLLMCompleter(
        timeout_seconds=settings.llm_request_timeout_seconds,
        price_input_per_1m=settings.llm_price_input_per_1m,
        price_output_per_1m=settings.llm_price_output_per_1m,
    )

    if primary is None:
        return StructuredGateway(
            roles=role_configs_from_settings(settings),
            completer=completer,
            max_repairs=settings.llm_max_repairs,
        )

    explicit_models = {
        "extractor": settings.llm_extractor_model,
        "gap_analyst": settings.llm_gap_model,
        "planner": settings.llm_planner_model,
        "writer": settings.llm_writer_model,
        "reviewer": settings.llm_reviewer_model,
        "auditor": settings.llm_auditor_model,
        "judge": settings.llm_judge_model,
    }
    roles = {
        name: RoleConfig(
            model=to_litellm_model(explicit_models[name] or primary.model),
            temperature=temperature,
            max_output_tokens=8192,
            api_base=primary.api_base,
            api_key=primary.api_key,
            fallback=fallback,
        )
        for name, temperature in ROLE_TEMPERATURES.items()
    }
    if fallback is not None:
        roles["fact_verifier"] = RoleConfig(
            model=fallback.model,
            temperature=0.0,
            max_output_tokens=8192,
            api_base=fallback.api_base,
            api_key=fallback.api_key,
            fallback=primary,
        )
    else:
        roles["fact_verifier"] = RoleConfig(
            model=primary.model,
            temperature=0.0,
            max_output_tokens=4096,
            api_base=primary.api_base,
            api_key=primary.api_key,
        )
    return StructuredGateway(
        roles=roles,
        completer=completer,
        max_repairs=settings.llm_max_repairs,
    )
