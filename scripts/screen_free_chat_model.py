"""Screen a candidate chat model's wire contract against the adapter's rules.

The adapter requires, for a chat response, that the reported model identifier is
present and is either the requested identifier or an explicitly supplied alias.
This screen reports what the route actually returns, so a model is only adopted
on observed behaviour rather than on a catalogue entry.

The screen sends small synthetic payloads. It never sends clinic content, never
prints the credential, and never prints an upstream body: it reports only the
observed contract.

Usage:
    python scripts/screen_free_chat_model.py --model minimax/minimax-m3.1-flash:free
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx2 as httpx

REPO = Path(__file__).resolve().parent.parent

SCREEN_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "screen",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "note": {"type": "string"},
            },
            "required": ["ok", "note"],
            "additionalProperties": False,
        },
    },
}

# The adapter always sends the strict schema and pins the route. These variants
# separate a routing refusal from a model capability gap.
PINNED = {"require_parameters": True, "allow_fallbacks": False}
OPEN = {"require_parameters": False, "allow_fallbacks": False}
FALLBACK = {"require_parameters": True, "allow_fallbacks": True}
NO_PROVIDER = None

VARIANTS = (
    ("pinned_route_strict_schema", PINNED, SCREEN_SCHEMA, "screen", None),
    ("open_route_strict_schema", OPEN, SCREEN_SCHEMA, "screen", None),
    ("fallback_route_strict_schema", FALLBACK, SCREEN_SCHEMA, "screen", None),
    ("no_provider_block_strict_schema", NO_PROVIDER, SCREEN_SCHEMA, "screen", None),
    ("open_route_real_planner_schema", OPEN, None, "planner", None),
    ("pinned_route_real_planner_schema", PINNED, None, "planner", None),
    ("open_route_real_planner_no_reasoning", OPEN, None, "planner", {"effort": "none"}),
)

MESSAGES = [
    {
        "role": "user",
        "content": json.dumps(
            {
                "instruction": "Reply with ok=true and note='screen'.",
                "synthetic": True,
            }
        ),
    }
]


def key_from_env() -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("project OpenRouter key not found in .env")


async def attempt(
    client: httpx.AsyncClient,
    model: str,
    headers: dict[str, str],
    *,
    variant: str,
    provider_block: dict[str, Any] | None,
    response_format: dict[str, Any] | None,
    messages: list[dict[str, str]],
    expected_keys: tuple[str, ...] | None = None,
    reasoning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": 4096,
        "stream": False,
    }
    if reasoning is not None:
        payload["reasoning"] = reasoning
    if response_format is not None:
        payload["response_format"] = response_format
    if provider_block is not None:
        payload["provider"] = provider_block
    started = time.monotonic()
    try:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers
        )
    except Exception as error:
        return {
            "variant": variant,
            "status": None,
            "error": type(error).__name__,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    elapsed = round(time.monotonic() - started, 3)
    observed: dict[str, Any] = {
        "variant": variant,
        "status": response.status_code,
        "elapsed_seconds": elapsed,
    }
    try:
        body = response.json()
    except Exception:
        observed["body_is_json"] = False
        return observed
    observed["body_is_json"] = True
    if response.status_code != 200:
        error = body.get("error", {}) if isinstance(body, dict) else {}
        observed["error_code"] = error.get("code")
        observed["error_message"] = str(error.get("message"))[:300]
        return observed
    choices = body.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    content = message.get("content")
    observed["reported_model"] = body.get("model")
    observed["provider"] = body.get("provider")
    usage = body.get("usage") or {}
    observed["cost"] = usage.get("cost")
    observed["prompt_tokens"] = usage.get("prompt_tokens")
    observed["completion_tokens"] = usage.get("completion_tokens")
    observed["reasoning_tokens"] = (usage.get("completion_tokens_details") or {}).get(
        "reasoning_tokens"
    )
    observed["finish_reason"] = choices[0].get("finish_reason") if choices else None
    observed["content_is_string"] = isinstance(content, str)
    if isinstance(content, str):
        text = content.strip()
        observed["content_length"] = len(text)
        observed["content_has_code_fence"] = text.startswith("```")
        observed["content_first_160"] = text[:160]
        parsed = None
        try:
            parsed = json.loads(text)
        except Exception:
            observed["content_parses_as_json"] = False
        if parsed is None and observed["content_has_code_fence"]:
            inner = text.strip("`")
            if inner.lower().startswith("json"):
                inner = inner[4:]
            try:
                parsed = json.loads(inner.strip())
            except Exception:
                parsed = None
        if parsed is not None:
            observed["content_parses_as_json"] = True
            observed["content_keys"] = sorted(parsed) if isinstance(parsed, dict) else None
            if expected_keys is None:
                observed["content_matches_schema"] = (
                    isinstance(parsed, dict)
                    and set(parsed) == {"ok", "note"}
                    and isinstance(parsed.get("ok"), bool)
                    and isinstance(parsed.get("note"), str)
                )
            else:
                observed["content_matches_schema"] = isinstance(parsed, dict) and set(
                    parsed
                ) == set(expected_keys)
    else:
        observed["content_type"] = type(content).__name__
        observed["content_keys_when_object"] = (
            sorted(content) if isinstance(content, dict) else None
        )
    return observed


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--only",
        action="append",
        help="Run only the named variant. Repeatable. Default: every variant.",
    )
    args = parser.parse_args()

    key = key_from_env()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    results = []
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        for variant, provider_block, response_format, schema_kind, reasoning in VARIANTS:
            if args.only and variant not in args.only:
                continue
            expected = None
            messages = MESSAGES
            if schema_kind == "planner":
                from telescope_rag.graph.contracts import PlannerReply
                from telescope_rag.providers.validation import output_schema

                response_format = {
                    "type": "json_schema",
                    "json_schema": output_schema(PlannerReply),
                }
                expected = tuple(sorted(PlannerReply.model_fields))
                messages = [
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "instruction": (
                                    "Split the question into parts. Use only the "
                                    "document handles and languages given. Answer "
                                    "with the JSON object the schema requires."
                                ),
                                "question": "What are your opening hours?",
                                "synthetic": True,
                            }
                        ),
                    }
                ]
            observed = await attempt(
                client,
                args.model,
                headers,
                variant=variant,
                provider_block=provider_block,
                response_format=response_format,
                messages=messages,
                expected_keys=expected,
                reasoning=reasoning,
            )
            results.append(observed)
            print(json.dumps(observed, ensure_ascii=False, indent=2))

    report = {
        "schema_version": "chat-model-wire-screen-v1",
        "requested_model": args.model,
        "attempts": results,
        "adapter_rule": (
            "the adapter accepts a chat response only when the reported model "
            "identifier equals the requested identifier or an explicit alias"
        ),
        "reported_matches_requested": any(r.get("reported_model") == args.model for r in results),
        "accepted_by_adapter_shape": any(
            r.get("status") == 200
            and r.get("reported_model") == args.model
            and r.get("content_matches_schema")
            for r in results
        ),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.output}")
    print(json.dumps({k: v for k, v in report.items() if k != "attempts"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
