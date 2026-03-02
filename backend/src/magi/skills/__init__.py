"""
Skills Module - Claude Code Skill Support

Implements the skill system with on-demand loading:
1. Indexer - Scan SKILL.md files for metadata only
2. Loader - Load skill content on demand
3. Executor - Execute skills with proper context injection
4. Subagent - Isolated execution context for skills
"""
from .schema import (
    SkillMetadata,
    SkillFrontmatter,
    SkillContent,
    SkillResult,
)
from .indexer import SkillIndexer
from .loader import SkillLoader
from .executor import SkillExecutor
from .subagent import SkillSubagent, create_skill_subagent

__all__ = [
    # Schema
    "SkillMetadata",
    "SkillFrontmatter",
    "SkillContent",
    "SkillResult",
    # Core components
    "SkillIndexer",
    "SkillLoader",
    "SkillExecutor",
    # Subagent
    "SkillSubagent",
    "create_skill_subagent",
]
