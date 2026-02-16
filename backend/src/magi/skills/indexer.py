"""
Skill Indexer - Scan and index skill metadata

Implements the "Index" phase of the skill system:
- Scans SKILL.md files in configured directories
- Parses only YAML frontmatter (not full content)
- Returns lightweight Skillmetadata for skill discovery
"""
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from .schema import Skillmetadata, SkillFrontmatter

logger = logging.getLogger(__name__)


class SkillIndexer:
    """
    Skill Indexer - Scans and indexes skill metadata

    Only parses YAML frontmatter, keeping memory usage minimal.
    Full skill content is loaded on-demand by SkillLoader.
    """

    # Skill directories in priority order (higher priority first)
    SKILL_LOCATIONS = [
        path.home() / ".claude" / "skills",     # Personal (high priority)
        path(__file__).parent.parent.parent.parent.parent / "skills",  # Project predefined skills (magi/skills)
        path.cwd() / ".claude" / "skills",       # Project local (lower priority)
    ]

    def __init__(self, skill_locations: Optional[List[path]] = None):
        """
        initialize the Skill Indexer

        Args:
            skill_locations: Custom skill directories (optional)
        """
        self.skill_locations = skill_locations or self.SKILL_LOCATIONS
        self._cache: Dict[str, Skillmetadata] = {}

    def scan_all(self) -> Dict[str, Skillmetadata]:
        """
        Scan all SKILL.md files and return metadata

        Only parses YAML frontmatter, not the full markdown content.
        Skills with the same name follow priority (later locations override earlier ones).

        Returns:
            Dict mapping skill name to Skillmetadata
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

        self._cache = skills
        logger.info(f"Total skills indexed: {len(skills)}")

        return skills

    def _scan_directory(self, directory: path) -> Dict[str, Skillmetadata]:
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

    def _parse_skill_metadata(self, skill_file: path) -> Optional[Skillmetadata]:
        """
        Parse skill metadata from SKILL.md file

        Only reads and parses the YAML frontmatter.

        Args:
            skill_file: path to SKILL.md

        Returns:
            Skillmetadata or None if parsing fails
        """
        try:
            content = skill_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read skill file {skill_file}: {e}")
            return None

        # Extract YAML frontmatter
        frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTall)
        if not frontmatter_match:
            logger.warning(f"No frontmatter found in {skill_file}")
            return None

        yaml_content = frontmatter_match.group(1)
        frontmatter = self._parse_yaml_frontmatter(yaml_content, skill_file)

        if not frontmatter:
            return None

        return Skillmetadata(
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
        )

    def _parse_yaml_frontmatter(self, yaml_content: str, source_file: path) -> Optional[SkillFrontmatter]:
        """
        Parse YAML frontmatter into SkillFrontmatter

        Args:
            yaml_content: YAML content as string
            source_file: source file path for error reporting

        Returns:
            SkillFrontmatter or None
        """
        import yaml

        try:
            data = yaml.safe_load(yaml_content)
            if not isinstance(data, dict):
                logger.warning(f"Invalid frontmatter in {source_file}: not a dict")
                return None

            # Required fields
            name = data.get("name")
            if not name:
                logger.warning(f"Skill missing 'name' field in {source_file}")
                return None

            description = data.get("description", "")
            if not description:
                description = f"Skill: {name}"

            return SkillFrontmatter(
                name=name,
                description=description,
                argument_hint=data.get("argument_hint"),
                disable_model_invocation=data.get("disable_model_invocation", False),
                user_invocable=data.get("user_invocable", True),
                context=data.get("context"),
                agent=data.get("agent"),
                category=data.get("category"),
                tags=data.get("tags", []),
                examples=data.get("examples", []),
            )

        except yaml.YAMLerror as e:
            logger.warning(f"Failed to parse YAML in {source_file}: {e}")
            return None

    def get_skill_names(self) -> List[str]:
        """
        Get list of all indexed skill names

        Returns:
            List of skill names
        """
        return list(self._cache.keys())

    def get_metadata(self, name: str) -> Optional[Skillmetadata]:
        """
        Get metadata for a specific skill

        Args:
            name: Skill name

        Returns:
            Skillmetadata or None
        """
        return self._cache.get(name)

    def refresh(self) -> Dict[str, Skillmetadata]:
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
