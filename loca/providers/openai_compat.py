"""Shared implementation for vendors that speak OpenAI Chat Completions.

DeepSeek, OpenAI and most self-hosted endpoints (vLLM, Ollama, LM Studio,
Together, Groq…) all expose the *same* wire protocol: a ``/chat/completions``
endpoint taking ``messages`` + ``tools`` and returning (or streaming) choices
with ``content`` and ``function``-style tool calls. Writing that translation
once and letting each vendor supply a base URL and a default model is the whole
reason :class:`OpenAICompatibleProvider` exists.

What a subclass must provide
----------------------------

``name``, ``default_base_url`` and ``default_model``. That is it — see
:class:`~loca.providers.openai.OpenAIProvider` for a three-line subclass.

Streaming contract (important)
------------------------------

The OpenAI protocol delivers a tool call as *fragments*: the first delta carries
``id`` + ``function.name``, later deltas carry pieces of the JSON argument
string. This class buffers those fragments and only ever emits a **fully
assembled** ``ToolCall``. A half-formed call (``arguments={}`` because the JSON
had not arrived yet) would look complete to the harness and be executed with
missing arguments, so in-progress fragments are deliberately never forwarded.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from loca.providers.base import LLMProvider
from loca.providers.types import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    Message,
    Role,
    StreamChunk,
    ToolCall,
    Usage,
)

#: Env var suffix for pointing a provider at a mirror/proxy/self-hosted endpoint.
BASE_URL_ENV_SUFFIX = "BASE_URL"

#: Env var suffix for overriding a provider's default model.
MODEL_ENV_SUFFIX = "MODEL"

#: Env var suffix for turning the streamed-usage request off. Self-hosted
#: gateways built on older OpenAI-compatible servers reject the unknown
#: ``stream_options`` field outright, so it has to be switchable per provider.
STREAM_USAGE_ENV_SUFFIX = "STREAM_USAGE"

_FALSEY = frozenset({"0", "false", "no", "off"})


def _env_flag(name: str, *, default: bool) -> bool:
    """Read a boolean-ish environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in _FALSEY


class OpenAICompatibleProvider(LLMProvider):
    """Translate loca's types to/from the OpenAI Chat Completions protocol."""

    name = "openai-compatible"
    #: Used when neither the constructor nor the environment names an endpoint.
    default_base_url = ""
    #: Used when ``ChatRequest.model`` is empty.
    default_model = ""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: float = 60.0,
        client: Any | None = None,
        stream_usage: bool | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                f"{type(self).__name__} requires a non-empty api_key "
                f"(set LOCA_{self.name.upper()}_API_KEY)."
            )
        self._default_model = default_model or self._env(MODEL_ENV_SUFFIX) or self.default_model
        # Streaming OpenAI-compatible endpoints only report token usage when the
        # request asks for it. Without this frame there is no usage at all, so
        # ``loca report`` shows 0 tokens for every streamed call — which is how
        # the "all three providers report usage" claim quietly stopped holding
        # for this one. On by default, switchable for gateways that reject it.
        self.stream_usage = (
            stream_usage
            if stream_usage is not None
            else _env_flag(
                f"LOCA_{self.name.upper()}_{STREAM_USAGE_ENV_SUFFIX}", default=True
            )
        )
        # ``client`` is injectable so tests can drive the parser with a fake
        # transport, exactly like the streaming regression tests do.
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=base_url or self._env(BASE_URL_ENV_SUFFIX) or self.default_base_url,
            timeout=timeout,
        )

    # ---- public API ------------------------------------------------------

    def chat(self, request: ChatRequest) -> ChatResponse:
        resp = self._client.chat.completions.create(**self._build_payload(request, stream=False))
        return self.parse_response(resp)

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        stream = self._client.chat.completions.create(**self._build_payload(request, stream=True))
        # index -> {"id": str, "name": str, "args": str, "args_is_str": bool}
        buf: dict[int, dict[str, Any]] = {}
        finish_seen: FinishReason | None = None
        for raw in stream:
            chunk = self.parse_stream_chunk(raw)
            if chunk.finish_reason is not None:
                finish_seen = chunk.finish_reason
            self._merge_tool_deltas(buf, raw)

            # No mid-stream draining: id/name usually arrive one chunk before
            # the argument fragments, and flushing as soon as a fragment
            # happens to parse would emit a call with truncated arguments.
            yield StreamChunk(
                delta_content=chunk.delta_content,
                delta_reasoning=chunk.delta_reasoning,
                delta_tool_calls=[],
                finish_reason=chunk.finish_reason,
                usage=chunk.usage,
            )

        # Stream is over — flush every buffered call. An empty argument string
        # means the model sent no arguments ({} is the correct reading);
        # truncated JSON surfaces as {} too, and the harness's schema
        # validation turns that into a recoverable error for the model.
        if buf:
            completed = [
                ToolCall(
                    id=entry["id"] or f"call_{index}",
                    name=entry["name"] or f"unknown_tool_{index}",
                    arguments=_parse_arguments(entry["args"]),
                )
                for index, entry in sorted(buf.items())
            ]
            buf.clear()
            yield StreamChunk(delta_tool_calls=completed, finish_reason=finish_seen)

    # ---- payload construction --------------------------------------------

    def _env(self, suffix: str) -> str | None:
        return os.environ.get(f"LOCA_{self.name.upper()}_{suffix}") or None

    def _build_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self._default_model,
            "messages": [m.to_openai() for m in request.messages],
            "stream": stream,
        }
        if stream and self.stream_usage:
            payload["stream_options"] = {"include_usage": True}
        if request.tools:
            payload["tools"] = request.tools
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        return payload

    # ---- response parsing (duck-typed, so it is testable offline) ---------

    def parse_response(self, resp: Any) -> ChatResponse:
        """Map a non-streaming completion onto loca's types."""
        choice = resp.choices[0]
        msg = choice.message
        message = Message(
            role=Role.ASSISTANT,
            content=msg.content or "",
            tool_calls=self.parse_tool_calls(msg),
            reasoning_content=getattr(msg, "reasoning_content", None),
        )
        return ChatResponse(
            message=message,
            finish_reason=map_finish_reason(choice.finish_reason),
            usage=parse_usage(getattr(resp, "usage", None)),
        )

    def parse_stream_chunk(self, raw: Any) -> StreamChunk:
        """Map one streamed delta onto a :class:`StreamChunk`.

        ``finish_reason`` is only mapped when the provider actually sent one.
        Every frame but the last carries ``None``, and a consumer that watches
        ``finish_reason`` for end-of-stream — which
        :mod:`loca.providers.types` documents as the contract — would otherwise
        see ``ERROR`` on the very first frame and stop. Unknown *strings* are
        still reported as :attr:`FinishReason.ERROR`.
        """
        choice = raw.choices[0] if raw.choices else None
        delta = choice.delta if choice else None
        return StreamChunk(
            delta_content=getattr(delta, "content", "") or "",
            delta_reasoning=getattr(delta, "reasoning_content", "") or "",
            delta_tool_calls=[],  # assembled by stream_chat, never per-fragment
            finish_reason=(
                map_finish_reason(choice.finish_reason)
                if choice is not None and choice.finish_reason
                else None
            ),
            usage=parse_usage(getattr(raw, "usage", None)),
        )

    def parse_tool_calls(self, raw_msg: Any) -> list[ToolCall]:
        """Fully-formed tool calls on a message (non-streaming path)."""
        out: list[ToolCall] = []
        for tc in getattr(raw_msg, "tool_calls", None) or []:
            raw_args = getattr(tc.function, "arguments", None) if tc.function else None
            if raw_args is None or raw_args == "":
                # Streaming has not filled the arguments yet. Don't substitute
                # an empty dict — that would let the accumulator treat a
                # half-formed call as complete.
                continue
            if isinstance(raw_args, dict):
                out.append(ToolCall(id=tc.id, name=tc.function.name, arguments=raw_args))
                continue
            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError:
                continue
            out.append(ToolCall(id=tc.id, name=tc.function.name, arguments=parsed))
        return out

    def _merge_tool_deltas(self, buf: dict[int, dict[str, Any]], raw: Any) -> None:
        """Fold this chunk's tool-call fragments into ``buf``."""
        choice = raw.choices[0] if raw.choices else None
        deltas = getattr(getattr(choice, "delta", None), "tool_calls", None) or []
        for delta in deltas:
            index = getattr(delta, "index", None)
            if index is None:
                # Some SDKs omit ``index`` for the single-call case.
                index = max(buf) if buf else 0
            entry = buf.setdefault(
                index, {"id": "", "name": "", "args": "", "args_is_str": False}
            )
            if getattr(delta, "id", None):
                entry["id"] = delta.id
            function = getattr(delta, "function", None)
            if function is not None and function.name:
                entry["name"] = function.name
            if function is not None and function.arguments is not None:
                raw_arg = function.arguments
                if isinstance(raw_arg, dict):
                    # The provider already assembled the dict (this happens when
                    # the SDK's first delta carries the whole payload).
                    if not entry["args"]:
                        entry["args"] = json.dumps(raw_arg, ensure_ascii=False)
                elif entry["args_is_str"]:
                    entry["args"] += raw_arg
                else:
                    entry["args"] = raw_arg
                    entry["args_is_str"] = True


# ---------------------------------------------------------------------------
# Shared parsing helpers
# ---------------------------------------------------------------------------


def _parse_arguments(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_usage(raw: Any) -> Usage | None:
    """Map an OpenAI ``usage`` object onto :class:`Usage` (``None`` if absent)."""
    if raw is None:
        return None
    details = getattr(raw, "completion_tokens_details", None)
    return Usage(
        prompt_tokens=getattr(raw, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(raw, "completion_tokens", 0) or 0,
        total_tokens=getattr(raw, "total_tokens", 0) or 0,
        reasoning_tokens=getattr(details, "reasoning_tokens", 0) or 0,
    )


_FINISH_REASONS: dict[str, FinishReason] = {
    "stop": FinishReason.STOP,
    "tool_calls": FinishReason.TOOL_USE,
    "function_call": FinishReason.TOOL_USE,
    "length": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}


def map_finish_reason(raw: str | None) -> FinishReason:
    """Map a ``finish_reason`` the provider actually sent onto loca's enum.

    An unrecognised non-empty string is :attr:`FinishReason.ERROR` — something
    stopped generation for a reason we do not model, and saying "stop" would be
    a lie.

    ``None`` is *not* a finish reason: it means "this frame says nothing about
    why generation ended". This function has to return something, so ``None``
    falls back to ``ERROR`` as well; callers on a streaming path must therefore
    guard the call rather than lean on that default (see
    :meth:`OpenAICompatibleProvider.parse_stream_chunk`).
    """
    return _FINISH_REASONS.get(raw or "", FinishReason.ERROR)


__all__ = [
    "BASE_URL_ENV_SUFFIX",
    "MODEL_ENV_SUFFIX",
    "STREAM_USAGE_ENV_SUFFIX",
    "OpenAICompatibleProvider",
    "map_finish_reason",
    "parse_usage",
]
