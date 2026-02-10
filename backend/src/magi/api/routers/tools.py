"""
工具管理API路由

提供工具的列表、详情、测试等功能
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

tools_router = APIRouter()


# ============ 数据模型 ============

class ToolResponse(BaseModel):
    """工具响应"""

    name: str
    description: str
    category: str
    parameters: Dict[str, Any]
    examples: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class ToolTestRequest(BaseModel):
    """工具测试请求"""

    parameters: Dict[str, Any] = Field(default_factory=dict, description="测试参数")


# ============ 内存存储（开发用） ============

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


# ============ API端点 ============

@tools_router.get("/", response_model=List[ToolResponse])
async def list_tools(
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    获取工具列表

    Args:
        category: 过滤工具分类
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        工具列表
    """
    tools = list(_tools_store.values())

    # 过滤
    if category:
        tools = [t for t in tools if t["category"] == category]

    # 分页
    tools = tools[offset:offset + limit]

    return tools


@tools_router.get("/{tool_name}", response_model=ToolResponse)
async def get_tool(tool_name: str):
    """
    获取工具详情

    Args:
        tool_name: 工具名称

    Returns:
        工具详情
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
    测试工具

    Args:
        tool_name: 工具名称
        request: 测试请求

    Returns:
        测试结果
    """
    if tool_name not in _tools_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {tool_name} not found",
        )

    # TODO: 实际执行工具测试
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


@tools_router.get("/categories/list")
async def list_tool_categories():
    """
    获取工具分类列表

    Returns:
        工具分类列表
    """
    categories = set(t["category"] for t in _tools_store.values())

    return {
        "success": True,
        "data": list(categories),
    }


@tools_router.get("/export/claude")
async def export_tools_claude_format():
    """
    导出工具定义为 Claude Tool Use API 格式

    Returns:
        Claude tools API 格式的工具定义列表
    """
    from ...tools import tool_registry

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
    从 Claude Tool Use API 格式导入工具

    Args:
        tools: Claude 格式的工具定义列表

    Returns:
        导入结果
    """
    from ...tools import tool_registry

    imported = []
    failed = []

    for tool_def in tools:
        try:
            # 创建动态工具的执行器
            async def executor(name, params):
                # 这里只是一个占位符，实际使用时需要提供真实的执行逻辑
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
