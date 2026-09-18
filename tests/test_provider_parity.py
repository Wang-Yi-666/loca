"""Week-5 acceptance: the providers are interchangeable on the same task.

The claim “loca talks to a vendor-neutral interface” is only worth anything if
switching vendors does not change what the harness sees. These tests take one
task — *call a tool, then answer* — express it in three wire formats (OpenAI
Chat Completions, DeepSeek's identical variant, Anthropic Messages) and assert
the loop produces the same run.

All offline: the SDKs are replaced by tiny fakes with the same shape.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from loca.core.events import AgentEvent, EventType
from loca.core.loop import AgentLoop
from loca.providers import LLMProvider
from loca.providers.anthropic import AnthropicProvider, to_anthropic_tools
from loca.providers.deepseek import DeepSeekProvider
from loca.providers.openai import OpenAIProvider
from loca.providers.openai_compat import OpenAICompatibleProvider
from loca.providers.registry import get_provider
from loca.providers.types import (
    ChatRequest,
    FinishReason,
    Message,
    Role,
    StreamChunk,
    ToolCall,
    Usage,
)
from loca.tools.base import Tool, ToolContext, ToolResult

# ---------------------------------------------------------------------------
# OpenAI-compatible SDK fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeFunction:
    name: str | None = None
    arguments: str | None = None


@dataclass
class FakeDeltaToolCall:
    index: int | None = None
    id: str | None = None
    function: FakeFunction | None = None


@dataclass
class FakeDelta:
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[Any] = field(default_factory=list)


@dataclass
class FakeChoice:
    delta: FakeDelta
    finish_reason: str | None = None
    message: Any = None


@dataclass
class FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    completion_tokens_details: Any = None


@dataclass
class FakeRawChunk:
    choices: list[Any]
    usage: Any = None


class FakeCompletions:
    """Returns a scripted chunk stream per ``create`` call."""

    def __init__(self, scripts: list[list[Any]]) -> None:
        self._scripts = list(scripts)
        self._call = 0
        self.payloads: list[dict[str, Any]] = []

    def create(self, **payload: Any) -> Any:
        self.payloads.append(payload)
        script = self._scripts[min(self._call, len(self._scripts) - 1)]
        self._call += 1
        return iter(script)


class FakeOpenAIClient:
    def __init__(self, scripts: list[list[Any]]) -> None:
        self.chat = type("Chat", (), {"completions": FakeCompletions(scripts)})()


@dataclass
class FakeMessageToolCall:
    """A fully-formed ``tool_calls[]`` entry on a non-streaming message."""

    id: str
    function: FakeFunction


@dataclass
class FakeCompletionMessage:
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[Any] = field(default_factory=list)


@dataclass
class FakeCompletionResponse:
    message: FakeCompletionMessage
    finish_reason: str
    usage: Any = None

    @property
    def choices(self) -> list[Any]:
        return [FakeChoice(FakeDelta(), self.finish_reason, message=self.message)]


class FakeNonStreamingClient:
    """An OpenAI-compatible client whose ``create`` always returns one response."""

    def __init__(self, response: Any) -> None:
        completions = type("Completions", (), {"create": staticmethod(lambda **_: response)})()
        self.chat = type("Chat", (), {"completions": completions})()


class FakeNonStreamingAnthropicClient:
    def __init__(self, response: Any) -> None:
        self.messages = type("Messages", (), {"create": staticmethod(lambda **_: response)})()


def _delta(**fields: Any) -> FakeDelta:
    return FakeDelta(**fields)


def _chunk(delta: FakeDelta, finish: str | None = None, usage: Any = None) -> FakeRawChunk:
    return FakeRawChunk([FakeChoice(delta, finish)], usage=usage)


def _tool_fragment(index: int, *, call_id: str | None = None, name: str | None = None,
                   arguments: str | None = None) -> FakeDeltaToolCall:
    return FakeDeltaToolCall(index, call_id, FakeFunction(name, arguments))


def _openai_tool_script() -> list[Any]:
    """A tool call delivered as fragments, then a final text answer."""
    return [
        [
            _chunk(_delta()),
            _chunk(_delta(tool_calls=[_tool_fragment(0, call_id="c1", name="echo")])),
            _chunk(_delta(tool_calls=[_tool_fragment(0, arguments='{"text":')])),
            _chunk(_delta(tool_calls=[_tool_fragment(0, arguments=' "hi"}')])),
            _chunk(
                _delta(),
                finish="tool_calls",
                usage=FakeUsage(prompt_tokens=30, completion_tokens=12, total_tokens=42),
            ),
        ],
        [
            _chunk(
                _delta(content="done"),
                finish="stop",
                usage=FakeUsage(prompt_tokens=50, completion_tokens=5, total_tokens=55),
            )
        ],
    ]


# ---------------------------------------------------------------------------
# Anthropic SDK fakes
# ---------------------------------------------------------------------------


def _ev(kind: str, **fields: Any) -> dict[str, Any]:
    return {"type": kind, **fields}


def _block_start(index: int, block: dict[str, Any]) -> dict[str, Any]:
    return _ev("content_block_start", index=index, content_block=block)


def _json_delta(index: int, partial: str) -> dict[str, Any]:
    return _ev(
        "content_block_delta",
        index=index,
        delta={"type": "input_json_delta", "partial_json": partial},
    )


def _text_delta(index: int, text: str) -> dict[str, Any]:
    return _ev("content_block_delta", index=index, delta={"type": "text_delta", "text": text})


def _anthropic_tool_script() -> list[list[dict[str, Any]]]:
    """The same answer, expressed as Messages API events."""
    return [
        [
            _ev("message_start", message={"usage": {"input_tokens": 30}}),
            _block_start(0, {"type": "tool_use", "id": "c1", "name": "echo", "input": {}}),
            _json_delta(0, '{"text":'),
            _json_delta(0, ' "hi"}'),
            _ev("content_block_stop", index=0),
            _ev("message_delta", delta={"stop_reason": "tool_use"}, usage={"output_tokens": 12}),
            _ev("message_stop"),
        ],
        [
            _ev("message_start", message={"usage": {"input_tokens": 50}}),
            _block_start(0, {"type": "text", "text": ""}),
            _text_delta(0, "done"),
            _ev("content_block_stop", index=0),
            _ev("message_delta", delta={"stop_reason": "end_turn"}, usage={"output_tokens": 5}),
            _ev("message_stop"),
        ],
    ]


class FakeAnthropicMessages:
    def __init__(self, scripts: list[list[dict[str, Any]]]) -> None:
        self._scripts = list(scripts)
        self._call = 0
        self.payloads: list[dict[str, Any]] = []

    def create(self, **payload: Any) -> Any:
        self.payloads.append(payload)
        if not self._scripts:
            return iter([])
        script = self._scripts[min(self._call, len(self._scripts) - 1)]
        self._call += 1
        return iter(script)


class FakeAnthropicClient:
    def __init__(self, scripts: list[list[dict[str, Any]]]) -> None:
        self.messages = FakeAnthropicMessages(scripts)


# ---------------------------------------------------------------------------
# Shared task
# ---------------------------------------------------------------------------


class EchoTool(Tool):
    name = "echo"
    description = "Echo text back."
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(content=f"echo: {arguments['text']}")


def _run(provider: LLMProvider, workspace: Any) -> list[AgentEvent]:
    loop = AgentLoop(provider=provider, tools=[EchoTool()], context_token_budget=None)
    ctx = ToolContext(workspace=workspace, session_id="parity", step_index=0)
    return list(loop.run(ctx, user_message="echo hi and tell me"))


def _summary(events: list[AgentEvent]) -> dict[str, Any]:
    """The facts a user would notice, independent of transport."""
    kinds = [event.type.value for event in events]
    tool_calls = [e.data for e in events if e.type is EventType.TOOL_CALL]
    tool_results = [e.data for e in events if e.type is EventType.TOOL_RESULT]
    done = next(e.data for e in events if e.type is EventType.DONE)
    return {
        "kinds": kinds,
        "text": "".join(e.data["content"] for e in events if e.type is EventType.TEXT_DELTA),
        "tool_calls": [(c["name"], c["arguments"]) for c in tool_calls],
        "tool_results": [(r["name"], r["content"], r["is_error"]) for r in tool_results],
        "usage": [e.data for e in events if e.type is EventType.USAGE],
        "done": done,
    }


# ---------------------------------------------------------------------------
# Same tool, three schemas
# ---------------------------------------------------------------------------


def test_the_same_tool_is_described_consistently() -> None:
    tool = EchoTool()

    openai_form = tool.to_openai_tool()
    anthropic_form = to_anthropic_tools([openai_form])[0]

    assert openai_form["function"]["name"] == anthropic_form["name"] == "echo"
    assert openai_form["function"]["description"] == anthropic_form["description"]
    # ``parameters`` (OpenAI) and ``input_schema`` (Anthropic) are the same JSON
    # Schema — that is what lets one tool list serve both.
    assert openai_form["function"]["parameters"] == anthropic_form["input_schema"]


# ---------------------------------------------------------------------------
# Same response, two wire formats
# ---------------------------------------------------------------------------


def test_openai_and_deepseek_build_identical_payloads() -> None:
    """DeepSeek *is* the OpenAI protocol — only the endpoint and default differ."""
    request = ChatRequest(
        messages=[Message(role=Role.USER, content="hi")],
        tools=[EchoTool().to_openai_tool()],
        model="same-model",
        temperature=0.3,
    )
    deepseek = DeepSeekProvider(api_key="sk-test", client=FakeOpenAIClient([]))
    openai = OpenAIProvider(api_key="sk-test", client=FakeOpenAIClient([]))

    assert deepseek._build_payload(request, stream=True) == openai._build_payload(
        request, stream=True
    )


def test_openai_and_deepseek_differ_only_in_defaults() -> None:
    assert issubclass(OpenAIProvider, OpenAICompatibleProvider)
    assert issubclass(DeepSeekProvider, OpenAICompatibleProvider)
    assert OpenAIProvider.default_base_url != DeepSeekProvider.default_base_url
    assert OpenAIProvider.default_model != DeepSeekProvider.default_model
    assert DeepSeekProvider.name == "deepseek"
    assert OpenAIProvider.name == "openai"


def test_openai_endpoint_and_model_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCA_OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LOCA_OPENAI_MODEL", "llama3")

    provider = OpenAIProvider(api_key="sk-test", client=FakeOpenAIClient([]))
    request = ChatRequest(messages=[Message(role=Role.USER, content="hi")])

    assert provider._default_model == "llama3"
    assert provider._build_payload(request, stream=False)["model"] == "llama3"


def test_an_explicit_model_beats_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCA_OPENAI_MODEL", "llama3")
    provider = OpenAIProvider(api_key="sk-test", client=FakeOpenAIClient([]))

    payload = provider._build_payload(
        ChatRequest(messages=[Message(role=Role.USER, content="hi")], model="gpt-4o"),
        stream=False,
    )

    assert payload["model"] == "gpt-4o"


def test_openai_compatible_provider_rejects_an_empty_key() -> None:
    with pytest.raises(ValueError, match="LOCA_OPENAI_API_KEY"):
        OpenAIProvider(api_key="")


# ---------------------------------------------------------------------------
# Same run, three providers
# ---------------------------------------------------------------------------


def test_non_streaming_responses_agree() -> None:
    """One logical answer, two wire payloads, one loca-level result."""
    compat = OpenAIProvider(
        api_key="sk-test",
        client=FakeNonStreamingClient(
            FakeCompletionResponse(
                message=FakeCompletionMessage(
                    content="on it",
                    tool_calls=[
                        FakeMessageToolCall("c1", FakeFunction("echo", '{"text": "hi"}'))
                    ],
                ),
                finish_reason="tool_calls",
                usage=FakeUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
            )
        ),
    )
    anthropic = AnthropicProvider(
        api_key="sk-test",
        client=FakeNonStreamingAnthropicClient(
            {
                "content": [
                    {"type": "text", "text": "on it"},
                    {"type": "tool_use", "id": "c1", "name": "echo", "input": {"text": "hi"}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 10, "output_tokens": 4},
            }
        ),
    )

    request = ChatRequest(messages=[Message(role=Role.USER, content="go")])
    from_compat = compat.chat(request)
    from_anthropic = anthropic.chat(request)

    assert from_compat.message.content == from_anthropic.message.content == "on it"
    assert from_compat.message.tool_calls == from_anthropic.message.tool_calls
    assert from_compat.finish_reason is from_anthropic.finish_reason is FinishReason.TOOL_USE
    assert from_compat.usage == from_anthropic.usage == Usage(10, 4, 14)


def test_streaming_usage_and_tool_calls_agree() -> None:
    compat = OpenAIProvider(
        api_key="sk-test", client=FakeOpenAIClient(_openai_tool_script())
    )
    anthropic = AnthropicProvider(
        api_key="sk-test", client=FakeAnthropicClient(_anthropic_tool_script())
    )
    request = ChatRequest(messages=[Message(role=Role.USER, content="go")])

    def assemble(provider: LLMProvider) -> dict[str, Any]:
        text = ""
        calls: list[ToolCall] = []
        finish: FinishReason | None = None
        usage: Usage | None = None
        for chunk in provider.stream_chat(request):
            text += chunk.delta_content
            calls.extend(chunk.delta_tool_calls)
            finish = chunk.finish_reason or finish
            usage = chunk.usage or usage
        return {"text": text, "calls": calls, "finish": finish, "usage": usage}

    left = assemble(compat)
    right = assemble(anthropic)

    assert left["calls"] == right["calls"] == [
        ToolCall(id="c1", name="echo", arguments={"text": "hi"})
    ]
    assert left["finish"] is right["finish"] is FinishReason.TOOL_USE
    assert left["usage"] == right["usage"] == Usage(30, 12, 42)


def test_the_loop_runs_identically_on_both_protocols(workspace: Any) -> None:
    """The real acceptance test: swap the provider, keep the run."""
    compat = OpenAIProvider(api_key="sk-test", client=FakeOpenAIClient(_openai_tool_script()))
    anthropic = AnthropicProvider(
        api_key="sk-test", client=FakeAnthropicClient(_anthropic_tool_script())
    )

    from_compat = _summary(_run(compat, workspace))
    from_anthropic = _summary(_run(anthropic, workspace))

    assert from_compat == from_anthropic
    # And the shared run is the one we meant to script.
    assert from_compat["tool_calls"] == [("echo", {"text": "hi"})]
    assert from_compat["tool_results"] == [("echo", "echo: hi", False)]
    assert from_compat["done"]["reason"] == "stop"
    assert from_compat["done"]["total_tokens"] == 42 + 55


def test_anthropic_payload_omits_openai_only_fields() -> None:
    """A vendor is not the protocol: no ``tools[].type``, no ``stream: false``."""
    anthropic = AnthropicProvider(api_key="sk-test", client=FakeAnthropicClient([]))
    request = ChatRequest(
        messages=[
            Message(role=Role.SYSTEM, content="be brief"),
            Message(role=Role.USER, content="hi"),
        ],
        tools=[EchoTool().to_openai_tool()],
    )

    payload = anthropic.build_payload(request, stream=False)

    assert payload["system"] == "be brief"
    assert "type" not in payload["tools"][0]
    assert payload["tools"][0]["name"] == "echo"
    assert "stream" not in payload
    assert all("system" not in m["role"] for m in payload["messages"])


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_anthropic_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a stub ``anthropic`` module so the registry can build the provider.

    The real SDK is an optional extra; the registry must still wire the provider
    up correctly for anyone who has installed it.
    """
    import sys
    import types

    module = types.ModuleType("anthropic")

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    module.Anthropic = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", module)


@pytest.mark.parametrize("name", ["deepseek", "openai", "anthropic"])
def test_registry_builds_every_provider_with_a_key(
    name: str, monkeypatch: pytest.MonkeyPatch, fake_anthropic_sdk: None
) -> None:
    monkeypatch.setenv(f"LOCA_{name.upper()}_API_KEY", "sk-test")
    monkeypatch.setenv("LOCA_DEFAULT_PROVIDER", name)

    provider = get_provider()

    assert isinstance(provider, LLMProvider)
    assert provider.name == name


@pytest.mark.parametrize("name", ["deepseek", "openai", "anthropic"])
def test_registry_requires_a_key_for_every_provider(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(f"LOCA_{name.upper()}_API_KEY", raising=False)

    with pytest.raises(ValueError):
        get_provider(name=name)


def test_registry_without_the_anthropic_sdk_says_what_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing optional dependency must name the fix, not a bare ImportError."""
    import sys

    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setenv("LOCA_ANTHROPIC_API_KEY", "sk-test")

    with pytest.raises(RuntimeError, match=r"loca\[anthropic\]"):
        get_provider(name="anthropic")


def test_default_provider_is_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCA_DEFAULT_PROVIDER", raising=False)
    monkeypatch.setenv("LOCA_DEEPSEEK_API_KEY", "sk-test")

    assert get_provider().name == "deepseek"


def test_provider_stream_type_matches_the_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever the vendor, ``stream_chat`` returns an iterator of chunks."""
    provider = AnthropicProvider(api_key="sk-test", client=FakeAnthropicClient([]))
    stream: Iterator[StreamChunk] = provider.stream_chat(
        ChatRequest(messages=[Message(role=Role.USER, content="hi")])
    )

    chunks = list(stream)
    assert chunks and isinstance(chunks[0], StreamChunk)
