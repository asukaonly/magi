"""
Tool Management API Router

Provides tool listing, details, testing and other functions
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
import logging

logger = logging.getLogger(__name__)

tools_router = APIRouter()


def _ensure_plugins_loaded() -> None:
    from ...plugins import get_plugin_manager

    get_plugin_manager()


# ============ data Models ============

class ToolResponse(BaseModel):
    """Tool response"""

    name: str
    description: str
    category: str
    parameters: Dict[str, Any]
    examples: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class ToolTestRequest(BaseModel):
    """Tool test request"""

    parameters: Dict[str, Any] = Field(default_factory=dict, description="Test parameters")


# ============ Tool Config Models ============

class ToolProviderInfo(BaseModel):
    """Provider information for multi-provider tools"""
    name: str = Field(..., description="Provider identifier")
    display_name: str = Field(..., description="Human-readable provider name")
    is_ready: bool = Field(..., description="Whether provider is configured and ready")
    required_config: List[str] = Field(default_factory=list, description="Required config paths")


class ToolConfigSpecResponse(BaseModel):
    """Tool config spec for API response"""
    path: str = Field(..., description="Config path (relative to tool namespace)")
    type: Literal["string", "integer", "float", "boolean", "array", "object"] = Field(
        default="string", description="Config value type"
    )
    description: str = Field(default="", description="Config item description")
    sensitive: bool = Field(default=False, description="Can be set but not read")
    read_only: bool = Field(default=False, description="Cannot be changed")
    required: bool = Field(default=False, description="Whether this config is required")
    default: Optional[Any] = Field(default=None, description="Default value")
    enum: Optional[List[Any]] = Field(default=None, description="Enum values for selection")
    placeholder: Optional[str] = Field(default=None, description="Input placeholder hint")
    is_template: bool = Field(default=False, description="Whether this is a template path (e.g., providers.{provider}.api_key)")
    providers: Optional[List[str]] = Field(default=None, description="Providers that this spec applies to")


class ToolConfigResponse(BaseModel):
    """Tool configuration response"""
    name: str = Field(..., description="Tool name")
    display_name: str = Field(..., description="Human-readable tool name")
    description: str = Field(..., description="Tool description")
    category: str = Field(..., description="Tool category")
    version: str = Field(default="1.0.0", description="Tool version")
    enabled: bool = Field(default=True, description="Whether tool is enabled")
    is_ready: bool = Field(default=True, description="Whether tool is configured and ready")
    is_multi_provider: bool = Field(default=False, description="Whether this is a multi-provider tool")
    providers: List[ToolProviderInfo] = Field(default_factory=list, description="Available providers")
    config_specs: List[ToolConfigSpecResponse] = Field(default_factory=list, description="Config specifications")
    current_values: Dict[str, Any] = Field(default_factory=dict, description="Current config values (non-sensitive)")


class ToolsListResponse(BaseModel):
    """Tools list response with config info"""
    tools: List[ToolConfigResponse] = Field(..., description="List of tools with config info")
    total: int = Field(..., description="Total number of tools")


class ToolConfigUpdateRequest(BaseModel):
    """Tool config update request"""
    updates: Dict[str, Any] = Field(..., description="Config updates (path -> value)")
    enabled: Optional[bool] = Field(default=None, description="Update enabled status")


# ============ In-memory Storage (for development) ============

_tools_store: Dict[str, Dict] = {
    "web_search": {
        "name": "web_search",
        "description": "Search the web for information",
        "category": "search",
        "parameters": {
            "query": {
                "type": "string",
                "description": "Search query",
                "required": True,
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return",
                "default": 10,
            },
        },
        "examples": [
            {
                "input": {"query": "Python programming"},
                "output": "Returns search results about Python programming",
            }
        ],
        "metadata": {
            "version": "1.0.0",
            "author": "Magi Team",
            "timeout": 30,
        },
    },
    "file_read": {
        "name": "file_read",
        "description": "Read content from a file",
        "category": "file",
        "parameters": {
            "path": {
                "type": "string",
                "description": "File path",
                "required": True,
            },
        },
        "examples": [
            {
                "input": {"path": "/path/to/file.txt"},
                "output": "Returns file content",
            }
        ],
        "metadata": {
            "version": "1.0.0",
            "author": "Magi Team",
            "timeout": 10,
        },
    },
}


# ============ API Endpoints ============

@tools_router.get("/", response_model=List[ToolResponse])
async def list_tools(
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    Get tool list

    Args:
        category: Filter tool category
        limit: Return quantity limit
        offset: Offset

    Returns:
        Tool list
    """
    _ensure_plugins_loaded()
    tools = list(_tools_store.values())

    # Filter
    if category:
        tools = [t for t in tools if t["category"] == category]

    # Pagination
    tools = tools[offset:offset + limit]

    return tools


@tools_router.get("/categories/list")
async def list_tool_categories():
    """
    Get tool category list

    Returns:
        Tool category list
    """
    categories = set(t["category"] for t in _tools_store.values())

    return {
        "success": True,
        "data": list(categories),
    }


@tools_router.get("/export/claude")
async def export_tools_claude_format():
    """
    Export tool definitions in Claude Tool Use API format

    Returns:
        List of tool definitions in Claude tools API format
    """
    from ...tools import tool_registry
    _ensure_plugins_loaded()

    claude_tools = tool_registry.export_to_claude_format()

    return {
        "success": True,
        "data": claude_tools,
        "format": "claude_tool_use_api",
        "count": len(claude_tools),
    }


@tools_router.post("/import/claude")
async def import_tools_claude_format(tools: List[Dict[str, Any]]):
    """
    Import tools from Claude Tool Use API format

    Args:
        tools: List of tool definitions in Claude format

    Returns:
        Import result
    """
    from ...tools import tool_registry
    _ensure_plugins_loaded()

    imported = []
    failed = []

    for tool_def in tools:
        try:
            # Create dynamic tool executor
            async def executor(name, params):
                # This is just a placeholder, actual usage requires providing real execution logic
                return f"Tool {name} executed with params: {params}"

            from ...tools.builtin import create_dynamic_tool

            dynamic_tool = create_dynamic_tool(
                name=tool_def.get("name", "unknown"),
                description=tool_def.get("description", ""),
                parameters=tool_def.get("input_schema", {}).get("properties", []),
                executor=executor,
            )

            tool_registry.register(dynamic_tool)
            imported.append(tool_def.get("name"))

        except Exception as e:
            failed.append({
                "name": tool_def.get("name", "unknown"),
                "error": str(e)
            })

    return {
        "success": True,
        "data": {
            "imported": imported,
            "failed": failed,
        },
        "message": f"Imported {len(imported)} tools, {len(failed)} failed",
    }


# ============ Tool Config Endpoints ============

def _get_tool_display_name(tool_name: str) -> str:
    """Convert tool name to display name"""
    name_map = {
        "web-search": "Web Search",
        "weather": "Weather",
        "web-fetch": "Web Fetch",
        "bash": "Bash",
        "file-read": "File Read",
        "file-write": "File Write",
        "file-list": "File List",
        "capabilities": "Capabilities",
        "skills-creator": "Skills Creator",
        "system-settings": "System Settings",
    }
    return name_map.get(tool_name, tool_name.replace("-", " ").title())


def _is_multi_provider_tool(tool) -> bool:
    """Check if tool is a multi-provider tool"""
    from ...tools.schema import MultiProviderTool
    return isinstance(tool, MultiProviderTool)


def _get_provider_display_name(provider_name: str) -> str:
    """Convert provider name to display name"""
    name_map = {
        "duckduckgo": "DuckDuckGo",
        "brave": "Brave Search",
        "perplexity": "Perplexity AI",
        "tavily": "Tavily",
        "qweather": "QWeather",
        "openweather": "OpenWeather",
    }
    return name_map.get(provider_name, provider_name.replace("-", " ").title())


def _build_tool_config_response(tool_name: str, tool) -> ToolConfigResponse:
    """Build ToolConfigResponse from a tool instance"""
    schema = tool.get_schema()
    config_specs_raw = tool.list_config_specs()

    # Convert config specs to response format
    config_specs = []
    for spec in config_specs_raw:
        is_template = "{provider}" in spec.path or "{provider}" in str(spec.path)
        config_specs.append(ToolConfigSpecResponse(
            path=spec.path,
            type=spec.type,
            description=spec.description,
            sensitive=spec.sensitive,
            read_only=spec.read_only,
            required=getattr(spec, 'required', False),
            default=getattr(spec, 'default', None),
            enum=getattr(spec, 'enum', None),
            placeholder=getattr(spec, 'placeholder', None),
            is_template=is_template,
            providers=getattr(spec, 'providers', None),
        ))

    # Build providers info for multi-provider tools
    providers = []
    is_multi_provider = _is_multi_provider_tool(tool)
    if is_multi_provider:
        all_providers = tool.get_all_provider_names()
        available_providers = tool.get_available_providers()
        for provider_name in all_providers:
            required_config = _required_provider_paths(config_specs_raw, provider_name)
            providers.append(ToolProviderInfo(
                name=provider_name,
                display_name=_get_provider_display_name(provider_name),
                is_ready=provider_name in available_providers,
                required_config=required_config,
            ))

    # Get current values (non-sensitive)
    current_values = {}
    from ...config import get_config
    config = get_config()

    # Get tool enabled status from config
    tool_enabled = True
    if tool_name == "weather":
        tool_enabled = config.tools.weather.enabled
        current_values["default_provider"] = config.tools.weather.default_provider
        current_values.update(_provider_current_values(config.tools.weather.providers, config_specs_raw))
    elif tool_name == "web-search":
        tool_enabled = config.tools.web_search.enabled
        current_values["default_provider"] = config.tools.web_search.default_provider
        current_values.update(_provider_current_values(config.tools.web_search.providers, config_specs_raw))
    elif tool_name == "web-fetch":
        tool_enabled = config.tools.web_fetch.enabled
        current_values["default_provider"] = config.tools.web_fetch.default_provider

    return ToolConfigResponse(
        name=tool_name,
        display_name=_get_tool_display_name(tool_name),
        description=schema.description if schema else "",
        category=schema.category if schema else "general",
        version=schema.version if schema else "1.0.0",
        enabled=tool_enabled,
        is_ready=tool.is_ready(),
        is_multi_provider=is_multi_provider,
        providers=providers,
        config_specs=config_specs,
        current_values=current_values,
    )


def _required_provider_paths(config_specs_raw: list[Any], provider_name: str) -> list[str]:
    required_paths: list[str] = []

    for spec in config_specs_raw:
        if not getattr(spec, "required", False):
            continue

        supported_providers = getattr(spec, "providers", None)
        if supported_providers and provider_name not in supported_providers:
            continue

        path = str(spec.path)
        if "{provider}" in path:
            required_paths.append(path.replace("{provider}", provider_name))
        elif f"providers.{provider_name}." in path:
            required_paths.append(path)

    return required_paths


def _provider_current_values(
    provider_configs: dict[str, Any],
    config_specs_raw: list[Any],
) -> dict[str, Any]:
    values: dict[str, Any] = {}

    for spec in config_specs_raw:
        path = str(spec.path)
        supported_providers = getattr(spec, "providers", None) or list(provider_configs.keys())
        if path == "default_provider":
            continue
        if "{provider}" not in path:
            continue

        field_name = path.split(".")[-1]
        for provider_name in supported_providers:
            config = provider_configs.get(provider_name)
            if config is None or not hasattr(config, field_name):
                continue
            values[path.replace("{provider}", provider_name)] = getattr(config, field_name)

    return values


@tools_router.get("/config", response_model=ToolsListResponse)
async def list_tools_with_config():
    """
    Get all tools with their configuration information.

    Returns:
        List of tools with config specs and current values
    """
    from ...tools import tool_registry
    _ensure_plugins_loaded()

    tools_response = []
    tool_names = tool_registry.list_tools()

    for tool_name in tool_names:
        tool = tool_registry.get_tool(tool_name)
        if tool:
            tools_response.append(_build_tool_config_response(tool_name, tool))

    return ToolsListResponse(
        tools=tools_response,
        total=len(tools_response),
    )


@tools_router.get("/{tool_name}/config", response_model=ToolConfigResponse)
async def get_tool_config(tool_name: str):
    """
    Get configuration information for a specific tool.

    Args:
        tool_name: Tool name

    Returns:
        Tool config details
    """
    from ...tools import tool_registry
    _ensure_plugins_loaded()

    tool = tool_registry.get_tool(tool_name)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_name} not found",
        )

    return _build_tool_config_response(tool_name, tool)


@tools_router.put("/{tool_name}/config")
async def update_tool_config(tool_name: str, request: ToolConfigUpdateRequest):
    """
    Update tool configuration.

    Args:
        tool_name: Tool name
        request: Config update request

    Returns:
        Update result
    """
    from ...tools import tool_registry
    from ...config import save_config, reload_config
    _ensure_plugins_loaded()

    tool = tool_registry.get_tool(tool_name)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_name} not found",
        )

    # Build config updates with full path
    config_updates = {}
    for path, value in request.updates.items():
        full_path = f"tools.{tool_name.replace('-', '_')}.{path}"
        config_updates[full_path] = value

    # Handle enabled status
    if request.enabled is not None:
        full_path = f"tools.{tool_name.replace('-', '_')}.enabled"
        config_updates[full_path] = request.enabled

    if not config_updates:
        return {"success": True, "message": "No updates to apply"}

    # Save configuration
    if save_config(config_updates):
        # Reload config to apply changes
        reload_config()

        logger.info(
            "Tool %s config updated: %s",
            tool_name,
            list(request.updates.keys()),
        )

        return {
            "success": True,
            "message": f"Tool {tool_name} configuration updated",
            "updated_keys": list(request.updates.keys()),
        }

    return {
        "success": False,
        "message": "Failed to save configuration",
    }


@tools_router.get("/{tool_name}", response_model=ToolResponse)
async def get_tool(tool_name: str):
    """
    Get tool details

    Args:
        tool_name: Tool name

    Returns:
        Tool details
    """
    if tool_name not in _tools_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_name} not found",
        )

    return _tools_store[tool_name]


@tools_router.post("/{tool_name}/test")
async def test_tool(tool_name: str, request: ToolTestRequest):
    """
    Test tool

    Args:
        tool_name: Tool name
        request: Test request

    Returns:
        Test result
    """
    if tool_name not in _tools_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_name} not found",
        )

    # TODO: Actual tool test execution
    logger.info(f"Testing tool: {tool_name} with params: {request.parameters}")

    return {
        "success": True,
        "message": f"Tool {tool_name} test executed",
        "data": {
            "tool_name": tool_name,
            "parameters": request.parameters,
            "result": "Test result (mock)",
        },
    }
