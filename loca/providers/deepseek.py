"""DeepSeek provider.

DeepSeek exposes an OpenAI-compatible Chat Completions API. We use the official
``openai`` SDK pointed at DeepSeek's base URL, then translate responses into
loca's vendor-neutral types.

DeepSeek-specific behavior to be aware of:

- ``reasoning_content`` is delivered alongside ``content`` for thinking models
  (DeepSeek-R1). We forward it into ``Message.reasoning_content`` so the
  harness can display it separately without mixing it into user-visible text.
- Tool calls use the same JSON-Schema-driven function-calling protocol as
  OpenAI.
"""

from __future__ import annotations

import json
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

_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-chat"


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        default_model: str = _DEFAULT_MODEL,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("DeepSeekProvider requires a non-empty api_key.")
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._default_model = default_model

    # ---- public API ------------------------------------------------------

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = self._build_payload(request, stream=False)
        resp = self._client.chat.completions.create(**payload)
        return self._parse_response(resp)

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        """Stream the response, **assembling tool calls in full** before yielding.

        The OpenAI streaming protocol delivers tool-call arguments as
        string fragments keyed by an ``index`` (in the raw delta). We
        merge them inside this provider so the rest of the harness can
        treat a ``StreamChunk`` as a discrete atomic update.
        """
        import json as _json

        payload = self._build_payload(request, stream=True)
        stream = self._client.chat.completions.create(**payload)
        # index -> {"id": str, "name": str, "args": str}
        buf: dict[int, dict[str, str]] = {}
        finish_seen: FinishReason | None = None
        for raw in stream:
            chunk = self._parse_stream_chunk(raw)
            if chunk.finish_reason is not None:
                finish_seen = chunk.finish_reason
            choice = raw.choices[0] if raw.choices else None
            delta_calls_raw = getattr(getattr(choice, "delta", None), "tool_calls", None) or []
            for delta in delta_calls_raw:
                # OpenAI's ChoiceDeltaToolCall exposes ``index`` (int) we
                # use to merge successive fragments for the same call. When
                # ``index`` is missing we fold into the most recent entry
                # (the simpler case of one tool call at a time).
                idx = getattr(delta, "index", None)
                if idx is None:
                    if not buf:
                        idx = 0
                    else:
                        idx = max(buf)
                if idx not in buf:
                    buf[idx] = {"id": "", "name": "", "args": "", "args_is_str": False}
                if delta.id:
                    buf[idx]["id"] = delta.id
                if delta.function and delta.function.name:
                    buf[idx]["name"] = delta.function.name
                if delta.function and delta.function.arguments is not None:
                    raw_arg = delta.function.arguments
                    if isinstance(raw_arg, dict):
                        # The provider already assembled the dict (this
                        # happens when the SDK's stream delta carries the
                        # full payload in the first chunk).
                        if not buf[idx]["args"]:
                            buf[idx]["args"] = _json.dumps(
                                raw_arg, ensure_ascii=False
                            )
                    else:
                        # String fragment. If the previous content was a
                        # serialized dict, replace it; otherwise append.
                        if buf[idx]["args_is_str"]:
                            buf[idx]["args"] += raw_arg
                        else:
                            buf[idx]["args"] = raw_arg
                            buf[idx]["args_is_str"] = True

            # No mid-stream draining: id/name usually arrive one chunk before
            # the argument fragments, and flushing as soon as the fragment
            # happens to parse would emit a call with empty (or truncated)
            # arguments. Buffer until the stream signals completion, then
            # flush everything below. In-progress fragments are never
            # forwarded, so the harness only ever sees whole calls.

            yield StreamChunk(
                delta_content=chunk.delta_content,
                delta_reasoning=chunk.delta_reasoning,
                delta_tool_calls=[],
                finish_reason=chunk.finish_reason,
                usage=chunk.usage,
            )

        # Stream is over — flush every buffered call. Empty argument strings
        # mean the model sent no arguments ({} is the correct reading);
        # truncated JSON surfaces as {} too, and the harness's schema
        # validation turns that into a recoverable error for the model.
        if buf:
            completed: list[ToolCall] = []
            for k in sorted(buf):
                entry = buf[k]
                try:
                    parsed = _json.loads(entry["args"]) if entry["args"] else {}
                except _json.JSONDecodeError:
                    parsed = {}
                completed.append(
                    ToolCall(
                        id=entry["id"] or f"call_{k}",
                        name=entry["name"] or f"unknown_tool_{k}",
                        arguments=parsed,
                    )
                )
            buf = {}
            yield StreamChunk(
                delta_tool_calls=completed,
                finish_reason=finish_seen,
            )

    # ---- payload construction --------------------------------------------

    def _build_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        messages = [m.to_openai() for m in request.messages]
        tools = request.tools or None
        payload: dict[str, Any] = {
            "model": request.model or self._default_model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        return payload

    # ---- response parsing ------------------------------------------------

    def _parse_response(self, resp: Any) -> ChatResponse:
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = self._parse_tool_calls(msg)
        message = Message(
            role=Role.ASSISTANT,
            content=msg.content or "",
            tool_calls=tool_calls,
            reasoning_content=getattr(msg, "reasoning_content", None),
        )
        finish = self._map_finish_reason(choice.finish_reason)
        usage = Usage(
            prompt_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(resp.usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(resp.usage, "total_tokens", 0) or 0,
        )
        return ChatResponse(message=message, finish_reason=finish, usage=usage)

    def _parse_stream_chunk(self, raw: Any) -> StreamChunk:
        choice = raw.choices[0] if raw.choices else None
        delta = choice.delta if choice else None
        delta_content = getattr(delta, "content", "") or ""
        delta_reasoning = getattr(delta, "reasoning_content", "") or ""
        delta_tool_calls = self._parse_tool_calls(delta)
        finish = self._map_finish_reason(choice.finish_reason) if choice else None
        usage = None
        if getattr(raw, "usage", None):
            usage = Usage(
                prompt_tokens=getattr(raw.usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(raw.usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(raw.usage, "total_tokens", 0) or 0,
            )
        return StreamChunk(
            delta_content=delta_content,
            delta_reasoning=delta_reasoning,
            delta_tool_calls=delta_tool_calls,
            finish_reason=finish,
            usage=usage,
        )

    def _parse_tool_calls(self, raw_msg: Any) -> list[ToolCall]:
        raw_calls = getattr(raw_msg, "tool_calls", None) or []
        out: list[ToolCall] = []
        for tc in raw_calls:
            raw_args = getattr(tc.function, "arguments", None) if tc.function else None
            if raw_args is None or raw_args == "":
                # Streaming hasn't filled the arguments yet. Don't
                # substitute an empty dict here — that would let the
                # tool-call accumulator treat a half-formed call as
                # complete and emit ``arguments={}`` to the harness.
                continue
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                # Incomplete JSON fragment from streaming. Skip; the
                # accumulator will pick up the next chunk.
                continue
            out.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return out

    def _map_finish_reason(self, raw: str | None) -> FinishReason:
        mapping = {
            "stop": FinishReason.STOP,
            "tool_calls": FinishReason.TOOL_USE,
            "length": FinishReason.LENGTH,
            "content_filter": FinishReason.CONTENT_FILTER,
        }
        return mapping.get(raw or "", FinishReason.ERROR)
