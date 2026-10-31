import asyncio
import json
import re

from canonguard.llm.gateway import LiteLLMCompleter, RoleConfig
from canonguard.llm.providers import load_model_endpoints


def _redact(text: str) -> str:
    return re.sub(r"(sk-|qwen-)[A-Za-z0-9_-]+", r"\1***", text)


async def main() -> None:
    primary, fallback = load_model_endpoints()
    endpoint = primary or fallback
    if endpoint is None:
        print("no LLM endpoint configured")
        raise SystemExit(1)

    config = RoleConfig(
        model=endpoint.model,
        temperature=0.0,
        max_output_tokens=256,
        api_base=endpoint.api_base,
        api_key=endpoint.api_key,
    )
    completer = LiteLLMCompleter(timeout_seconds=60)
    try:
        result = await completer(
            config.model,
            [
                {
                    "role": "user",
                    "content": 'Reply with JSON: {"ok": true}',
                }
            ],
            config,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "endpoint": endpoint.name,
                    "model": endpoint.model,
                    "error_type": type(exc).__name__,
                    "detail": _redact(str(exc))[:1200],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1) from exc

    print(
        json.dumps(
            {
                "ok": True,
                "endpoint": endpoint.name,
                "model": result.model,
                "content": result.content[:500],
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
