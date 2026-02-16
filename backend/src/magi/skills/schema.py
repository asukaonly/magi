"""
Skill Schema - data models for skills

Defines the data structures used throughout the skills system.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class SkillFrontmatter:
    """
    Skill frontmatter parsed from YAML

    This is the metadata section of a SKILL.md file.
    """
    name: str
    description: str
    argument_hint: Optional[str] = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    context: Optional[str] = None  # "fork" for sub-agent execution
    agent: Optional[str] = None  # Sub-agent type (e.g., "general-purpose")
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    examples: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SkillMetadata:
    """
    Skill metadata (lightweight, kept in memory)

    This is the minimal information needed for skill discovery and selection.
    The full content is only loaded when the skill is executed.
    """
    name: str
    description: str
    directory: Path  # Used for loading full content later
    argument_hint: Optional[str] = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    context: Optional[str] = None
    agent: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class SkillContent:
    """
    Complete skill content ready for execution

    This contains the full skill definition including the prompt template
    and any supporting data needed for execution.
    """
    name: str
    frontmatter: SkillFrontmatter
    prompt_template: str  # processed template with resolved references
    supporting_data: Dict[str, Any] = field(default_factory=dict)
    source_file: Optional[Path] = None


@dataclass
class SkillResult:
    """
    Result of skill execution
    """
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
