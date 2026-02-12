"""
Skills Creator Tool - Create new skills in user's ~/.magi/skills directory
"""
import os
import re
from pathlib import Path
from typing import Dict, Any, List
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType


class SkillsCreatorTool(Tool):
    """
    Skills Creator Tool

    Create new skills in the user's ~/.magi/skills directory.
    """

    def _init_schema(self) -> None:
        """Initialize Schema"""
        self.schema = ToolSchema(
            name="skills-creator",
            description="Create a new skill in the ~/.magi/skills directory. Skills extend the agent's capabilities with specialized knowledge and workflows.",
            category="skills",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="name",
                    type=ParameterType.STRING,
                    description="Skill name (alphanumeric with hyphens, e.g., 'code-review')",
                    required=True,
                ),
                ToolParameter(
                    name="description",
                    type=ParameterType.STRING,
                    description="Brief description of what the skill does",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type=ParameterType.STRING,
                    description="The skill content in markdown format (the main prompt/instructions)",
                    required=True,
                ),
                ToolParameter(
                    name="category",
                    type=ParameterType.STRING,
                    description="Category for organizing skills (optional)",
                    required=False,
                    default=None,
                ),
                ToolParameter(
                    name="argument_hint",
                    type=ParameterType.STRING,
                    description="Hint for how to invoke the skill with arguments (optional)",
                    required=False,
                    default=None,
                ),
                ToolParameter(
                    name="tags",
                    type=ParameterType.ARRAY,
                    description="List of tags for the skill (optional)",
                    required=False,
                    default=[],
                ),
                ToolParameter(
                    name="user_invocable",
                    type=ParameterType.BOOLEAN,
                    description="Whether users can directly invoke this skill",
                    required=False,
                    default=True,
                ),
            ],
            examples=[
                {
                    "input": {
                        "name": "code-review",
                        "description": "Review code for best practices and potential issues",
                        "content": "Review the provided code...\n\n## Checklist\n- Check for bugs\n- Review patterns\n- Suggest improvements",
                        "category": "development",
                        "tags": ["code", "review", "quality"]
                    },
                    "output": "Creates skill at ~/.magi/skills/code-review/SKILL.md",
                },
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=False,
            tags=["skills", "create", "extend"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute skill creation"""
        name = parameters["name"]
        description = parameters["description"]
        content = parameters["content"]
        category = parameters.get("category")
        argument_hint = parameters.get("argument_hint")
        tags = parameters.get("tags", [])
        user_invocable = parameters.get("user_invocable", True)

        # Validate name
        if not re.match(r'^[a-z0-9-]+$', name):
            return ToolResult(
                success=False,
                error="Skill name must be lowercase alphanumeric with hyphens only (e.g., 'my-skill')",
                error_code="INVALID_NAME",
            )

        # Get skills directory
        skills_dir = self._get_skills_directory()

        # Create skill directory
        skill_dir = skills_dir / name
        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to create skill directory: {e}",
                error_code="DIR_CREATE_ERROR",
            )

        # Build frontmatter
        frontmatter_lines = ["---"]
        frontmatter_lines.append(f'name: "{name}"')
        frontmatter_lines.append(f'description: "{self._escape_yaml(description)}"')

        if argument_hint:
            frontmatter_lines.append(f'argument_hint: "{self._escape_yaml(argument_hint)}"')

        frontmatter_lines.append(f'user_invocable: {str(user_invocable).lower()}')

        if category:
            frontmatter_lines.append(f'category: "{self._escape_yaml(category)}"')

        if tags:
            tags_str = ", ".join([f'"{t}"' for t in tags])
            frontmatter_lines.append(f"tags: [{tags_str}]")

        frontmatter_lines.append("---")
        frontmatter_lines.append("")

        # Build full content
        full_content = "\n".join(frontmatter_lines) + content

        # Write SKILL.md
        skill_file = skill_dir / "SKILL.md"
        try:
            skill_file.write_text(full_content, encoding="utf-8")
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Failed to write skill file: {e}",
                error_code="WRITE_ERROR",
            )

        return ToolResult(
            success=True,
            data={
                "name": name,
                "path": str(skill_file),
                "message": f"Skill '{name}' created successfully at {skill_file}",
            },
        )

    def _get_skills_directory(self) -> Path:
        """Get the user's skills directory"""
        # Check for custom skills directory
        custom_dir = os.environ.get("MAGI_SKILLS_DIR")
        if custom_dir:
            return Path(custom_dir)

        # Default to ~/.magi/skills
        home = Path.home()
        return home / ".magi" / "skills"

    def _escape_yaml(self, value: str) -> str:
        """Escape special characters for YAML"""
        # Escape double quotes
        return value.replace('"', '\\"')
