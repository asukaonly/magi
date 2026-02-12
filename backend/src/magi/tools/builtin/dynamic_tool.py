"""
Dynamic Tool - 支持从外部格式（如 Claude Tool Use）动态创建工具
"""
from typing import Any, Dict, Optional
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult


class DynamicTool(Tool):
    """
    动态工具基类

    支持从外部格式（如 Claude Tool Use API）动态创建工具
    """

    def __init__(self, schema: Optional[ToolSchema] = None):
        super().__init__()
        if schema:
            self.schema = schema

    def _init_schema(self) -> None:
        """
        初始化 Schema

        子类应该设置 self.schema 或传入 schema 参数
        """
        if not hasattr(self, 'schema') or self.schema is None:
            # 创建默认 schema
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
        执行工具

        子类应该重写此方法或设置 _executor
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
                    error_code="EXECUTION_ERROR"
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
    创建动态工具

    Args:
        name: 工具名称
        description: 工具描述
        parameters: Claude 格式的参数定义
        executor: 执行函数 async def execute(params) -> Any
        **kwargs: 其他 ToolSchema 参数

    Returns:
        DynamicTool 实例
    """
    from ..schema import ToolParameter, ParameterType

    param_objects = []
    for param_def in parameters:
        param_type = ParameterType.STRING
        if "type" in param_def:
            try:
                param_type = ParameterType(param_def["type"])
            except ValueError:
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

    # 创建动态工具类
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
