"""
Skills Module - Claude Code Skill Support

Implements the skill system with on-demand loading:
1. Indexer - Scan SKILL.md files for metadata only
2. Loader - Load skill content on demand
3. Runner - Execute skills with proper context injection
4. Fork execution through the shared agent runtime
"""
from .schema import (
    SkillMetadata,
    SkillFrontmatter,
    SkillContent,
    SkillResult,
)
from .indexer import SkillIndexer
from .loader import SkillLoader
from .runner import SkillRunner

__all__ = [
    # Schema
    "SkillMetadata",
    "SkillFrontmatter",
    "SkillContent",
    "SkillResult",
    # Core components
    "SkillIndexer",
    "SkillLoader",
    "SkillRunner",
]
