"""LLM context assembly layer - prompt-context policy, retrieval, and rendering."""

from .assembler import PromptContextAssembler, PromptContextRenderer
from .contracts import ContextPolicyDecision, PromptPackage
from .policy import ContextPolicy
from .retrieval import ContextRetrievalService
from .service import ContextAssemblyService
from .user_profile_service import UserProfileService
from .window_budget import (
    ContextWindowBudget,
    build_context_window_budget,
    estimate_context_tokens,
    estimate_text_tokens,
)
from .scenarios import Scenario
from .schema import (
    IdentityConstraintContext,
    ProfileMemoryContext,
    PromptAssemblyContext,
    RetrievalMemoryContext,
    RuntimeSystemContext,
    SelfMemoryContext,
    ToolCatalogContext,
)

__all__ = [
    "ContextAssemblyService",
    "ContextPolicy",
    "ContextPolicyDecision",
    "ContextRetrievalService",
    "ContextWindowBudget",
    "IdentityConstraintContext",
    "ProfileMemoryContext",
    "PromptPackage",
    "PromptAssemblyContext",
    "PromptContextAssembler",
    "PromptContextRenderer",
    "RetrievalMemoryContext",
    "RuntimeSystemContext",
    "Scenario",
    "SelfMemoryContext",
    "ToolCatalogContext",
    "UserProfileService",
    "build_context_window_budget",
    "estimate_context_tokens",
    "estimate_text_tokens",
]
