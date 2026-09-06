"""
Skill Indexer - Scan and index skill metadata

Implements the "Index" phase of the skill system:
- Scans SKILL.md files in configured directories
- Parses only YAML frontmatter (not full content)
- Returns lightweight SkillMetadata for skill discovery
"""

import logging
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.packaged_paths import get_repo_root
from .allowed_tools_rules import parse_allowed_tools, rules_to_strings
from .schema import SkillMetadata, SkillFrontmatter

logger = logging.getLogger(__name__)

# Skill name validation pattern:
# - 1-64 characters
# - Lowercase alphanumeric with hyphens
# - Must start with letter or digit
# - Pattern: ^[a-z0-9][a-z0-9-]*$
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_NAME_LENGTH = 64


class SkillIndexer:
    """
    Skill Indexer - Scans and indexes skill metadata

    Only parses YAML frontmatter, keeping memory usage minimal.
    Full skill content is loaded on-demand by SkillLoader.
    """

    # Skill directories.
    #
    # NOTE on priority: scan_all() iterates in reverse and applies
    # ``dict.update()``, so a location listed EARLIER in this tuple wins when
    # the same skill name appears in multiple locations. The list is ordered
    # high-priority first for readability; do not reorder without updating
    # scan_all().
    _REPO_ROOT = get_repo_root()
    SKILL_LOCATIONS = [
        Path.home() / ".claude" / "skills",  # Personal — Claude Code compatible
        Path.home() / ".agents" / "skills",  # Personal — agents-style layout
        _REPO_ROOT / "skills",  # Project predefined skills (magi/skills)
        _REPO_ROOT / ".claude" / "skills",  # Project local (lower priority)
    ]

    def __init__(self, skill_locations: Optional[List[Path]] = None):
        """
        initialize the Skill Indexer

        Args:
            skill_locations: Custom skill directories (optional)
        """
        self.skill_locations = skill_locations or self.SKILL_LOCATIONS
        self._cache: Dict[str, SkillMetadata] = {}
        self._plugin_skills: dict[str, SkillMetadata] = {}

    def register_plugin_skill(
        self, name: str, skill_file: Path
    ) -> tuple[SkillMetadata, Callable[[], None]]:
        """Index packaged content with an owner-bound revocation handle."""
        if name in self._cache or name in self._plugin_skills:
            raise ValueError(f"Skill is already indexed: {name}")
        metadata = self._parse_skill_metadata(skill_file)
        if metadata is None:
            raise ValueError(f"Invalid plugin skill: {skill_file}")
        metadata = replace(metadata, name=name)
        self._plugin_skills[name] = metadata
        self._cache[name] = metadata

        def dispose() -> None:
            if self._plugin_skills.get(name) is metadata:
                del self._plugin_skills[name]
                if self._cache.get(name) is metadata:
                    del self._cache[name]

        return metadata, dispose

    @staticmethod
    def validate_skill_name(
        name: str, directory_name: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Validate skill name according to Claude Code Skills specification.

        Rules:
        - 1-64 characters
        - Lowercase alphanumeric with hyphens only
        - Must start with letter or digit
        - Cannot end with hyphen
        - Must match directory name if provided

        Args:
            name: Skill name to validate
            directory_name: Expected directory name (for consistency check)

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not name:
            return False, "Skill name cannot be empty"

        if len(name) > MAX_NAME_LENGTH:
            return (
                False,
                f"Skill name must be {MAX_NAME_LENGTH} characters or less, got {len(name)}",
            )

        if not SKILL_NAME_PATTERN.match(name):
            return False, (
                f"Skill name must be lowercase alphanumeric with hyphens, "
                f"start with letter or digit, and not end with hyphen: '{name}'"
            )

        if name.endswith("-"):
            return False, f"Skill name cannot end with hyphen: '{name}'"

        if directory_name and name != directory_name:
            return (
                False,
                f"Skill name '{name}' must match directory name '{directory_name}'",
            )

        return True, None

    def scan_all(self) -> Dict[str, SkillMetadata]:
        """
        Scan all SKILL.md files and return metadata

        Only parses YAML frontmatter, not the full markdown content.
        Skills with the same name follow priority (later locations override earlier ones).

        Returns:
            Dict mapping skill name to SkillMetadata
        """
        skills = {}

        # Scan in reverse order so higher priority locations override lower ones
        for location in reversed(self.skill_locations):
            if not location.exists():
                logger.debug(f"Skill location does not exist: {location}")
                continue

            found_skills = self._scan_directory(location)
            skills.update(found_skills)

            logger.info(f"Scanned {len(found_skills)} skills from {location}")

        skills.update(self._plugin_skills)
        self._cache = skills
        logger.info(f"Total skills indexed: {len(skills)}")

        return skills

    def _scan_directory(self, directory: Path) -> Dict[str, SkillMetadata]:
        """
        Scan a single directory for skills

        Args:
            directory: directory to scan

        Returns:
            Dict of skills found in this directory
        """
        skills = {}

        # Look for SKILL.md files in subdirectories
        for skill_dir in directory.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                metadata = self._parse_skill_metadata(skill_file)
                if metadata:
                    skills[metadata.name] = metadata
                    logger.debug(f"Indexed skill: {metadata.name} from {skill_dir}")
            except Exception as e:
                logger.warning(f"Failed to parse skill {skill_dir}: {e}")

        return skills

    def _parse_skill_metadata(self, skill_file: Path) -> Optional[SkillMetadata]:
        """
        Parse skill metadata from SKILL.md file

        Only reads and parses the YAML frontmatter.

        Args:
            skill_file: Path to SKILL.md

        Returns:
            SkillMetadata or None if parsing fails
        """
        try:
            content = skill_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read skill file {skill_file}: {e}")
            return None

        # Extract YAML frontmatter
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not frontmatter_match:
            logger.warning(f"No frontmatter found in {skill_file}")
            return None

        yaml_content = frontmatter_match.group(1)
        frontmatter = self._parse_yaml_frontmatter(yaml_content, skill_file)

        if not frontmatter:
            return None

        return SkillMetadata(
            name=frontmatter.name,
            description=frontmatter.description,
            directory=skill_file.parent,
            argument_hint=frontmatter.argument_hint,
            disable_model_invocation=frontmatter.disable_model_invocation,
            user_invocable=frontmatter.user_invocable,
            context=frontmatter.context,
            agent=frontmatter.agent,
            category=frontmatter.category,
            tags=frontmatter.tags,
            # Claude Code Skills spec fields
            license=frontmatter.license,
            compatibility=frontmatter.compatibility,
            allowed_tools=frontmatter.allowed_tools,
        )

    def _parse_yaml_frontmatter(
        self, yaml_content: str, source_file: Path
    ) -> Optional[SkillFrontmatter]:
        """
        Parse YAML frontmatter into SkillFrontmatter

        Args:
            yaml_content: YAML content as string
            source_file: source file path for error reporting

        Returns:
            SkillFrontmatter or None
        """
        data = _load_frontmatter_mapping(yaml_content, source_file)
        if data is None:
            return None
        name = self._validated_frontmatter_name(data, source_file)
        if name is None:
            return None
        return SkillFrontmatter(
            name=name,
            description=_normalized_description(data, name, source_file),
            argument_hint=data.get("argument_hint"),
            disable_model_invocation=data.get("disable_model_invocation", False),
            user_invocable=data.get("user_invocable", True),
            context=data.get("context"),
            agent=data.get("agent"),
            category=data.get("category"),
            tags=data.get("tags", []),
            examples=data.get("examples", []),
            # New fields for Claude Code Skills spec compliance
            license=data.get("license"),
            compatibility=_normalized_compatibility(data, source_file),
            allowed_tools=_normalized_allowed_tools(data, source_file),
            metadata=data.get("metadata", {}),
        )

    def _validated_frontmatter_name(
        self, data: dict[str, Any], source_file: Path
    ) -> Any | None:
        name = data.get("name")
        if not name:
            logger.warning(f"Skill missing 'name' field in {source_file}")
            return None

        directory_name = source_file.parent.name
        is_valid, error_msg = self.validate_skill_name(str(name), directory_name)
        if not is_valid:
            logger.warning(f"Invalid skill name in {source_file}: {error_msg}")
            return None
        return name

    def get_skill_names(self) -> List[str]:
        """
        Get list of all indexed skill names

        Returns:
            List of skill names
        """
        return list(self._cache.keys())

    def get_metadata(self, name: str) -> Optional[SkillMetadata]:
        """
        Get metadata for a specific skill

        Args:
            name: Skill name

        Returns:
            SkillMetadata or None
        """
        return self._cache.get(name)

    def refresh(self) -> Dict[str, SkillMetadata]:
        """
        Refresh the skill index by rescanning all directories

        Returns:
            Updated skill index
        """
        logger.info("Refreshing skill index...")
        return self.scan_all()

    def clear_cache(self) -> None:
        """Clear the cached skill index"""
        self._cache.clear()
        logger.info("Skill index cache cleared")


def _load_frontmatter_mapping(
    yaml_content: str, source_file: Path
) -> dict[str, Any] | None:
    import yaml

    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse YAML in {source_file}: {e}")
        return None
    if not isinstance(data, dict):
        logger.warning(f"Invalid frontmatter in {source_file}: not a dict")
        return None
    return data


def _normalized_description(data: dict[str, Any], name: Any, source_file: Path) -> Any:
    description = data.get("description", "")
    if not description:
        description = f"Skill: {name}"
    if len(description) > 1024:
        logger.warning(
            f"Description too long in {source_file}: {len(description)} chars (max 1024)"
        )
        description = description[:1024]
    return description


def _normalized_compatibility(data: dict[str, Any], source_file: Path) -> Any:
    compatibility = data.get("compatibility")
    if compatibility and len(str(compatibility)) > 500:
        logger.warning(
            f"Compatibility too long in {source_file}: {len(str(compatibility))} chars (max 500)"
        )
        compatibility = str(compatibility)[:500]
    return compatibility


def _normalized_allowed_tools(
    data: dict[str, Any], source_file: Path
) -> list[str] | None:
    allowed_tools_raw = data.get("allowed-tools")
    parsed_rules = parse_allowed_tools(allowed_tools_raw)
    if allowed_tools_raw is not None and not parsed_rules:
        logger.warning(
            "allowed-tools in %s could not be parsed; ignoring",
            source_file,
        )
    return rules_to_strings(parsed_rules) if parsed_rules else None
