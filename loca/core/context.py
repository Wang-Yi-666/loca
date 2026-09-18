"""Context window management: token counting and history compaction.

Week 3 taught the loop to *drop* old turns when the conversation outgrew the
model's window. Dropping is safe but lossy — the agent forgets the goal, the
files it already wrote, and the dead ends it ruled out. This module adds a
better option: fold the old turns into a short summary and keep that instead.

Three pieces:

:class:`TokenCounter`
    Model-aware token estimation. Uses a real tokenizer when one is importable
    (``tiktoken``, optional) and a documented heuristic otherwise, so the
    harness never grows a hard dependency on a 2 MB vocabulary file.

:func:`provider_summarizer`
    Turns "summarize these messages" into a single non-streaming provider call,
    using the very provider the session already has.

:class:`ContextManager`
    The policy: measure, and when the budget is blown, summarize the old turns
    (or trim, if no summarizer is available). Returns a
    :class:`ContextOutcome` describing what it did, which the loop turns into
    events instead of silently rewriting history.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from loca.core.recovery import estimate_tokens, trim_messages
from loca.providers.base import LLMProvider
from loca.providers.types import ChatRequest, Message, Role

_log = logging.getLogger("loca.context")

#: Inserted at the top of the message that replaces the compacted turns, so a
#: human reading the session (or a future resume) can tell it is a summary.
SUMMARY_MARKER = "[Earlier conversation summary]"

#: A user message is used as the carrier (not a system message) because the loop
#: strips incoming system messages when it replays history — a summary stored as
#: ``system`` would vanish on resume.
SUMMARY_ROLE = Role.USER

DEFAULT_SUMMARY_INSTRUCTION = (
    "You compact a coding agent's conversation history so it fits in the model's "
    "context window. Summarize the transcript below.\n"
    "Preserve: the user's goal, decisions taken, every file created or modified "
    "(with its path), commands run and what they returned, and anything still "
    "unresolved. Drop greetings, repeated output and dead ends.\n"
    "Reply with plain text, at most 300 words, no preamble."
)

#: Per-message character cap when rendering a transcript for the summarizer, so
#: one enormous tool result cannot blow up the compaction call itself.
MAX_RENDERED_MESSAGE_CHARS = 4000

#: ``(model_prefix, ascii_chars_per_token, cjk_chars_per_token)``.
#: These are deliberate approximations — a real count comes from a tokenizer,
#: and all we need here is to fire *before* the API rejects the request.
MODEL_PROFILES: tuple[tuple[str, float, float], ...] = (
    ("deepseek", 3.5, 1.0),
    ("gpt-4o", 4.0, 1.0),
    ("gpt-4", 4.0, 1.0),
    ("o1", 4.0, 1.0),
    ("claude", 3.5, 1.0),
    ("qwen", 3.5, 1.0),
    ("glm", 3.5, 1.0),
)

DEFAULT_PROFILE = (4.0, 1.0)


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


class TokenCounter(ABC):
    """Counts (approximately) how many tokens a conversation costs."""

    name: str = "counter"

    @abstractmethod
    def count_text(self, text: str | None) -> int:
        """Tokens in one string."""

    def count_message(self, message: Message) -> int:
        """Tokens for one message, including tool-call and role overhead."""
        total = 4 + self.count_text(message.content)  # role + separators
        for call in message.tool_calls:
            total += self.count_text(call.name) + self.count_text(str(call.arguments)) + 8
        if message.tool_call_id:
            total += 6
        return total

    def count(self, messages: Sequence[Message]) -> int:
        return sum(self.count_message(m) for m in messages)


class HeuristicTokenCounter(TokenCounter):
    """Character-based estimate — no tokenizer, no downloads, no surprises.

    ASCII-ish text runs a few characters per token; CJK is close to one token
    per character. The default ratios reproduce the Week 3 estimator exactly,
    so enabling this module does not silently change existing trim behaviour.
    """

    def __init__(
        self,
        *,
        chars_per_token: float = DEFAULT_PROFILE[0],
        cjk_chars_per_token: float = DEFAULT_PROFILE[1],
        name: str | None = None,
    ) -> None:
        self.chars_per_token = chars_per_token
        self.cjk_chars_per_token = cjk_chars_per_token
        self.name = name or f"heuristic({chars_per_token:g}/tok)"

    def count_text(self, text: str | None) -> int:
        if not text:
            return 0
        if self.chars_per_token <= 0 or self.cjk_chars_per_token <= 0:
            return estimate_tokens(text)
        cjk = sum(
            1
            for ch in text
            if 0x4E00 <= ord(ch) <= 0x9FFF
            or 0x3040 <= ord(ch) <= 0x30FF
            or 0xAC00 <= ord(ch) <= 0xD7AF
        )
        other = len(text) - cjk
        return int(cjk / self.cjk_chars_per_token) + int(other / self.chars_per_token + 0.999)


class TiktokenTokenCounter(TokenCounter):
    """Exact counts via ``tiktoken`` when the package happens to be installed.

    Optional on purpose: a coding harness should not require a tokenizer
    download to start.
    """

    def __init__(self, model: str | None = None) -> None:
        import tiktoken  # noqa: PLC0415 - optional dependency, imported lazily

        try:
            self._encoding = tiktoken.encoding_for_model(model or "gpt-4o")
        except Exception:  # pragma: no cover - unknown model name
            self._encoding = tiktoken.get_encoding("cl100k_base")
        self.name = f"tiktoken({self._encoding.name})"

    def count_text(self, text: str | None) -> int:
        if not text:
            return 0
        return len(self._encoding.encode(text, disallowed_special=()))


def profile_for(model: str | None) -> tuple[float, float]:
    """``(chars_per_token, cjk_chars_per_token)`` for a model name."""
    if model:
        lowered = model.lower()
        for prefix, ascii_ratio, cjk_ratio in MODEL_PROFILES:
            if prefix in lowered:
                return ascii_ratio, cjk_ratio
    return DEFAULT_PROFILE


@lru_cache(maxsize=32)
def _counter_for(model: str | None, prefer_real_tokenizer: bool) -> TokenCounter:
    if prefer_real_tokenizer:
        try:
            return TiktokenTokenCounter(model)
        except ImportError:
            pass
    ratios = profile_for(model)
    label = model or "default"
    return HeuristicTokenCounter(
        chars_per_token=ratios[0],
        cjk_chars_per_token=ratios[1],
        name=f"heuristic[{label}]",
    )


def counter_for(model: str | None = None, *, prefer_real_tokenizer: bool = True) -> TokenCounter:
    """Best available counter for ``model`` (cached per model)."""
    return _counter_for(model, prefer_real_tokenizer)


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------

#: ``(old_messages) -> summary text``.
Summarizer = Callable[[Sequence[Message]], str]


def render_transcript(
    messages: Sequence[Message], *, max_chars: int = MAX_RENDERED_MESSAGE_CHARS
) -> str:
    """Flatten messages into a readable transcript for the summarizer."""
    lines: list[str] = []
    for message in messages:
        body = (message.content or "").strip()
        if len(body) > max_chars:
            body = body[:max_chars] + f"\n… (+{len(body) - max_chars} chars truncated)"
        parts = [f"[{message.role.value}]"]
        if body:
            parts.append(body)
        for call in message.tool_calls:
            parts.append(f"-> called {call.name}({_short(str(call.arguments), 300)})")
        if message.tool_call_id and not body:
            parts.append("(empty tool result)")
        lines.append(" ".join(parts))
    return "\n\n".join(lines)


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def provider_summarizer(
    provider: LLMProvider,
    *,
    model: str | None = None,
    max_tokens: int = 700,
    instruction: str | None = None,
) -> Summarizer:
    """Build a summarizer that compacts history with ``provider`` itself.

    Deliberately a plain ``chat()`` call: the summary is internal plumbing, so it
    must not stream into the user's transcript.
    """
    system_prompt = instruction or DEFAULT_SUMMARY_INSTRUCTION

    def summarize(messages: Sequence[Message]) -> str:
        request = ChatRequest(
            messages=[
                Message(role=Role.SYSTEM, content=system_prompt),
                Message(role=Role.USER, content=render_transcript(messages)),
            ],
            model=model,
            max_tokens=max_tokens,
            stream=False,
        )
        response = provider.chat(request)
        return (response.message.content or "").strip()

    return summarize


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ContextOutcome:
    """What the context manager decided to send, and why."""

    messages: list[Message]
    estimated_tokens: int
    budget: int
    trimmed: bool = False
    summarized: bool = False
    dropped: int = 0
    summarized_messages: int = 0
    summary_tokens: int = 0

    @property
    def fits(self) -> bool:
        return self.estimated_tokens <= self.budget


class ContextManager:
    """Keep a conversation inside the model's window.

    Order of preference when the budget is blown:

    1. **Summarize** the old turns into one message (needs a ``summarizer``).
       Information survives; the agent keeps knowing what it already did.
    2. **Trim** them away (Week 3 behaviour) when there is no summarizer, or
       when there is too little history for a summary to be worth a call.

    Recommendation from the loop is not to call this at all until the budget is
    exceeded — ``fit()`` is cheap, but the summarizer call is not.
    """

    def __init__(
        self,
        *,
        budget: int,
        keep_recent: int = 6,
        model: str | None = None,
        counter: TokenCounter | None = None,
        summarizer: Summarizer | None = None,
        min_summarize_messages: int = 2,
    ) -> None:
        if budget <= 0:
            raise ValueError("budget must be positive")
        self.budget = budget
        self.keep_recent = max(0, keep_recent)
        self.model = model
        self.counter = counter or counter_for(model)
        self.summarizer = summarizer
        self.min_summarize_messages = max(1, min_summarize_messages)
        #: How many summarizer calls this manager made (observability/tests).
        self.summarize_calls = 0

    # ---- measurement ------------------------------------------------------

    def count(self, messages: Sequence[Message]) -> int:
        return self.counter.count(messages)

    def needs_compaction(self, messages: Sequence[Message]) -> bool:
        return self.count(messages) > self.budget

    # ---- policy -----------------------------------------------------------

    def fit(self, messages: Sequence[Message]) -> ContextOutcome:
        """Return the message list to actually send.

        Never mutates the input; the caller decides whether to adopt it.
        """
        total = self.count(messages)
        if total <= self.budget:
            return ContextOutcome(
                messages=list(messages), estimated_tokens=total, budget=self.budget
            )

        system, convo = _split_system(messages)
        recent = convo[-self.keep_recent :] if self.keep_recent else []
        older = convo[: len(convo) - len(recent)]

        if self.summarizer is not None and len(older) >= self.min_summarize_messages:
            summary = self._summarize(older)
            if summary:
                return self._assemble_with_summary(system, convo, older, recent, summary, total)

        return self._trim(messages, total)

    def compact(
        self, messages: Sequence[Message]
    ) -> tuple[list[Message], ContextOutcome | None]:
        """Force a summary of everything except the recent turns.

        Backs an explicit ``/compact`` command: the user asks for it, so it runs
        even when the conversation still fits.
        """
        if self.summarizer is None:
            return list(messages), None
        system, convo = _split_system(messages)
        recent = convo[-self.keep_recent :] if self.keep_recent else []
        older = convo[: len(convo) - len(recent)]
        if len(older) < self.min_summarize_messages:
            return list(messages), None
        summary = self._summarize(older)
        if not summary:
            return list(messages), None
        outcome = self._assemble_with_summary(
            system, convo, older, recent, summary, self.count(messages)
        )
        return outcome.messages, outcome

    # ---- internals --------------------------------------------------------

    def _summarize(self, older: Sequence[Message]) -> str:
        assert self.summarizer is not None
        try:
            text = self.summarizer(older).strip()
        except Exception as exc:
            # A failed compaction must never kill the turn: fall back to trim.
            _log.warning(
                "summarizer failed (%s: %s); falling back to trim",
                type(exc).__name__,
                exc,
            )
            return ""
        self.summarize_calls += 1
        return text

    def _assemble_with_summary(
        self,
        system: list[Message],
        convo: Sequence[Message],
        older: Sequence[Message],
        recent: Sequence[Message],
        summary: str,
        total: int,
    ) -> ContextOutcome:
        """Pin the summary in place, then shrink the recent tail to fit."""
        summary_message = Message(
            role=SUMMARY_ROLE, content=f"{SUMMARY_MARKER}\n{summary}"
        )
        summary_tokens = self.counter.count_message(summary_message)

        # Trim the remaining tail, then splice the summary right after the
        # system block. Trimming first and reinserting keeps the summary from
        # being treated as disposable history.
        tail_budget = self.budget - self.counter.count(system) - summary_tokens
        if tail_budget <= 0:
            kept_tail: list[Message] = []
        else:
            trimmed = trim_messages(
                [*system, *recent], max_tokens=tail_budget, keep_recent=self.keep_recent
            )
            kept_tail = [m for m in trimmed.messages if m.role is not Role.SYSTEM]

        if not kept_tail and recent:
            # Always leave the model something to answer: the last real turn.
            kept_tail = [recent[-1]]

        result = [*system, summary_message, *kept_tail]
        return ContextOutcome(
            messages=result,
            estimated_tokens=self.counter.count(result),
            budget=self.budget,
            trimmed=True,
            summarized=True,
            dropped=len(system) + len(convo) - (len(system) + len(kept_tail)),
            summarized_messages=len(older),
            summary_tokens=summary_tokens,
        )

    def _trim(self, messages: Sequence[Message], total: int) -> ContextOutcome:
        outcome = trim_messages(
            messages, max_tokens=self.budget, keep_recent=max(1, self.keep_recent)
        )
        return ContextOutcome(
            messages=outcome.messages,
            estimated_tokens=outcome.estimated_tokens,
            budget=self.budget,
            trimmed=outcome.trimmed,
            dropped=outcome.dropped,
        )


def _split_system(messages: Sequence[Message]) -> tuple[list[Message], list[Message]]:
    system = [m for m in messages if m.role is Role.SYSTEM]
    convo = [m for m in messages if m.role is not Role.SYSTEM]
    return system, convo


def count_tokens_for_model(
    messages: Sequence[Message], model: str | None = None
) -> int:
    """Convenience wrapper used by callers that just want a number."""
    return counter_for(model).count(messages)


__all__ = [
    "DEFAULT_PROFILE",
    "DEFAULT_SUMMARY_INSTRUCTION",
    "MAX_RENDERED_MESSAGE_CHARS",
    "MODEL_PROFILES",
    "SUMMARY_MARKER",
    "ContextManager",
    "ContextOutcome",
    "HeuristicTokenCounter",
    "Summarizer",
    "TiktokenTokenCounter",
    "TokenCounter",
    "count_tokens_for_model",
    "counter_for",
    "profile_for",
    "provider_summarizer",
    "render_transcript",
]
