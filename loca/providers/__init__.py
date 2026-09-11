"""Provider abstraction layer.

Defines the unified interface that loca talks to regardless of the underlying
model vendor. Concrete providers (DeepSeek / OpenAI / Anthropic) live in
sub-modules.
"""

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

__all__ = [
    "LLMProvider",
    "ChatRequest",
    "ChatResponse",
    "FinishReason",
    "Message",
    "Role",
    "StreamChunk",
    "ToolCall",
    "Usage",
]
