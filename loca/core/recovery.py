"""Error recovery for provider calls.

Two failure modes dominate a long-running coding agent:

1. **Transient transport failures** — a rate limit, a timeout, a dropped
   connection, a 502 from the gateway. These are not the model's fault and
   usually succeed on a retry, so we hide them behind exponential backoff.

2. **Context overflow** — the conversation grows past the model's window and
   every subsequent call fails with ``context_length_exceeded``. We estimate
   the token cost and drop the oldest turns before that happens.

Neither concern belongs in the execution loop's happy path, so both live here.

The retry policy is deliberately conservative for streaming: once a chunk has
been handed to the caller we must **not** retry, because re-running the request
would replay text the user already saw (and duplicate the tool call). Retries
only cover failures that happen before the first chunk arrives.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from loca.providers.base import LLMProvider
from loca.providers.types import ChatRequest, ChatResponse, Message, Role, StreamChunk

_log = logging.getLogger("loca.recovery")

# HTTP statuses that are worth another attempt. 4xx other than 408/409/425/429
# mean we sent something the server will reject again, so we fail fast.
_TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# Exception class names we treat as transient, matched by name so we do not
# import the openai / httpx SDKs here (and so a mock in tests behaves the same
# as the real client). MRO walk covers subclasses.
_TRANSIENT_NAMES = frozenset(
    {
        # openai SDK
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "InternalServerError",
        # httpx
        "TimeoutException",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "ConnectError",
        "ReadError",
        "WriteError",
        "RemoteProtocolError",
        # builtins
        "TimeoutError",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionAbortedError",
        "ConnectionRefusedError",
        "BrokenPipeError",
    }
)

# Builtin exceptions that are transient even though the name lookup above
# already covers them; kept explicit for readability of the intent.
_BUILTIN_TRANSIENT = (
    TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionAbortedError,
    ConnectionRefusedError,
    BrokenPipeError,
)


class ProviderCallError(RuntimeError):
    """A provider call failed and could not be recovered.

    Wraps the original exception so the harness can report *why* the turn
    died without leaking a vendor-specific exception type into the UI.
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 1,
        transient: bool = False,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.transient = transient
        self.cause = cause


def is_transient(exc: BaseException) -> bool:
    """Best-effort classification: would retrying this call plausibly help?"""
    if isinstance(exc, ProviderCallError):
        # The wrapper already decided; report what it concluded.
        return exc.transient
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return False
    if isinstance(exc, _BUILTIN_TRANSIENT):
        return True

    # openai raises APIStatusError with ``status_code``; httpx raises
    # HTTPStatusError with ``response.status_code``.
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status in _TRANSIENT_STATUS

    for klass in type(exc).__mro__:
        if klass.__name__ in _TRANSIENT_NAMES:
            return True
    return False


# ---------------------------------------------------------------------------
# Retrying provider wrapper
# ---------------------------------------------------------------------------


class RetryingProvider(LLMProvider):
    """Wrap an :class:`LLMProvider` with retries for transient failures.

    ``max_attempts`` counts the *total* number of tries (so ``3`` means the
    original call plus two retries). ``sleep`` is injectable so tests do not
    actually wait; ``on_retry`` is an observability hook called with
    ``(attempt, delay, exc)`` before each backoff.
    """

    def __init__(
        self,
        inner: LLMProvider,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 8.0,
        jitter: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        on_retry: Callable[[int, float, BaseException], None] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._inner = inner
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._jitter = jitter
        self._sleep = sleep
        self._on_retry = on_retry
        self.retry_count = 0

    # ``name`` is a class attribute on providers; mirror the wrapped one.
    @property
    def name(self) -> str:  # type: ignore[override]
        return getattr(self._inner, "name", "unknown")

    @property
    def inner(self) -> LLMProvider:
        """The wrapped provider (handy for tests and for unwrapping)."""
        return self._inner

    # ---- policy ----------------------------------------------------------

    def _delay(self, attempt: int) -> float:
        """Exponential backoff, capped, with optional full-jitter."""
        delay = min(self._max_delay, self._base_delay * (2 ** (attempt - 1)))
        if self._jitter:
            delay *= 0.5 + random.random() * 0.5
        return delay

    def _should_retry(self, exc: BaseException, attempt: int) -> bool:
        return attempt < self._max_attempts and is_transient(exc)

    def _wait(self, attempt: int, exc: BaseException) -> None:
        delay = self._delay(attempt)
        if self._on_retry is not None:
            self._on_retry(attempt, delay, exc)
        _log.warning(
            "provider call failed (attempt %d/%d): %s — retrying in %.2fs",
            attempt,
            self._max_attempts,
            exc,
            delay,
        )
        self._sleep(delay)

    def _exhausted(self, exc: BaseException, attempt: int) -> ProviderCallError:
        return ProviderCallError(
            f"provider {self.name!r} call failed after {attempt} attempt(s): "
            f"{type(exc).__name__}: {exc}",
            attempts=attempt,
            transient=is_transient(exc),
            cause=exc,
        )

    # ---- LLMProvider ------------------------------------------------------

    def chat(self, request: ChatRequest) -> ChatResponse:
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._inner.chat(request)
            except Exception as exc:
                if not self._should_retry(exc, attempt):
                    if is_transient(exc):
                        raise self._exhausted(exc, attempt) from exc
                    raise
                self.retry_count += 1
                self._wait(attempt, exc)

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamChunk]:
        """Retry only while the stream has not produced anything yet.

        A failure after the first chunk is re-raised (wrapped) rather than
        retried: replaying the request would duplicate output the caller
        already consumed.
        """
        attempt = 0
        while True:
            attempt += 1
            emitted = False
            try:
                for chunk in self._inner.stream_chat(request):
                    emitted = True
                    yield chunk
                return
            except Exception as exc:
                if not emitted and self._should_retry(exc, attempt):
                    self.retry_count += 1
                    self._wait(attempt, exc)
                    continue
                if not emitted and is_transient(exc):
                    raise self._exhausted(exc, attempt) from exc
                raise

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"RetryingProvider(inner={self._inner!r}, "
            f"max_attempts={self._max_attempts})"
        )


# ---------------------------------------------------------------------------
# Context budgeting
# ---------------------------------------------------------------------------


def estimate_tokens(text: str | None) -> int:
    """Cheap token estimate that does not need a tokenizer download.

    ASCII-ish text is ~4 chars/token; CJK is ~1 token/char. Good enough to
    trigger a trim *before* the API rejects the request.
    """
    if not text:
        return 0
    cjk = 0
    for ch in text:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF:
            cjk += 1
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def count_message_tokens(message: Message) -> int:
    """Estimated tokens for one message, including tool-call overhead."""
    overhead = 4  # role + separators, as the OpenAI cookbook suggests
    total = overhead + estimate_tokens(message.content)
    for call in message.tool_calls:
        total += estimate_tokens(call.name) + estimate_tokens(str(call.arguments)) + 8
    if message.tool_call_id:
        total += 6
    return total


def count_tokens(messages: Sequence[Message]) -> int:
    """Estimated tokens for a whole conversation."""
    return sum(count_message_tokens(m) for m in messages)


@dataclass(slots=True)
class TrimOutcome:
    """Result of :func:`trim_messages`."""

    messages: list[Message]
    dropped: int = 0
    estimated_tokens: int = 0
    trimmed: bool = False
    dropped_orphan_tool_messages: int = 0


def trim_messages(
    messages: Sequence[Message],
    *,
    max_tokens: int,
    keep_recent: int = 4,
) -> TrimOutcome:
    """Drop the oldest turns until the conversation fits ``max_tokens``.

    Rules:

    - System prompts are always preserved (they carry the harness contract).
    - The most recent ``keep_recent`` messages are preserved even if they push
      past the budget — otherwise a single huge tool result would erase the
      user's question.
    - A ``tool`` message whose parent assistant ``tool_call`` was dropped is
      removed too; OpenAI-compatible APIs reject orphan tool messages.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    system = [m for m in messages if m.role is Role.SYSTEM]
    convo = [m for m in messages if m.role is not Role.SYSTEM]

    budget = max_tokens - count_tokens(system)
    if budget < 0:
        budget = 0

    kept_rev: list[Message] = []
    used = 0
    for msg in reversed(convo):
        cost = count_message_tokens(msg)
        if kept_rev and used + cost > budget and len(kept_rev) >= keep_recent:
            break
        kept_rev.append(msg)
        used += cost

    kept = list(reversed(kept_rev))

    # Drop orphan tool results at the front of the window.
    orphans = 0
    while kept and kept[0].role is Role.TOOL:
        kept.pop(0)
        orphans += 1

    # Never hand the model an empty conversation when there was one to begin
    # with — keep the final turn so the call has a chance to make progress.
    if not kept and convo:
        kept = [convo[-1]]

    result = system + kept
    return TrimOutcome(
        messages=result,
        dropped=len(messages) - len(result),
        estimated_tokens=count_tokens(result),
        trimmed=len(result) != len(messages),
        dropped_orphan_tool_messages=orphans,
    )


__all__ = [
    "ProviderCallError",
    "RetryingProvider",
    "TrimOutcome",
    "count_message_tokens",
    "count_tokens",
    "estimate_tokens",
    "is_transient",
    "trim_messages",
]
