"""
toolSchemaandmetadata定义

定义tool的standardInterfaceandmetadatastructure
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, type
from pydantic import BaseModel, Field
from enum import Enum


class Parametertype(str, Enum):
    """Parametertype"""
    strING = "string"
    intEGER = "integer"
    float = "float"
    boolEAN = "boolean"
    array = "array"
    object = "object"
    FILE = "file"


class ToolParameter(BaseModel):
    """toolParameter定义"""
    name: str = Field(..., description="Parameter名")
    type: Parametertype = Field(..., description="Parametertype")
    description: str = Field(..., description="ParameterDescription")
    required: bool = Field(default=False, description="is not必需")
    default: Any = Field(None, description="defaultValue")
    enum: Optional[List[Any]] = Field(None, description="枚举Value")
    min_value: Optional[float] = Field(None, description="minimumValue（numbertype）")
    max_value: Optional[float] = Field(None, description="maximumValue（numbertype）")


class ToolSchema(BaseModel):
    """toolSchema"""
    name: str = Field(..., description="toolName")
    description: str = Field(..., description="toolDescription")
    category: str = Field(..., description="tool分Class")
    version: str = Field(default="1.0.0", description="toolversion")
    author: str = Field(default="Magi Team", description="作者")
    parameters: List[ToolParameter] = Field(default_factory=list, description="Parameterlist")
    examples: List[Dict[str, Any]] = Field(default_factory=list, description="使用Example")

    # ExecuteConfiguration
    timeout: int = Field(default=30, description="timeout时间（seconds）")
    retry_on_failure: bool = Field(default=False, description="failure时is not重试")
    max_retries: int = Field(default=3, description="maximum重试count")

    # permissionandsafe
    requires_auth: bool = Field(default=False, description="is not需要authentication")
    allowed_roles: List[str] = Field(default_factory=list, description="允许的role")
    dangerous: bool = Field(default=False, description="is notdangerousoperation")

    # metadata
    tags: List[str] = Field(default_factory=list, description="label")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="othermetadata")


class ToolExecutionContext(BaseModel):
    """toolExecutecontext"""
    agent_id: str
    task_id: Optional[str] = None
    workspace: str = Field(default="./workspace", description="工作directory")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="环境Variable")
    permissions: List[str] = Field(default_factory=list, description="permissionlist")


class ToolResult(BaseModel):
    """toolExecution result"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Tool(ABC):
    """
    toolBase class

    alltool都应该继承此Class并ImplementationexecuteMethod
    """

    def __init__(self):
        self.schema: Optional[ToolSchema] = None
        self._init_schema()

    @abstractmethod
    def _init_schema(self) -> None:
        """
        initializetoolSchema

        子Class必须Implementation此Method来定义tool的metadata
        """
        pass

    @abstractmethod
    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        Executetool

        Args:
            parameters: toolParameter
            context: Executecontext

        Returns:
            Execution result
        """
        pass

    async def validate_parameters(
        self,
        parameters: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        ValidateParameter

        Args:
            parameters: 待Validate的Parameter

        Returns:
            (is notvalid, errorinfo)
        """
        if not self.schema:
            return True, None

        # check必需Parameter
        for param in self.schema.parameters:
            if param.required and param.name not in parameters:
                return False, f"Missing required parameter: {param.name}"

            # checktype
            if param.name in parameters:
                value = parameters[param.name]

                # typeValidate
                if param.type == Parametertype.strING:
                    if not isinstance(value, str):
                        return False, f"Parameter {param.name} must be a string"
                elif param.type == Parametertype.intEGER:
                    if not isinstance(value, int):
                        return False, f"Parameter {param.name} must be an integer"
                elif param.type == Parametertype.float:
                    if not isinstance(value, (int, float)):
                        return False, f"Parameter {param.name} must be a number"
                elif param.type == Parametertype.boolEAN:
                    if not isinstance(value, bool):
                        return False, f"Parameter {param.name} must be a boolean"
                elif param.type == Parametertype.array:
                    if not isinstance(value, list):
                        return False, f"Parameter {param.name} must be an array"
                elif param.type == Parametertype.object:
                    if not isinstance(value, dict):
                        return False, f"Parameter {param.name} must be an object"

                # 枚举ValueValidate
                if param.enum and value not in param.enum:
                    return False, f"Parameter {param.name} must be one of {param.enum}"

                # rangeValidate
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
        Execute前钩子

        子Class可以重写此Method来Implementationcustom的Execute前逻辑
        """
        return True, None

    async def after_execution(
        self,
        result: ToolResult,
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        Execute后钩子

        子Class可以重写此Method来Implementationcustom的Execute后逻辑
        """
        return result

    def get_schema(self) -> ToolSchema:
        """gettoolSchema"""
        return self.schema

    def get_info(self) -> Dict[str, Any]:
        """gettoolinfo"""
        return {
            "name": self.schema.name if self.schema else "Unknotttwn",
            "description": self.schema.description if self.schema else "",
            "category": self.schema.category if self.schema else "unknotttwn",
            "parameters": [p.dict() for p in self.schema.parameters] if self.schema else [],
            "examples": self.schema.examples if self.schema else [],
            "version": self.schema.version if self.schema else "1.0.0",
            "dangerous": self.schema.dangerous if self.schema else False,
        }

    def to_claude_format(self) -> Dict[str, Any]:
        """
        convert为 Claude Tool Use API format

        Claude tools 定义format：
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
            Claude tools API format的tool定义
        """
        if not self.schema:
            return {}

        # build properties
        properties = {}
        required = []

        for param in self.schema.parameters:
            prop_def = {
                "type": param.type.value,
                "description": param.description,
            }

            # adddefaultValue
            if param.default is not None:
                prop_def["default"] = param.default

            # add枚举Value
            if param.enum:
                prop_def["enum"] = param.enum

            # addrangelimitation
            if param.min_value is not None:
                prop_def["min"] = param.min_value
            if param.max_value is not None:
                prop_def["max"] = param.max_value

            properties[param.name] = prop_def

            # 收集必需Parameter
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
        从 Claude Tool Use API formatcreatetool定义

        Args:
            tool_def: Claude format的tool定义

        Returns:
            ToolSchema Object
        """
        from . import registry

        # 这is一个ClassMethod，但实际createtool需要具体的toolClass
        # 这里只Return schema，实际tool需要由具体的toolClassImplementation
        parameters = []

        input_schema = tool_def.get("input_schema", {})
        props = input_schema.get("properties", {})
        required_list = input_schema.get("required", [])

        for param_name, param_def in props.items():
            param_type = Parametertype.strING
            if "type" in param_def:
                try:
                    param_type = Parametertype(param_def["type"])
                except Valueerror:
                    param_type = Parametertype.strING

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
            name=tool_def.get("name", "unknotttwn"),
            description=tool_def.get("description", ""),
            category="external",  # 从 Claude import的tooldefault为 external
            parameters=parameters,
        )
