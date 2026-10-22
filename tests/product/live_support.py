"""Shared offline fixtures for the live-runner tests: fake keys, fake transports, canned replies.

Nothing here touches the network or a real credential. The fake key is syntactically a
key (prefix `sk-or-`) but contains non-hex marker text so no secret scanner matches it.
"""

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from deploy_vii.live.catalog import Catalog, PinnedPool
from deploy_vii.live.client import Request, Response
from deploy_vii.live.settings import CandidateSetting

FIXTURES = Path(__file__).parent / "live_fixtures"
FAKE_KEY = "sk-or-v1-TESTONLY-not-a-real-key-0123456789"
SECOND_FAKE_KEY = "sk-or-v1-TESTONLY-other-fake-key-9876543210"

CANDIDATES = (
    CandidateSetting("luna", "openai/gpt-6-luna", "explicit-version"),
    CandidateSetting("glm", "z-ai/glm-5.3-flash", "explicit-version"),
    CandidateSetting(
        "deepseek",
        "deepseek/deepseek-v4.1-flash-1017",
        "refresh-latest-suitable-deepseek-before-batch",
    ),
)


def fixture_catalog() -> Catalog:
    return Catalog.from_file(FIXTURES / "models-subset.json", looked_up_at="2026-10-21T09:00:00Z")


def fixture_pool(batch_id: str = "batch-test") -> PinnedPool:
    return fixture_catalog().pin(batch_id, CANDIDATES)


def make_rtf_key(directory: Path, key: str = FAKE_KEY, *, name: str = "key.rtf") -> Path:
    """Generate a fixture RTF credential file with macOS textutil (macOS-only tool)."""
    textutil = shutil.which("textutil")
    if textutil is None:
        pytest.skip("textutil is absent (macOS-only); credential conversion cannot be exercised")
    source = directory / (name + ".txt")
    source.write_text(key + "\n", encoding="utf-8")
    target = directory / name
    subprocess.run(
        [textutil, "-convert", "rtf", str(source), "-output", str(target)],
        check=True,
        capture_output=True,
    )
    source.unlink()
    return target


def chat_body(
    content: str,
    *,
    model: str = "openai/gpt-6-luna",
    provider: str | None = "OpenAI",
    finish_reason: str = "stop",
    usage: dict[str, object] | bool = True,
) -> bytes:
    """A canned OpenRouter chat-completions reply; `usage=False` omits the usage object."""
    body: dict[str, object] = {
        "id": "gen-test-0001",
        "model": model,
        "choices": [
            {"finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}
        ],
    }
    if provider is not None:
        body["provider"] = provider
    if usage is True:
        body["usage"] = {
            "prompt_tokens": 1000,
            "completion_tokens": 400,
            "total_tokens": 1400,
            "completion_tokens_details": {"reasoning_tokens": 250},
            "prompt_tokens_details": {"cached_tokens": 0},
            "cost": 0.00033,
        }
    elif isinstance(usage, dict):
        body["usage"] = usage
    return json.dumps(body).encode()


class FakeTransport:
    """Records requests; replies from a queue of Responses or exceptions."""

    def __init__(self, *replies: Response | BaseException | Callable[[Request], Response]) -> None:
        self.replies = list(replies)
        self.requests: list[Request] = []

    def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            return reply(request)
        return reply


def ok(
    content: str,
    *,
    model: str = "openai/gpt-6-luna",
    provider: str | None = "OpenAI",
    finish_reason: str = "stop",
    usage: dict[str, object] | bool = True,
) -> Response:
    body = chat_body(
        content, model=model, provider=provider, finish_reason=finish_reason, usage=usage
    )
    return Response(status=200, body=body)


def catalog_row(
    model_id: str,
    *,
    context: int = 1_048_576,
    completion_limit: int = 131_072,
    efforts: tuple[str, ...] | None = ("high", "low"),
    parameters: tuple[str, ...] = (
        "max_tokens",
        "reasoning",
        "reasoning_effort",
        "response_format",
        "structured_outputs",
    ),
    pricing: dict[str, str] | None = None,
) -> dict[str, object]:
    """A synthetic models-catalog row (the shape OpenRouter returns)."""
    reasoning: dict[str, object] = {"mandatory": False}
    if efforts is not None:
        reasoning["supported_efforts"] = list(efforts)
    return {
        "id": model_id,
        "canonical_slug": model_id,
        "created": 1,
        "context_length": context,
        "architecture": {"output_modalities": ["text"]},
        "pricing": pricing or {"prompt": "0.000001", "completion": "0.000002"},
        "top_provider": {"context_length": context, "max_completion_tokens": completion_limit},
        "reasoning": reasoning,
        "supported_parameters": list(parameters),
    }


def catalog_of(*rows: dict[str, object]) -> Catalog:
    raw = json.dumps({"data": list(rows)}).encode()
    return Catalog.from_bytes(raw, source="synthetic", looked_up_at="2026-10-22T09:00:00Z")
