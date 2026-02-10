"""
工具Schema和元数据定义

定义工具的标准接口和元数据结构
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field
from enum import Enum


class ParameterType(str, Enum):
    """参数类型"""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    FILE = "file"


class ToolParameter(BaseModel):
    """工具参数定义"""
    name: str = Field(..., description="参数名")
    type: ParameterType = Field(..., description="参数类型")
    description: str = Field(..., description="参数描述")
    required: bool = Field(default=False, description="是否必需")
    default: Any = Field(None, description="默认值")
    enum: Optional[List[Any]] = Field(None, description="枚举值")
    min_value: Optional[float] = Field(None, description="最小值（数字类型）")
    max_value: Optional[float] = Field(None, description="最大值（数字类型）")


class ToolSchema(BaseModel):
    """工具Schema"""
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    category: str = Field(..., description="工具分类")
    version: str = Field(default="1.0.0", description="工具版本")
    author: str = Field(default="Magi Team", description="作者")
    parameters: List[ToolParameter] = Field(default_factory=list, description="参数列表")
    examples: List[Dict[str, Any]] = Field(default_factory=list, description="使用示例")

    # 执行配置
    timeout: int = Field(default=30, description="超时时间（秒）")
    retry_on_failure: bool = Field(default=False, description="失败时是否重试")
    max_retries: int = Field(default=3, description="最大重试次数")

    # 权限和安全
    requires_auth: bool = Field(default=False, description="是否需要认证")
    allowed_roles: List[str] = Field(default_factory=list, description="允许的角色")
    dangerous: bool = Field(default=False, description="是否危险操作")

    # 元数据
    tags: List[str] = Field(default_factory=list, description="标签")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="其他元数据")


class ToolExecutionContext(BaseModel):
    """工具执行上下文"""
    agent_id: str
    task_id: Optional[str] = None
    workspace: str = Field(default="./workspace", description="工作目录")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="环境变量")
    permissions: List[str] = Field(default_factory=list, description="权限列表")


class ToolResult(BaseModel):
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Tool(ABC):
    """
    工具基类

    所有工具都应该继承此类并实现execute方法
    """

    def __init__(self):
        self.schema: Optional[ToolSchema] = None
        self._init_schema()

    @abstractmethod
    def _init_schema(self) -> None:
        """
        初始化工具Schema

        子类必须实现此方法来定义工具的元数据
        """
        pass

    @abstractmethod
    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        执行工具

        Args:
            parameters: 工具参数
            context: 执行上下文

        Returns:
            执行结果
        """
        pass

    async def validate_parameters(
        self,
        parameters: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        验证参数

        Args:
            parameters: 待验证的参数

        Returns:
            (是否有效, 错误信息)
        """
        if not self.schema:
            return True, None

        # 检查必需参数
        for param in self.schema.parameters:
            if param.required and param.name not in parameters:
                return False, f"Missing required parameter: {param.name}"

            # 检查类型
            if param.name in parameters:
                value = parameters[param.name]

                # 类型验证
                if param.type == ParameterType.STRING:
                    if not isinstance(value, str):
                        return False, f"Parameter {param.name} must be a string"
                elif param.type == ParameterType.INTEGER:
                    if not isinstance(value, int):
                        return False, f"Parameter {param.name} must be an integer"
                elif param.type == ParameterType.FLOAT:
                    if not isinstance(value, (int, float)):
                        return False, f"Parameter {param.name} must be a number"
                elif param.type == ParameterType.BOOLEAN:
                    if not isinstance(value, bool):
                        return False, f"Parameter {param.name} must be a boolean"
                elif param.type == ParameterType.ARRAY:
                    if not isinstance(value, list):
                        return False, f"Parameter {param.name} must be an array"
                elif param.type == ParameterType.OBJECT:
                    if not isinstance(value, dict):
                        return False, f"Parameter {param.name} must be an object"

                # 枚举值验证
                if param.enum and value not in param.enum:
                    return False, f"Parameter {param.name} must be one of {param.enum}"

                # 范围验证
                if param.min_value is not None and isinstance(value, (int, float)):
                    if value < param.min_value:
                        return False, f"Parameter {param.name} must be >= {param.min_value}"

                if param.max_value is not None and isinstance(value, (int, float)):
                    if value > param.max_value:
                        return False, f"Parameter {param.name} must be <= {param.max_value}"

        return True, None

    async def before_execution(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> tuple[bool, Optional[str]]:
        """
        执行前钩子

        子类可以重写此方法来实现自定义的执行前逻辑
        """
        return True, None

    async def after_execution(
        self,
        result: ToolResult,
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        执行后钩子

        子类可以重写此方法来实现自定义的执行后逻辑
        """
        return result

    def get_schema(self) -> ToolSchema:
        """获取工具Schema"""
        return self.schema

    def get_info(self) -> Dict[str, Any]:
        """获取工具信息"""
        return {
            "name": self.schema.name if self.schema else "Unknown",
            "description": self.schema.description if self.schema else "",
            "category": self.schema.category if self.schema else "unknown",
            "parameters": [p.dict() for p in self.schema.parameters] if self.schema else [],
            "examples": self.schema.examples if self.schema else [],
            "version": self.schema.version if self.schema else "1.0.0",
            "dangerous": self.schema.dangerous if self.schema else False,
        }

    def to_claude_format(self) -> Dict[str, Any]:
        """
        转换为 Claude Tool Use API 格式

        Claude tools 定义格式：
        {
            "name": "tool_name",
            "description": "Tool description",
            "input_schema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "..."}
                },
                "required": ["param1"]
            }
        }

        Returns:
            Claude tools API 格式的工具定义
        """
        if not self.schema:
            return {}

        # 构建 properties
        properties = {}
        required = []

        for param in self.schema.parameters:
            prop_def = {
                "type": param.type.value,
                "description": param.description,
            }

            # 添加默认值
            if param.default is not None:
                prop_def["default"] = param.default

            # 添加枚举值
            if param.enum:
                prop_def["enum"] = param.enum

            # 添加范围限制
            if param.min_value is not None:
                prop_def["min"] = param.min_value
            if param.max_value is not None:
                prop_def["max"] = param.max_value

            properties[param.name] = prop_def

            # 收集必需参数
            if param.required:
                required.append(param.name)

        input_schema = {
            "type": "object",
            "properties": properties,
        }

        if required:
            input_schema["required"] = required

        return {
            "name": self.schema.name,
            "description": self.schema.description,
            "input_schema": input_schema,
        }

    @classmethod
    def from_claude_format(cls, tool_def: Dict[str, Any]) -> 'Tool':
        """
        从 Claude Tool Use API 格式创建工具定义

        Args:
            tool_def: Claude 格式的工具定义

        Returns:
            ToolSchema 对象
        """
        from . import registry

        # 这是一个类方法，但实际创建工具需要具体的工具类
        # 这里只返回 schema，实际工具需要由具体的工具类实现
        parameters = []

        input_schema = tool_def.get("input_schema", {})
        props = input_schema.get("properties", {})
        required_list = input_schema.get("required", [])

        for param_name, param_def in props.items():
            param_type = ParameterType.STRING
            if "type" in param_def:
                try:
                    param_type = ParameterType(param_def["type"])
                except ValueError:
                    param_type = ParameterType.STRING

            parameters.append(ToolParameter(
                name=param_name,
                type=param_type,
                description=param_def.get("description", ""),
                required=param_name in required_list,
                default=param_def.get("default"),
                enum=param_def.get("enum"),
                min_value=param_def.get("min"),
                max_value=param_def.get("max"),
            ))

        return ToolSchema(
            name=tool_def.get("name", "unknown"),
            description=tool_def.get("description", ""),
            category="external",  # 从 Claude 导入的工具默认为 external
            parameters=parameters,
        )
