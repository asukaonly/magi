"""
工具注册表和内置工具测试

测试工具注册、执行、批量执行等功能
"""
import asyncio
import sys
import os
import tempfile

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from magi.tools import (
    tool_registry,
    Tool,
    ToolSchema,
    ToolExecutionContext,
    ToolResult,
    ToolParameter,
    ParameterType,
)
from magi.tools.builtin import (
    BashTool,
    FileReadTool,
    FileWriteTool,
    FileListTool,
)


async def test_tool_registration():
    """测试工具注册"""
    print("\n=== 测试工具注册 ===")

    # 列出所有工具
    tools = tool_registry.list_tools()
    print(f"  已注册工具: {tools}")
    assert len(tools) >= 4, f"Should have at least 4 tools, got {len(tools)}"
    print("  ✓ 工具注册成功")

    # 获取工具信息
    for tool_name in tools[:2]:
        info = tool_registry.get_tool_info(tool_name)
        assert info is not None, f"Tool {tool_name} info should not be None"
        print(f"  ✓ {tool_name}: {info['description']}")


async def test_bash_tool():
    """测试Bash工具"""
    print("\n=== 测试Bash工具 ===")

    context = ToolExecutionContext(
        agent_id="test_agent",
        task_id="test_task",
        workspace=tempfile.gettempdir(),
    )

    # 测试pwd命令
    result = await tool_registry.execute(
        "bash",
        {"command": "pwd"},
        context
    )

    assert result.success, f"pwd command should succeed: {result.error}"
    assert result.data["return_code"] == 0, "pwd should succeed"
    print(f"  ✓ pwd执行成功: {result.data['stdout'].strip()}")

    # 测试ls命令
    result = await tool_registry.execute(
        "bash",
        {"command": "ls -la"},
        context
    )

    assert result.success, f"ls command should succeed: {result.error}"
    assert len(result.data["stdout"]) > 0, "ls should output something"
    print("  ✓ ls执行成功")

    # 测试错误命令
    result = await tool_registry.execute(
        "bash",
        {"command": "invalid_command_that_does_not_exist"},
        context
    )

    assert not result.success, "Invalid command should fail"
    print("  ✓ 错误命令正确处理")


async def test_file_operations():
    """测试文件操作工具"""
    print("\n=== 测试文件操作 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        context = ToolExecutionContext(
            agent_id="test_agent",
            task_id="test_task",
            workspace=tmpdir,
        )

        # 测试写入文件
        test_file = os.path.join(tmpdir, "test.txt")
        test_content = "Hello, Magi!"

        result = await tool_registry.execute(
            "file_write",
            {
                "path": test_file,
                "content": test_content,
            },
            context
        )

        assert result.success, f"file_write should succeed: {result.error}"
        assert result.data["bytes_written"] == len(test_content)
        print(f"  ✓ 写入文件: {result.data['bytes_written']} bytes")

        # 测试读取文件
        result = await tool_registry.execute(
            "file_read",
            {"path": test_file},
            context
        )

        assert result.success, f"file_read should succeed: {result.error}"
        assert result.data["content"] == test_content
        print(f"  ✓ 读取文件: {result.data['content']}")

        # 测试追加写入
        append_content = "\nAppended line"
        result = await tool_registry.execute(
            "file_write",
            {
                "path": test_file,
                "content": append_content,
                "mode": "append",
            },
            context
        )

        assert result.success, f"file_write append should succeed: {result.error}"
        print(f"  ✓ 追加写入: +{result.data['bytes_written']} bytes")

        # 验证追加
        result = await tool_registry.execute(
            "file_read",
            {"path": test_file},
            context
        )

        expected = test_content + append_content
        assert result.data["content"] == expected
        print(f"  ✓ 追加验证成功")

        # 测试列出文件
        result = await tool_registry.execute(
            "file_list",
            {"path": tmpdir},
            context
        )

        assert result.success, f"file_list should succeed: {result.error}"
        assert len(result.data["items"]) > 0
        print(f"  ✓ 列出文件: {result.data['count']} 个")

        # 测试模式过滤
        result = await tool_registry.execute(
            "file_list",
            {"path": tmpdir, "pattern": "*.txt"},
            context
        )

        assert result.success, f"file_list with pattern should succeed: {result.error}"
        assert any(item["name"] == "test.txt" for item in result.data["items"])
        print(f"  ✓ 模式过滤: 找到test.txt")


async def test_batch_execution():
    """测试批量执行"""
    print("\n=== 测试批量执行 ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        context = ToolExecutionContext(
            agent_id="test_agent",
            workspace=tmpdir,
        )

        # 准备命令列表
        commands = [
            {"tool": "bash", "parameters": {"command": "echo 'Line 1' > " + os.path.join(tmpdir, "test.txt")}},
            {"tool": "bash", "parameters": {"command": "echo 'Line 2' >> " + os.path.join(tmpdir, "test.txt")}},
            {"tool": "bash", "parameters": {"command": "cat " + os.path.join(tmpdir, "test.txt")}},
        ]

        # 串行执行
        results = await tool_registry.execute_batch(commands, context, parallel=False)

        assert len(results) == 3, f"Should have 3 results, got {len(results)}"
        assert results[0].success, f"First command should succeed: {results[0].error}"
        assert results[1].success, f"Second command should succeed: {results[1].error}"
        assert results[2].success, f"Third command should succeed: {results[2].error}"
        print(f"  ✓ 串行执行: {len(results)} 个命令")

        # 验证输出
        assert "Line 1" in results[2].data["stdout"]
        assert "Line 2" in results[2].data["stdout"]
        print("  ✓ 输出验证成功")

        # 并行执行
        commands = [
            {"tool": "bash", "parameters": {"command": "echo 'Parallel 1'"}},
            {"tool": "bash", "parameters": {"command": "echo 'Parallel 2'"}},
            {"tool": "bash", "parameters": {"command": "echo 'Parallel 3'"}},
        ]

        results = await tool_registry.execute_batch(commands, context, parallel=True)

        assert len(results) == 3, f"Should have 3 results, got {len(results)}"
        for i, result in enumerate(results):
            assert result.success, f"Parallel command {i+1} should succeed"
        print(f"  ✓ 并行执行: {len(results)} 个命令全部成功")


async def test_tool_stats():
    """测试工具统计"""
    print("\n=== 测试工具统计 ===")

    context = ToolExecutionContext(
        agent_id="test_agent",
        workspace=".",
    )

    # 执行一些命令生成统计数据
    await tool_registry.execute("bash", {"command": "echo test"}, context)
    await tool_registry.execute("bash", {"command": "pwd"}, context)

    # 获取单个工具统计
    bash_stats = tool_registry.get_stats("bash")
    assert bash_stats is not None, "Bash tool should have stats"
    assert bash_stats["bash"]["total_calls"] >= 2
    print(f"  ✓ Bash工具统计: {bash_stats['bash']}")

    # 获取所有工具统计
    all_stats = tool_registry.get_stats()
    assert len(all_stats) > 0, "Should have stats for at least one tool"
    print(f"  ✓ 所有工具统计: {list(all_stats.keys())}")


async def test_parameter_validation():
    """测试参数验证"""
    print("\n=== 测试参数验证 ===")

    tool = tool_registry.get_tool("file_write")

    # 测试缺少必需参数
    valid, error = await tool.validate_parameters({})
    assert not valid, "Should fail with missing path parameter"
    print("  ✓ 缺少必需参数被拒绝")

    # 测试错误类型
    valid, error = await tool.validate_parameters({"path": 123})
    assert not valid, "Should fail with wrong parameter type"
    print("  ✓ 错误参数类型被拒绝")

    # 测试正确参数
    valid, error = await tool.validate_parameters({
        "path": "/tmp/test.txt",
        "content": "test",
    })
    assert valid, "Valid parameters should pass"
    print("  ✓ 正确参数验证通过")


async def test_tool_info():
    """测试工具信息"""
    print("\n=== 测试工具信息 ===")

    # 获取所有工具信息
    all_tools = tool_registry.get_all_tools_info()
    print(f"  工具总数: {len(all_tools)}")

    for tool_info in all_tools:
        print(f"\n  工具: {tool_info['name']}")
        print(f"    描述: {tool_info['description']}")
        print(f"    类别: {tool_info['category']}")
        print(f"    参数数量: {len(tool_info['parameters'])}")
        print(f"    示例数量: {len(tool_info['examples'])}")
        if "stats" in tool_info:
            print(f"    调用次数: {tool_info['stats']['total_calls']}")

    print("\n  ✓ 所有工具信息获取成功")


async def main():
    """主测试函数"""
    print("=" * 50)
    print("工具注册表和内置工具测试")
    print("=" * 50)

    try:
        await test_tool_registration()
        await test_bash_tool()
        await test_file_operations()
        await test_batch_execution()
        await test_tool_stats()
        await test_parameter_validation()
        await test_tool_info()

        print("\n" + "=" * 50)
        print("✓ 所有工具测试通过!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
