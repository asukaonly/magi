"""Preview-mode chat runner used by the onboarding persona preview screen.

This package exists outside the main agent runtime on purpose: preview chats
must NOT touch tools, memory, or context_decider. They are pure LLM calls
into the configured `core` model with the persona's system prompt prepended.
"""

from magi.chat_preview.runner import PreviewMessage, PreviewMode, run_preview

__all__ = ["PreviewMessage", "PreviewMode", "run_preview"]
