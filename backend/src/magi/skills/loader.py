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

from magi_plugin_sdk.subprocess import hidden_process_kwargs
from .allowed_tools_rules import parse_allowed_tools, rules_to_strings
from .schema import SkillContent, SkillFrontmatter
from .indexer import SkillIndexer

logger = logging.getLogger(__name__)

# Hard upper bound on the body of a single SKILL.md after frontmatter is
# stripped. Anything larger is truncated with a warning to avoid blowing the
# model context window from a misbehaving or hostile skill file.
MAX_SKILL_BODY_BYTES = 256 * 1024  # 256 KiB

# ``!`command``` references inside SKILL.md auto-execute shell at load time.
# That is *not* part of the Claude Code Skills spec and is a clear RCE vector
# when a SKILL.md comes from an untrusted source (shared org skill repo,
# downloaded skill pack, plugin contribution, …). The capability is therefore
# disabled by default; opt back in via the environment variable when a
# trusted-source workflow needs it.
_ALLOW_COMMAND_RESOLUTION_ENV = "MAGI_SKILLS_ALLOW_COMMAND_RESOLUTION"


def _command_resolution_enabled() -> bool:
    value = os.environ.get(_ALLOW_COMMAND_RESOLUTION_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


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

            body = self._enforce_body_size_limit(body, skill_file)

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
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
        if not frontmatter_match:
            logger.warning("No frontmatter found, using defaults")
            return SkillFrontmatter(name="", description=""), content

        yaml_content = frontmatter_match.group(1)
        body = frontmatter_match.group(2)

        try:
            data = yaml.safe_load(yaml_content)
            if not isinstance(data, dict):
                data = {}

            parsed_rules = parse_allowed_tools(data.get("allowed-tools"))
            allowed_tools = rules_to_strings(parsed_rules) if parsed_rules else None
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
                # Claude Code Skills spec fields
                license=data.get("license"),
                compatibility=data.get("compatibility"),
                allowed_tools=allowed_tools,
                metadata=data.get("metadata", {}),
            )
            return frontmatter, body

        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse frontmatter: {e}")
            return SkillFrontmatter(name="", description=""), body

    def _enforce_body_size_limit(self, body: str, skill_file: Path) -> str:
        """Cap the SKILL.md body so a runaway file cannot exhaust the model context.

        The limit is measured in UTF-8 bytes (closer to what the LLM
        tokenizer cares about than character count for non-ASCII text).
        When exceeded, the body is truncated and a marker is appended so
        the model can see the cut happened — silent truncation would hide
        the problem.
        """
        encoded = body.encode("utf-8")
        if len(encoded) <= MAX_SKILL_BODY_BYTES:
            return body
        logger.warning(
            "SKILL.md body %s exceeds %d bytes (got %d); truncating",
            skill_file,
            MAX_SKILL_BODY_BYTES,
            len(encoded),
        )
        # Truncate on a UTF-8 boundary by decoding with errors='ignore'.
        truncated = encoded[:MAX_SKILL_BODY_BYTES].decode("utf-8", errors="ignore")
        return (
            truncated + f"\n\n<!-- SKILL.md truncated at {MAX_SKILL_BODY_BYTES} bytes by magi -->\n"
        )

    def _resolve_references(self, content: str, skill_dir: Path) -> str:
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
        Resolve shell command references at load time.

        Pattern: ``!`command``` — for example ``!`git rev-parse --short HEAD```.

        This auto-executes shell on the host whenever a SKILL.md is loaded,
        which is an RCE vector when the SKILL.md is sourced from an
        untrusted location. The capability is therefore **disabled by
        default**. Set ``MAGI_SKILLS_ALLOW_COMMAND_RESOLUTION=1`` to
        re-enable for trusted workflows; references are then executed with
        a hard 5-second timeout per match.

        When the capability is disabled and a ``!`command``` reference is
        present, the literal text is preserved unchanged so the model still
        sees the intent (and can choose to run it via the Bash tool, which
        is permission-gated).
        """
        pattern = r"!`([^`]+)`"

        if not _command_resolution_enabled():
            if pattern_matches := re.findall(pattern, content):
                logger.warning(
                    "SKILL.md contains %d shell-execution reference(s); "
                    "auto-execution is disabled (set %s=1 to enable). "
                    "Leaving the literals in place — the model can run them "
                    "via the Bash tool if needed. samples=%s",
                    len(pattern_matches),
                    _ALLOW_COMMAND_RESOLUTION_ENV,
                    pattern_matches[:3],
                )
            return content

        def replace_command(match):
            command = match.group(1)
            logger.warning(
                "Executing !`command` from SKILL.md at load time: %s",
                command,
            )
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    **hidden_process_kwargs(),
                )
                output = result.stdout.strip()
                if not output:
                    output = result.stderr.strip()
                return output if output else match.group(0)
            except Exception as e:
                logger.warning(f"Command execution failed: {command} -> {e}")
                return match.group(0)

        return re.sub(pattern, replace_command, content)

    def _resolve_file_references(self, content: str, skill_dir: Path) -> str:
        """
        Resolve file references

        pattern: [filename](filename) or [alt text](filename)
        Only resolves if the file exists inside the skill directory.

        Paths that escape ``skill_dir`` (via ``..``, absolute paths, or
        symlinks that resolve outside the directory) are rejected — the
        original markdown text is kept unchanged so the rest of the body
        is unaffected.

        Args:
            content: Content with file references
            skill_dir: Skill directory

        Returns:
            Content with file references replaced by their content
        """
        pattern = r"\[([^\]]*)\]\(([^)]+)\)"
        skill_dir_resolved = skill_dir.resolve()

        return re.sub(
            pattern,
            lambda match: self._replace_file_reference(
                match,
                skill_dir,
                skill_dir_resolved,
            ),
            content,
        )

    def _replace_file_reference(
        self,
        match: re.Match[str],
        skill_dir: Path,
        skill_dir_resolved: Path,
    ) -> str:
        filename = match.group(2)
        if filename.startswith(("http://", "https://", "mailto:")):
            return match.group(0)

        resolved = self._resolve_safe_skill_file_reference(
            filename,
            skill_dir,
            skill_dir_resolved,
        )
        if resolved is None or not resolved.is_file():
            return match.group(0)
        return self._read_skill_file_reference(filename, resolved, match.group(0))

    @staticmethod
    def _resolve_safe_skill_file_reference(
        filename: str,
        skill_dir: Path,
        skill_dir_resolved: Path,
    ) -> Path | None:
        try:
            candidate = Path(filename)
        except (ValueError, OSError):
            return None
        if candidate.is_absolute():
            logger.warning(
                "Rejecting absolute SKILL.md file reference: %s (skill_dir=%s)",
                filename,
                skill_dir_resolved,
            )
            return None

        try:
            resolved = (skill_dir / filename).resolve()
        except (OSError, RuntimeError) as exc:
            logger.warning("SKILL.md file reference unresolvable: %s (%s)", filename, exc)
            return None
        try:
            resolved.relative_to(skill_dir_resolved)
        except ValueError:
            logger.warning(
                "Rejecting out-of-tree SKILL.md file reference: %s -> %s (skill_dir=%s)",
                filename,
                resolved,
                skill_dir_resolved,
            )
            return None
        return resolved

    @staticmethod
    def _read_skill_file_reference(
        filename: str,
        resolved: Path,
        original_markdown: str,
    ) -> str:
        try:
            file_content = resolved.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read file {resolved}: {e}")
            return original_markdown
        if filename.endswith(".md"):
            return f"\n```\n{file_content}\n```\n"
        return file_content

    def _load_supporting_data(self, skill_dir: Path) -> Dict[str, Any]:
        """
        Load supporting data from the skill directory

        Standard directories per Claude Code Skills spec:
        - examples/ - Example files
        - scripts/ - Executable scripts
        - references/ - Reference documents
        - assets/ - Static assets (images, etc.)

        Also loads:
        - template files (template*.md)

        Args:
            skill_dir: Skill directory

        Returns:
            Dict of supporting data
        """
        data = {}

        examples_dir = skill_dir / "examples"
        if examples_dir.exists() and examples_dir.is_dir():
            data["examples"] = _load_text_supporting_files(
                examples_dir,
                suffixes={".md", ".txt"},
                warning_label="example",
            )

        scripts_dir = skill_dir / "scripts"
        if scripts_dir.exists() and scripts_dir.is_dir():
            data["scripts"] = _load_path_supporting_files(
                scripts_dir,
                warning_label="script",
            )

        references_dir = skill_dir / "references"
        if references_dir.exists() and references_dir.is_dir():
            data["references"] = _load_text_supporting_files(
                references_dir,
                suffixes={".md", ".txt", ".json"},
                warning_label="reference",
            )

        assets_dir = skill_dir / "assets"
        if assets_dir.exists() and assets_dir.is_dir():
            data["assets"] = _load_path_supporting_files(
                assets_dir,
                warning_label="asset",
            )

        data.update(_load_template_files(skill_dir))
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


def _load_text_supporting_files(
    directory: Path,
    *,
    suffixes: set[str],
    warning_label: str,
) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for item in directory.iterdir():
        if not item.is_file() or item.suffix not in suffixes:
            continue
        try:
            files.append(
                {
                    "name": item.name,
                    "content": item.read_text(encoding="utf-8"),
                }
            )
        except Exception as e:
            logger.warning(f"Failed to load {warning_label} {item}: {e}")
    return files


def _load_path_supporting_files(
    directory: Path,
    *,
    warning_label: str,
) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for item in directory.iterdir():
        if not item.is_file():
            continue
        try:
            files.append(
                {
                    "name": item.name,
                    "path": str(item),
                }
            )
        except Exception as e:
            logger.warning(f"Failed to scan {warning_label} {item}: {e}")
    return files


def _load_template_files(skill_dir: Path) -> dict[str, str]:
    templates: dict[str, str] = {}
    for template_file in skill_dir.glob("template*.md"):
        try:
            templates[f"template_{template_file.stem}"] = template_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to load template {template_file}: {e}")
    return templates
