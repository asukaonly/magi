"""
Capabilities Tool - List all available tools and skills
"""
from typing import Dict, Any, List
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType
from ..registry import tool_registry


class CapabilitiesTool(Tool):
    """
    Capabilities Tool

    Lists all available tools and skills with their descriptions.
    """

    def _init_schema(self) -> None:
        """Initialize Schema"""
        self.schema = ToolSchema(
            name="get-capabilities",
            description="List all available tools and skills. Use this to discover what capabilities are available.",
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="filter_type",
                    type=ParameterType.STRING,
                    description="Filter by type: 'all', 'tools', or 'skills'",
                    required=False,
                    default="all",
                    enum=["all", "tools", "skills"],
                ),
                ToolParameter(
                    name="category",
                    type=ParameterType.STRING,
                    description="Filter by category (optional)",
                    required=False,
                    default=None,
                ),
            ],
            examples=[
                {
                    "input": {"filter_type": "all"},
                    "output": "Returns all tools and skills",
                },
                {
                    "input": {"filter_type": "tools", "category": "system"},
                    "output": "Returns only system tools",
                },
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=False,
            tags=["system", "discovery", "info"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute capabilities query"""
        filter_type = parameters.get("filter_type", "all")
        category = parameters.get("category")

        tools_list: List[Dict[str, Any]] = []
        skills_list: List[Dict[str, Any]] = []

        # Get tools
        if filter_type in ["all", "tools"]:
            tool_names = tool_registry.list_tools(category=category)
            for name in tool_names:
                info = tool_registry.get_tool_info(name)
                if info:
                    tools_list.append({
                        "name": info["name"],
                        "description": info["description"],
                        "category": info["category"],
                        "parameters": info.get("parameters", []),
                        "dangerous": info.get("dangerous", False),
                    })

        # Get skills
        if filter_type in ["all", "skills"]:
            for skill_name in tool_registry.get_skill_names():
                metadata = tool_registry.get_skill_metadata(skill_name)
                if metadata:
                    # Apply category filter if specified
                    if category and metadata.category != category:
                        continue
                    skills_list.append({
                        "name": metadata.name,
                        "description": metadata.description,
                        "category": metadata.category or "skill",
                        "argument_hint": metadata.argument_hint,
                        "user_invocable": metadata.user_invocable,
                        "tags": metadata.tags,
                    })

        # Build summary
        summary_parts = []
        if filter_type in ["all", "tools"]:
            summary_parts.append(f"{len(tools_list)} tools")
        if filter_type in ["all", "skills"]:
            summary_parts.append(f"{len(skills_list)} skills")

        summary = f"Available: {', '.join(summary_parts)}"
        if category:
            summary += f" in category '{category}'"

        return ToolResult(
            success=True,
            data={
                "tools": tools_list,
                "skills": skills_list,
                "summary": summary,
                "total_tools": len(tools_list),
                "total_skills": len(skills_list),
            },
        )
