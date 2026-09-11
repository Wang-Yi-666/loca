"""Smoke test: the package imports and the registry returns DeepSeek by default."""

from __future__ import annotations

import pytest

import loca
from loca.providers import FinishReason, LLMProvider, Message, Role, ToolCall, Usage
from loca.providers.registry import available_providers, get_provider
from loca.tools import Tool, ToolResult


def test_version_is_exposed() -> None:
    assert isinstance(loca.__version__, str)
    assert loca.__version__  # non-empty


def test_public_types_are_exported() -> None:
    # Symbols come from the public surface of the package.
    assert issubclass(LLMProvider, object)
    assert isinstance(Role.USER.value, str)
    assert isinstance(FinishReason.TOOL_USE.value, str)


def test_message_to_openai_round_trip() -> None:
    msg = Message(
        role=Role.ASSISTANT,
        content=None,  # tool-only turns: we substitute a single space
        tool_calls=[ToolCall(id="call_1", name="read_file", arguments={"path": "README.md"})],
    )
    rendered = msg.to_openai()
    assert rendered["role"] == "assistant"
    # Placeholder content lets DeepSeek accept the message.
    assert rendered["content"] == " "
    assert rendered["tool_calls"][0]["function"]["name"] == "read_file"
    # Arguments must be a JSON string in the OpenAI wire format.
    assert isinstance(rendered["tool_calls"][0]["function"]["arguments"], str)


def test_get_provider_without_key_raises() -> None:
    from loca.providers.deepseek import DeepSeekProvider

    with pytest.raises(ValueError):
        DeepSeekProvider(api_key="")


def test_get_provider_returns_deepseek_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCA_DEFAULT_PROVIDER", "deepseek")
    monkeypatch.setenv("LOCA_DEEPSEEK_API_KEY", "sk-test")
    provider = get_provider()
    assert provider.name == "deepseek"
    assert isinstance(provider, LLMProvider)


def test_get_provider_openai_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCA_DEFAULT_PROVIDER", "openai")
    monkeypatch.delenv("LOCA_OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        get_provider()


def test_get_provider_unknown_name_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(KeyError):
        get_provider(name="does-not-exist")


def test_available_providers_lists_configured_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCA_DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("LOCA_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LOCA_ANTHROPIC_API_KEY", raising=False)
    assert available_providers() == ["deepseek"]


def test_tool_abc_is_subclassable() -> None:
    class EchoTool(Tool):
        name = "echo"
        description = "Echo input back."
        input_schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

        def execute(self, arguments, ctx):  # type: ignore[override]
            return ToolResult(content=arguments["text"])

    tool = EchoTool()
    assert tool.name == "echo"
    assert tool.execute({"text": "hi"}, ctx=None).content == "hi"  # type: ignore[arg-type]
    openai_form = tool.to_openai_tool()
    assert openai_form["type"] == "function"
    assert openai_form["function"]["name"] == "echo"


def test_usage_dataclass() -> None:
    u = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15, reasoning_tokens=3)
    assert u.total_tokens == 15
