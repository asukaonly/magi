"""
Dynamic Tool - Supports dynamically creating tools from external formats (like Claude Tool Use)
"""
from typing import Any, Dict, Optional
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult


class DynamicTool(Tool):
    """
    Dynamic Tool Base Class

    Supports dynamically creating tools from external formats (like Claude Tool Use API)
    """

    def __init__(self, schema: Optional[ToolSchema] = None):
        super().__init__()
        if schema:
            self.schema = schema

    def _init_schema(self) -> None:
        """
        initialize Schema

        Subclasses should set self.schema or pass in schema parameter
        """
        if not hasattr(self, 'schema') or self.schema is None:
            # Create default schema
            self.schema = ToolSchema(
                name=self.__class__.__name__,
                description="Dynamic tool",
                category="external",
                parameters=[],
            )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        Execute tool

        Subclasses should override this method or set _executor
        """
        if hasattr(self, '_executor'):
            try:
                result = await self._executor(self.schema.name, parameters)
                return ToolResult(
                    success=True,
                    data=result,
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=str(e),
                    error_code="EXECUTION_error"
                )

        return ToolResult(
            success=False,
            error="Dynamic tool executor not implemented",
            error_code="NOT_IMPLEMENTED"
        )


def create_dynamic_tool(
    name: str,
    description: str,
    parameters: list,
    executor: callable,
    **kwargs
) -> DynamicTool:
    """
    Create dynamic tool

    Args:
        name: Tool name
        description: Tool description
        parameters: Claude format parameter definition
        executor: Execution function async def execute(params) -> Any
        **kwargs: Other ToolSchema parameters

    Returns:
        DynamicTool instance
    """
    from ..schema import ToolParameter, Parametertype

    param_objects = []
    for param_def in parameters:
        param_type = Parametertype.strING
        if "type" in param_def:
            try:
                param_type = Parametertype(param_def["type"])
            except Valueerror:
                pass

        param_objects.append(ToolParameter(
            name=param_def.get("name", ""),
            type=param_type,
            description=param_def.get("description", ""),
            required=param_def.get("required", False),
            default=param_def.get("default"),
        ))

    schema = ToolSchema(
        name=name,
        description=description,
        category="external",
        parameters=param_objects,
        **kwargs
    )

    # Create dynamic tool class
    class CreatedDynamicTool(DynamicTool):
        def __init__(self):
            super().__init__(schema)

        async def execute(self, parameters, context):
            try:
                result = await executor(parameters)
                return ToolResult(success=True, data=result)
            except Exception as e:
                return ToolResult(success=False, error=str(e))

    return CreatedDynamicTool()
