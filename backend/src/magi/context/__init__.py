"""LLM context assembly layer — prompt building, compression, scenario prompts."""

from .assembler import PromptContextAssembler, PromptContextRenderer
from .builder import Scenario
from .scenario_prompts import (
    DEFAULT_SCENARIO_PROMPTS,
    ScenarioPrompt,
    ScenarioPromptsStore,
    initialize_default_prompts,
)
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
    "DEFAULT_SCENARIO_PROMPTS",
    "IdentityConstraintContext",
    "ProfileMemoryContext",
    "PromptAssemblyContext",
    "PromptContextAssembler",
    "PromptContextRenderer",
    "RetrievalMemoryContext",
    "RuntimeSystemContext",
    "Scenario",
    "ScenarioPrompt",
    "ScenarioPromptsStore",
    "SelfMemoryContext",
    "ToolCatalogContext",
    "initialize_default_prompts",
]
