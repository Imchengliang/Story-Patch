import asyncio
import json
import re

from pydantic import BaseModel

from canonguard.core.config import get_settings
from canonguard.llm.providers import build_gateway


class SmokeAnswer(BaseModel):
    answer: str
    confidence: float


def _redact(text: str) -> str:
    return re.sub(r"(sk-|qwen-)[A-Za-z0-9_-]+", r"\1***", text)


async def main() -> None:
    gateway = build_gateway(get_settings())
    try:
        result = await gateway.complete(
            "extractor",
            [
                {
                    "role": "system",
                    "content": (
                        "Return a JSON object with fields answer (string) and "
                        "confidence (number between 0 and 1). No markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": "用一句话说明《红楼梦》第30到35回主要发生在哪里。",
                },
            ],
            SmokeAnswer,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "detail": _redact(str(exc))[:500],
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
                "model": result.model,
                "used_fallback": result.used_fallback,
                "answer": result.parsed.model_dump(),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cost_usd": result.cost_usd,
                "latency_ms": result.latency_ms,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
