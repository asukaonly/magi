"""
Skill Loader - On-demand skill content loading

Implements the "Load" phase of the skill system:
- Loads full SKILL.md content when needed
- Resolves variable references (!`command`, template.md, examples/)
- Returns executable SkillContent
"""
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from .schema import SkillContent, SkillFrontmatter, Skillmetadata
from .indexer import SkillIndexer

logger = logging.getLogger(__name__)


class SkillLoader:
    """
    Skill Content Loader - Load skills on demand

    Only loads the full content of a skill when it's about to be executed.
    This keeps memory usage minimal for unused skills.
    """

    def __init__(self, indexer: Optional[SkillIndexer] = None):
        """
        initialize the Skill Loader

        Args:
            indexer: SkillIndexer instance for metadata lookup
        """
        self.indexer = indexer or SkillIndexer()
        self._content_cache: Dict[str, SkillContent] = {}

    def load_skill(self, name: str) -> Optional[SkillContent]:
        """
        Load a skill's complete content

        Reads the SKILL.md file and processes variable references.

        Args:
            name: Skill name

        Returns:
            SkillContent or None if not found
        """
        # Check cache first
        if name in self._content_cache:
            logger.debug(f"Loading skill from cache: {name}")
            return self._content_cache[name]

        # Get skill metadata
        metadata = self.indexer.get_metadata(name)
        if not metadata:
            logger.warning(f"Skill not found: {name}")
            return None

        skill_file = metadata.directory / "SKILL.md"
        if not skill_file.exists():
            logger.warning(f"Skill file not found: {skill_file}")
            return None

        try:
            # Read full content
            content = skill_file.read_text(encoding="utf-8")

            # Parse frontmatter and body
            frontmatter, body = self._split_frontmatter(content)

            # Resolve references
            processed_body = self._resolve_references(body, metadata.directory)

            # Create skill content
            skill_content = SkillContent(
                name=name,
                frontmatter=frontmatter,
                prompt_template=processed_body,
                supporting_data=self._load_supporting_data(metadata.directory),
                source_file=skill_file,
            )

            # Cache for future use
            self._content_cache[name] = skill_content

            logger.info(f"Loaded skill: {name} from {skill_file}")
            return skill_content

        except Exception as e:
            logger.error(f"Failed to load skill {name}: {e}")
            return None

    def _split_frontmatter(self, content: str) -> tuple[SkillFrontmatter, str]:
        """
        Split content into frontmatter and body

        Args:
            content: Full file content

        Returns:
            Tuple of (SkillFrontmatter, body_content)
        """
        import yaml

        # Extract YAML frontmatter
        frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTall)
        if not frontmatter_match:
            logger.warning("No frontmatter found, using defaults")
            return SkillFrontmatter(name="", description=""), content

        yaml_content = frontmatter_match.group(1)
        body = frontmatter_match.group(2)

        try:
            data = yaml.safe_load(yaml_content)
            if not isinstance(data, dict):
                data = {}

            frontmatter = SkillFrontmatter(
                name=data.get("name", ""),
                description=data.get("description", ""),
                argument_hint=data.get("argument_hint"),
                disable_model_invocation=data.get("disable_model_invocation", False),
                user_invocable=data.get("user_invocable", True),
                context=data.get("context"),
                agent=data.get("agent"),
                category=data.get("category"),
                tags=data.get("tags", []),
                examples=data.get("examples", []),
            )
            return frontmatter, body

        except yaml.YAMLerror as e:
            logger.warning(f"Failed to parse frontmatter: {e}")
            return SkillFrontmatter(name="", description=""), body

    def _resolve_references(self, content: str, skill_dir: path) -> str:
        """
        Resolve variable references in skill content

        Handles:
        - !`command` - Execute shell command and embed output
        - [template.md](template.md) - Embed file content
        - @examples/ - Reference example files

        Args:
            content: Skill content with references
            skill_dir: Skill directory for resolving relative paths

        Returns:
            processed content with references resolved
        """
        result = content

        # Resolve !`command` - execute shell commands
        result = self._resolve_command_references(result)

        # Resolve [file.md](file.md) - embed file content
        result = self._resolve_file_references(result, skill_dir)

        return result

    def _resolve_command_references(self, content: str) -> str:
        """
        Resolve shell command references

        pattern: !`command`
        Example: !`git rev-parse --short HEAD`

        Args:
            content: Content with command references

        Returns:
            Content with commands executed and replaced
        """
        pattern = r'!`([^`]+)`'

        def replace_command(match):
            command = match.group(1)
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                output = result.stdout.strip()
                if not output:
                    output = result.stderr.strip()
                return output if output else match.group(0)
            except Exception as e:
                logger.warning(f"Command execution failed: {command} -> {e}")
                return match.group(0)

        return re.sub(pattern, replace_command, content)

    def _resolve_file_references(self, content: str, skill_dir: path) -> str:
        """
        Resolve file references

        pattern: [filename](filename) or [alt text](filename)
        Only resolves if the file exists in the skill directory.

        Args:
            content: Content with file references
            skill_dir: Skill directory

        Returns:
            Content with file references replaced by their content
        """
        pattern = r'\[([^\]]*)\]\(([^)]+)\)'

        def replace_file(match):
            alt_text = match.group(1)
            filename = match.group(2)

            # Skip external urls
            if filename.startswith(('http://', 'https://', 'mailto:')):
                return match.group(0)

            # Resolve relative to skill directory
            file_path = skill_dir / filename
            if not file_path.exists():
                # Keep original if file doesn't exist
                return match.group(0)

            try:
                file_content = file_path.read_text(encoding="utf-8")
                # Format as code block for markdown files
                if filename.endswith('.md'):
                    return f"\n```\n{file_content}\n```\n"
                return file_content
            except Exception as e:
                logger.warning(f"Failed to read file {file_path}: {e}")
                return match.group(0)

        return re.sub(pattern, replace_file, content)

    def _load_supporting_data(self, skill_dir: path) -> Dict[str, Any]:
        """
        Load supporting data from the skill directory

        Looks for:
        - examples/ directory
        - template files
        - config files

        Args:
            skill_dir: Skill directory

        Returns:
            Dict of supporting data
        """
        data = {}

        # Load examples if present
        examples_dir = skill_dir / "examples"
        if examples_dir.exists() and examples_dir.is_dir():
            examples = []
            for example_file in examples_dir.iterdir():
                if example_file.is_file() and example_file.suffix in ['.md', '.txt']:
                    try:
                        examples.append({
                            "name": example_file.name,
                            "content": example_file.read_text(encoding="utf-8"),
                        })
                    except Exception as e:
                        logger.warning(f"Failed to load example {example_file}: {e}")
            data["examples"] = examples

        # Look for template files
        for template_file in skill_dir.glob("template*.md"):
            try:
                data[f"template_{template_file.stem}"] = template_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to load template {template_file}: {e}")

        return data

    def clear_cache(self, name: Optional[str] = None) -> None:
        """
        Clear content cache

        Args:
            name: Specific skill to clear, or None to clear all
        """
        if name:
            self._content_cache.pop(name, None)
            logger.debug(f"Cleared cache for skill: {name}")
        else:
            self._content_cache.clear()
            logger.info("Cleared all skill content cache")
