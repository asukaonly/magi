#!/usr/bin/env python3
"""
快速测试脚本 - 验证后台核心功能
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import asyncio
from magi.tools import (
    tool_registry,
    ToolRecommender,
    ExecutionPlanner,
    ToolVersionManager,
    ToolExecutionContext,
)


def print_header(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


async def test_basic_tools():
    """测试基础工具功能"""
    print_header("1. 测试基础工具")

    # 列出所有工具
    tools = tool_registry.list_tools()
    print(f"✓ 已注册工具: {tools}")

    # 获取工具信息
    for tool_name in tools[:3]:
        info = tool_registry.get_tool_info(tool_name)
        print(f"  - {tool_name}")
        print(f"    描述: {info['description']}")
        print(f"    类别: {info['category']}")
        print(f"    参数: {len(info['parameters'])} 个")

    return True


async def test_tool_execution():
    """测试工具执行"""
    print_header("2. 测试工具执行")

    context = ToolExecutionContext(
        agent_id="test_agent",
        workspace=".",
        permissions=["dangerous_tools"],
    )

    # 执行bash命令
    result = await tool_registry.execute(
        "bash",
        {"command": "echo 'Hello from Magi!'"},
        context
    )

    if result.success:
        print(f"✓ 命令执行成功")
        print(f"  输出: {result.data['stdout'].strip()}")
        return True
    else:
        print(f"✗ 命令执行失败: {result.error}")
        return False


async def test_tool_recommendation():
    """测试工具推荐"""
    print_header("3. 测试工具推荐")

    recommender = ToolRecommender(tool_registry)

    context = ToolExecutionContext(
        agent_id="test_agent",
        workspace=".",
        permissions=["dangerous_tools"],
    )

    # 测试不同的意图
    test_intents = [
        "我需要读取文件内容",
        "执行bash命令",
        "查看目录下所有文件",
    ]

    for intent in test_intents:
        print(f"\n意图: {intent}")
        recommendations = recommender.recommend_tools(intent, context, top_k=2)
        if recommendations:
            print(f"  推荐工具:")
            for rec in recommendations:
                print(f"    - {rec['tool']} (分数: {rec['score']:.2f})")
                print(f"      理由: {rec['reason']}")
        else:
            print(f"  没有找到合适的工具")

    return True


async def test_execution_planner():
    """测试执行计划器"""
    print_header("4. 测试执行计划器")

    planner = ExecutionPlanner(tool_registry)

    context = ToolExecutionContext(
        agent_id="test_agent",
        workspace=".",
        permissions=["dangerous_tools"],
    )

    # 创建简单的执行计划
    tasks = [
        {
            "id": "task1",
            "tool": "bash",
            "parameters": {"command": "echo 'Task 1'"},
        },
        {
            "id": "task2",
            "tool": "bash",
            "parameters": {"command": "echo 'Task 2'"},
            "depends_on": ["task1"],
        },
    ]

    plan = planner.create_plan("test_plan", tasks)

    # 验证计划
    is_valid, error = planner.validate_plan(plan)
    if is_valid:
        print(f"✓ 计划验证通过")
        print(f"  包含 {len(plan.nodes)} 个任务")
        print(f"  执行顺序:")
        for level_idx, level in enumerate(plan.get_execution_order()):
            print(f"    层级 {level_idx + 1}: {level}")
    else:
        print(f"✗ 计划验证失败: {error}")
        return False

    # 执行计划
    print(f"\n执行计划...")
    results = await planner.execute_plan(plan, context, parallel=False)

    success_count = sum(1 for r in results.values() if r.success)
    print(f"✓ 执行完成: {success_count}/{len(results)} 成功")

    return True


async def test_version_manager():
    """测试版本管理"""
    print_header("5. 测试版本管理")

    manager = ToolVersionManager()

    from magi.tools.builtin import BashTool

    # 注册多个版本
    manager.register_version("bash", "1.0.0", BashTool)
    manager.register_version("bash", "2.0.0", BashTool, is_active=True)

    # 获取版本信息
    active = manager.get_active_version("bash")
    print(f"✓ 活跃版本: {active}")

    versions = manager.list_versions("bash")
    print(f"✓ 可用版本: {[v.version for v in versions]}")

    info = manager.get_version_info("bash")
    print(f"✓ 版本统计: {info['total_versions']} 个版本")

    return True


async def test_permission_control():
    """测试权限控制"""
    print_header("6. 测试权限控制")

    # 无权限测试
    context_no_permission = ToolExecutionContext(
        agent_id="test_agent",
        workspace=".",
        permissions=[],  # 没有权限
    )

    result = await tool_registry.execute(
        "bash",
        {"command": "echo test"},
        context_no_permission
    )

    if not result.success and result.error_code == "PERMISSION_DENIED":
        print(f"✓ 权限检查生效: 危险工具被正确阻止")
    else:
        print(f"✗ 权限检查未生效")
        return False

    # 有权限测试
    context_with_permission = ToolExecutionContext(
        agent_id="test_agent",
        workspace=".",
        permissions=["dangerous_tools"],
    )

    result = await tool_registry.execute(
        "bash",
        {"command": "echo test"},
        context_with_permission
    )

    if result.success:
        print(f"✓ 有权限时执行成功")
    else:
        print(f"✗ 执行失败: {result.error}")
        return False

    return True


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("  Magi AI Agent Framework - 快速功能测试")
    print("=" * 60)

    tests = [
        ("基础工具", test_basic_tools),
        ("工具执行", test_tool_execution),
        ("工具推荐", test_tool_recommendation),
        ("执行计划", test_execution_planner),
        ("版本管理", test_version_manager),
        ("权限控制", test_permission_control),
    ]

    results = []

    for name, test_func in tests:
        try:
            success = await test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n✗ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 总结
    print_header("测试总结")
    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"  {name}: {status}")

    print("\n" + "=" * 60)
    print(f"  总计: {passed}/{total} 测试通过")
    print("=" * 60)

    if passed == total:
        print("\n🎉 所有测试通过！后台功能正常！\n")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，请检查\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
