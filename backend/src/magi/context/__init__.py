"""LLM context assembly layer - prompt building and compression."""

from .assembler import PromptContextAssembler, PromptContextRenderer
from .contracts import ContextPolicyDecision, PromptPackage
from .policy import ContextPolicy
from .retrieval import ContextRetrievalService
from .service import ContextAssemblyService
from .user_profile_service import UserProfileService
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
]
