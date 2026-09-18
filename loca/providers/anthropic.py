"""Anthropic provider, speaking the Messages API.

Anthropic is *not* OpenAI-compatible, so this module is a genuine translation
layer rather than a base-URL change. The differences that matter:

======================  ==============================  ==========================
Concept                 OpenAI / DeepSeek               Anthropic Messages
======================  ==============================  ==========================
system prompt           a ``system`` message            a top-level ``system`` param
tool result             a ``tool`` message              a ``tool_result`` block inside
                                                        a **user** message
assistant tool call     ``tool_calls[]``                a ``tool_use`` content block
tool schema             ``{type,function:{…}}``         ``{name,description,input_schema}``
token counts            ``prompt/completion_tokens``    ``input_tokens`` / ``output_tokens``
streamed tool args      ``function.arguments`` fragments  ``input_json_delta.partial_json``
required field          —                               ``max_tokens`` (always)
======================  ==============================  ==========================

The translation itself is written as **pure functions** over duck-typed
objects (:func:`to_anthropic_messages`, :func:`from_anthropic_message`,
:func:`iter_stream_events`). Two consequences, both deliberate:

* it can be tested completely offline — no SDK, no key, no network;
* the SDK only ever appears in :meth:`AnthropicProvider.__init__`, so the
  ``anthropic`` package stays an optional dependency until someone actually
  configures a key.

Streaming follows the same contract as the OpenAI-compatible providers: tool
calls are buffered and only emitted **fully assembled** (at
``content_block_stop``), never as half-written JSON.

Extension thinking blocks (``thinking_delta``) are forwarded as
``delta_reasoning`` — the same channel DeepSeek uses for
``reasoning_content`` — so a UI has one place to render "the model's private
work" regardless of vendor.

Overrides: ``LOCA_ANTHROPIC_BASE_URL`` and ``LOCA_ANTHROPIC_MODEL``. The default
model is a moving target, so pin it explicitly if you have access to a specific
one.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

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

#: The Messages API rejects a request without ``max_tokens``. This is the
#: fallback when neither the request nor the caller names one.
DEFAULT_MAX_TOKENS = 4096

_STOP_REASONS: dict[str, FinishReason] = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "pause_turn": FinishReason.STOP,
    "tool_use": FinishReason.TOOL_USE,
    "max_tokens": FinishReason.LENGTH,
    "refusal": FinishReason.CONTENT_FILTER,
}


# ---------------------------------------------------------------------------
# Field access that works on both SDK objects and plain dicts
# ---------------------------------------------------------------------------


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` off an attribute or a mapping — tests use plain dicts."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_json(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # A truncated argument stream. Returning {} lets the harness's schema
        # validation turn it into a recoverable error the model can fix.
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# loca -> Anthropic
# ---------------------------------------------------------------------------


def to_anthropic_messages(messages: Sequence[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Convert loca messages into ``(system_prompt, anthropic_messages)``.

    Roles are collapsed the way the Messages API expects: systems are lifted
    out, tool results become ``tool_result`` blocks inside user turns, and
    consecutive same-role turns are merged (an assistant that called two tools
    in a row must not become two assistant messages).
    """
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []

    for message in messages:
        role = message.role

        if role is Role.SYSTEM:
            if message.content:
                system_parts.append(message.content)
            continue

        if role is Role.TOOL:
            _merge(
                out,
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id or "",
                        "content": message.content or "",
                    }
                ],
            )
            continue

        if role is Role.ASSISTANT:
            blocks: list[dict[str, Any]] = []
            if message.content and message.content.strip():
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments or {},
                    }
                )
            # The API rejects an empty content array. A tool-only assistant
            # turn is normal for us, so give it the same benign placeholder the
            # OpenAI path uses.
            _merge(out, "assistant", blocks or [{"type": "text", "text": " "}])
            continue

        _merge(out, "user", [{"type": "text", "text": message.content or " "}])

    return "\n\n".join(system_parts), out


def _merge(out: list[dict[str, Any]], role: str, blocks: list[dict[str, Any]]) -> None:
    """Append blocks, folding into the previous turn when the role matches."""
    if out and out[-1]["role"] == role:
        out[-1]["content"].extend(blocks)
    else:
        out.append({"role": role, "content": list(blocks)})


def to_anthropic_tools(tools: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI-shaped tool schemas into Anthropic's ``input_schema`` form.

    Accepts both the wrapped (``{type:function, function:{…}}``) and the bare
    (``{name, description, input_schema}``) shape so it can be handed either.
    """
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        source = function if isinstance(function, dict) else tool
        name = source.get("name")
        if not name:
            continue
        schema = source.get("input_schema") or source.get("parameters") or {
            "type": "object",
            "properties": {},
        }
        converted.append(
            {
                "name": name,
                "description": source.get("description") or "",
                "input_schema": schema,
            }
        )
    return converted


# ---------------------------------------------------------------------------
# Anthropic -> loca
# ---------------------------------------------------------------------------


def from_anthropic_message(payload: Any) -> ChatResponse:
    """Map a non-streaming ``Message`` onto :class:`ChatResponse`."""
    text, thinking, calls = extract_content(_field(payload, "content"))
    return ChatResponse(
        message=Message(
            role=Role.ASSISTANT,
            content=text,
            tool_calls=calls,
            reasoning_content=thinking or None,
        ),
        finish_reason=map_stop_reason(_field(payload, "stop_reason")),
        usage=parse_usage(_field(payload, "usage")) or Usage(),
    )


def extract_content(blocks: Any) -> tuple[str, str, list[ToolCall]]:
    """Pull ``(text, thinking, tool_calls)`` out of a content-block list."""
    texts: list[str] = []
    thinking: list[str] = []
    calls: list[ToolCall] = []
    for block in blocks or []:
        kind = _field(block, "type", "")
        if kind == "text":
            texts.append(_field(block, "text", "") or "")
        elif kind == "thinking":
            thinking.append(_field(block, "thinking", "") or "")
        elif kind == "tool_use":
            calls.append(
                ToolCall(
                    id=_field(block, "id", "") or "",
                    name=_field(block, "name", "") or "",
                    arguments=_as_dict(_field(block, "input")),
                )
            )
    return "".join(texts), "".join(thinking), calls


def iter_stream_events(events: Iterable[Any]) -> Iterator[StreamChunk]:
    """Translate a raw Anthropic event stream into loca :class:`StreamChunk`\\ s.

    Pure: feed it any iterable of duck-typed events (the SDK's objects in
    production, plain dicts in a test) and it yields what the harness consumes.
    Tool calls are emitted at ``content_block_stop``, once their
    ``input_json_delta`` fragments are complete — never as half-written JSON.
    """
    blocks: dict[int, dict[str, Any]] = {}
    prompt = 0
    completion = 0
    stop_reason: FinishReason | None = None

    for event in events:
        kind = _field(event, "type", "")
        index = int(_field(event, "index", 0) or 0)

        if kind == "error":
            raise RuntimeError(f"anthropic stream error: {_field(event, 'error', event)}")

        if kind == "message_start":
            usage = _field(_field(event, "message"), "usage")
            if usage is not None:
                prompt = prompt_tokens(usage)

        elif kind == "content_block_start":
            block = _field(event, "content_block")
            entry = {
                "type": _field(block, "type", ""),
                "id": _field(block, "id", "") or "",
                "name": _field(block, "name", "") or "",
                "json": "",
            }
            initial = _as_dict(_field(block, "input"))
            if initial:
                entry["json"] = json.dumps(initial, ensure_ascii=False)
            blocks[index] = entry
            text = _field(block, "text", "") or ""
            thinking = _field(block, "thinking", "") or ""
            if text or thinking:
                yield StreamChunk(delta_content=text, delta_reasoning=thinking)

        elif kind == "content_block_delta":
            delta = _field(event, "delta")
            delta_type = _field(delta, "type", "")
            if delta_type == "text_delta":
                text = _field(delta, "text", "") or ""
                if text:
                    yield StreamChunk(delta_content=text)
            elif delta_type == "thinking_delta":
                text = _field(delta, "thinking", "") or ""
                if text:
                    yield StreamChunk(delta_reasoning=text)
            elif delta_type == "input_json_delta":
                entry = blocks.setdefault(
                    index, {"type": "tool_use", "id": "", "name": "", "json": ""}
                )
                entry["json"] += _field(delta, "partial_json", "") or ""

        elif kind == "content_block_stop":
            entry = blocks.pop(index, None)
            if entry and entry.get("type") == "tool_use" and entry.get("name"):
                yield StreamChunk(
                    delta_tool_calls=[
                        ToolCall(
                            id=entry.get("id") or f"toolu_{index}",
                            name=entry["name"],
                            arguments=_parse_json(entry.get("json", "")),
                        )
                    ]
                )

        elif kind == "message_delta":
            raw_reason = _field(_field(event, "delta"), "stop_reason")
            if raw_reason:
                stop_reason = map_stop_reason(raw_reason)
            usage = _field(event, "usage")
            if usage is not None:
                completion = int(_field(usage, "output_tokens", 0) or 0)

    yield StreamChunk(
        finish_reason=stop_reason or FinishReason.STOP,
        usage=Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        ),
    )


def prompt_tokens(usage: Any) -> int:
    """Anthropic splits the prompt across plain and cached input counters.

    All three are prompt tokens as far as a token budget is concerned, so they
    are summed — reporting only ``input_tokens`` would understate the cost of a
    long cached conversation.
    """
    return sum(
        int(_field(usage, name, 0) or 0)
        for name in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )


def parse_usage(raw: Any) -> Usage | None:
    """Map an Anthropic ``usage`` object onto :class:`Usage`."""
    if raw is None:
        return None
    prompt = prompt_tokens(raw)
    completion = int(_field(raw, "output_tokens", 0) or 0)
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def map_stop_reason(raw: str | None) -> FinishReason:
    """Map an Anthropic ``stop_reason`` onto loca's enum."""
    return _STOP_REASONS.get(raw or "", FinishReason.ERROR)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class AnthropicProvider(LLMProvider):
    """Claude models over the Messages API.

    The ``anthropic`` package is imported lazily: without a key it is never
    needed, so it can stay out of the core dependency list.
    """

    name = "anthropic"
    default_model = "claude-sonnet-4-5"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: float = 120.0,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "AnthropicProvider requires a non-empty api_key "
                "(set LOCA_ANTHROPIC_API_KEY)."
            )
        self._default_model = (
            default_model or os.environ.get("LOCA_ANTHROPIC_MODEL") or self.default_model
        )
        if client is not None:
            # Injected transport (tests, or a caller sharing one client).
            self._client = client
            return

        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError(
                "the 'anthropic' package is not installed. Install it with "
                '`pip install "loca[anthropic]"` (or `pip install anthropic`).'
            ) from exc

        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout}
        resolved_base_url = base_url or os.environ.get("LOCA_ANTHROPIC_BASE_URL")
        if resolved_base_url:
            kwargs["base_url"] = resolved_base_url
        self._client = anthropic.Anthropic(**kwargs)

    # ---- public API ------------------------------------------------------

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = self.build_payload(request, stream=False)
        return from_anthropic_message(self._client.messages.create(**payload))

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        """Stream, emitting tool calls only once their JSON is complete."""
        stream = self._client.messages.create(**self.build_payload(request, stream=True))
        yield from iter_stream_events(stream)

    # ---- payload construction --------------------------------------------

    def build_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        system, messages = to_anthropic_messages(request.messages)
        payload: dict[str, Any] = {
            "model": request.model or self._default_model,
            # Always required by the Messages API — never omit it.
            "max_tokens": request.max_tokens or DEFAULT_MAX_TOKENS,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = to_anthropic_tools(request.tools)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if stream:
            payload["stream"] = True
        return payload


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "AnthropicProvider",
    "extract_content",
    "from_anthropic_message",
    "iter_stream_events",
    "map_stop_reason",
    "parse_usage",
    "prompt_tokens",
    "to_anthropic_messages",
    "to_anthropic_tools",
]
