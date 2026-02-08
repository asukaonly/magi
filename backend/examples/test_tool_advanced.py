"""
工具高级功能测试

测试工具推荐引擎、执行计划器、版本管理等功能
"""
import asyncio
import sys
import os
import tempfile

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from magi.tools import (
    tool_registry,
    ToolRecommender,
    ScenarioType,
    ExecutionPlanner,
    ExecutionPlan,
    ToolVersionManager,
    ToolExecutionContext,
)


async def test_permission_control():
    """测试权限控制"""
    print("\n=== 测试权限控制 ===")

    # 测试无权限执行危险工具
    context = ToolExecutionContext(
        agent_id="test_agent",
        task_id="test_task",
        workspace=".",
        permissions=[],  # 没有危险工具权限
    )

    result = await tool_registry.execute(
        "bash",
        {"command": "echo test"},
        context
    )

    assert not result.success, "Should fail without dangerous_tools permission"
    assert result.error_code == "PERMISSION_DENIED"
    print("  ✓ 危险工具权限检查成功")

    # 测试有权限执行
    context_full = ToolExecutionContext(
        agent_id="test_agent",
        task_id="test_task",
        workspace=".",
        permissions=["dangerous_tools"],
    )

    result = await tool_registry.execute(
        "bash",
        {"command": "echo test"},
        context_full
    )

    assert result.success, f"Should succeed with permission: {result.error}"
    print("  ✓ 有权限执行成功")


async def test_tool_recommender():
    """测试工具推荐引擎"""
    print("\n=== 测试工具推荐引擎 ===")

    recommender = ToolRecommender(tool_registry)

    context = ToolExecutionContext(
        agent_id="test_agent",
        task_id="test_task",
        workspace=".",
        permissions=["dangerous_tools"],
    )

    # 测试场景分类
    scenario = recommender.classify_scenario("我需要读取文件内容")
    assert scenario == ScenarioType.FILE_OPERATION
    print(f"  ✓ 场景分类: {scenario}")

    scenario = recommender.classify_scenario("执行bash命令查看系统状态")
    assert scenario == ScenarioType.SYSTEM_COMMAND
    print(f"  ✓ 场景分类: {scenario}")

    # 测试工具推荐
    recommendations = recommender.recommend_tools(
        "我需要读取文件test.txt",
        context,
        top_k=3
    )

    assert len(recommendations) > 0, "Should have recommendations"
    assert recommendations[0]["tool"] == "file_read"
    print(f"  ✓ 推荐工具: {[r['tool'] for r in recommendations]}")

    # 测试参数建议
    params = recommender.suggest_parameters(
        "file_read",
        "读取文件test.txt的内容",
        context
    )

    assert "path" in params
    print(f"  ✓ 参数建议: {params}")


async def test_execution_planner():
    """测试执行计划器"""
    print("\n=== 测试执行计划器 ===")

    planner = ExecutionPlanner(tool_registry)

    with tempfile.TemporaryDirectory() as tmpdir:
        context = ToolExecutionContext(
            agent_id="test_agent",
            task_id="test_task",
            workspace=tmpdir,
            permissions=["dangerous_tools"],
        )

        # 创建执行计划（DAG）
        tasks = [
            {
                "id": "task1",
                "tool": "bash",
                "parameters": {"command": f"echo 'Hello' > {os.path.join(tmpdir, 'test.txt')}"},
            },
            {
                "id": "task2",
                "tool": "bash",
                "parameters": {"command": f"echo 'World' >> {os.path.join(tmpdir, 'test.txt')}"},
                "depends_on": ["task1"],
            },
            {
                "id": "task3",
                "tool": "file_read",
                "parameters": {"path": os.path.join(tmpdir, "test.txt")},
                "depends_on": ["task2"],
            },
        ]

        plan = planner.create_plan("test_plan", tasks)

        # 验证计划
        is_valid, error = planner.validate_plan(plan)
        assert is_valid, f"Plan should be valid: {error}"
        print("  ✓ 计划验证成功")

        # 可视化计划
        print(f"\n  计划结构:\n{plan.visualize()}")

        # 执行计划（串行）
        results = await planner.execute_plan(
            plan,
            context,
            parallel=False,
            stop_on_failure=True
        )

        assert len(results) == 3
        assert results["task1"].success
        assert results["task2"].success
        assert results["task3"].success
        assert "Hello" in results["task3"].data["content"]
        assert "World" in results["task3"].data["content"]
        print("  ✓ 串行执行成功")

    # 测试并行执行
    with tempfile.TemporaryDirectory() as tmpdir:
        context = ToolExecutionContext(
            agent_id="test_agent",
            task_id="test_task",
            workspace=tmpdir,
            permissions=["dangerous_tools"],
        )

        # 创建并行任务（无依赖）
        tasks = [
            {
                "id": "parallel1",
                "tool": "bash",
                "parameters": {"command": f"echo 'Task1' > {os.path.join(tmpdir, 't1.txt')}"},
            },
            {
                "id": "parallel2",
                "tool": "bash",
                "parameters": {"command": f"echo 'Task2' > {os.path.join(tmpdir, 't2.txt')}"},
            },
            {
                "id": "parallel3",
                "tool": "bash",
                "parameters": {"command": f"echo 'Task3' > {os.path.join(tmpdir, 't3.txt')}"},
            },
        ]

        plan = planner.create_plan("parallel_plan", tasks)

        # 并行执行
        results = await planner.execute_plan(
            plan,
            context,
            parallel=True,
            stop_on_failure=True
        )

        assert len(results) == 3
        assert all(r.success for r in results.values())
        print("  ✓ 并行执行成功")


async def test_version_manager():
    """测试版本管理"""
    print("\n=== 测试版本管理 ===")

    manager = ToolVersionManager()

    # 注册版本
    from magi.tools.builtin import BashTool

    manager.register_version("bash", "1.0.0", BashTool, is_active=True)
    manager.register_version("bash", "1.1.0", BashTool, is_active=True)
    manager.register_version("bash", "2.0.0", BashTool, breaking_changes=["Removed old parameter"])

    # 获取活跃版本
    active = manager.get_active_version("bash")
    assert active == "2.0.0"
    print(f"  ✓ 活跃版本: {active}")

    # 列出版本
    versions = manager.list_versions("bash")
    assert len(versions) == 3
    print(f"  ✓ 可用版本: {[v.version for v in versions]}")

    # 弃用版本
    success = manager.deprecate_version("bash", "1.0.0", "Please upgrade to 2.0.0")
    assert success
    print("  ✓ 版本弃用成功")

    # 检查弃用状态
    is_deprecated = manager.is_deprecated("bash", "1.0.0")
    assert is_deprecated
    print("  ✓ 弃用状态检查成功")

    # 版本兼容性检查
    compatibility = manager.check_compatibility("bash", "1.5.0")
    assert compatibility.compatible
    print(f"  ✓ 兼容性检查: {compatibility.compatible}")

    # 获取破坏性变更
    breaking = manager.get_breaking_changes("bash", "1.0.0")
    assert len(breaking) > 0
    print(f"  ✓ 破坏性变更: {breaking}")

    # 版本信息
    info = manager.get_version_info("bash")
    assert info["total_versions"] == 3
    assert info["has_deprecated"]
    print(f"  ✓ 版本信息: {info}")


async def test_dag_validation():
    """测试DAG循环依赖检测"""
    print("\n=== 测试DAG循环依赖检测 ===")

    planner = ExecutionPlanner(tool_registry)

    # 创建有循环依赖的计划
    tasks = [
        {
            "id": "task1",
            "tool": "bash",
            "parameters": {"command": "echo test"},
            "depends_on": ["task3"],  # 循环：task1 -> task2 -> task3 -> task1
        },
        {
            "id": "task2",
            "tool": "bash",
            "parameters": {"command": "echo test"},
            "depends_on": ["task1"],
        },
        {
            "id": "task3",
            "tool": "bash",
            "parameters": {"command": "echo test"},
            "depends_on": ["task2"],
        },
    ]

    plan = planner.create_plan("circular_plan", tasks)

    # 验证应该失败
    is_valid, error = planner.validate_plan(plan)
    assert not is_valid, "Should detect circular dependency"
    assert "Circular dependency" in error
    print(f"  ✓ 循环依赖检测成功: {error}")


async def test_parameter_substitution():
    """测试参数替换"""
    print("\n=== 测试参数替换 ===")

    planner = ExecutionPlanner(tool_registry)

    with tempfile.TemporaryDirectory() as tmpdir:
        context = ToolExecutionContext(
            agent_id="test_agent",
            task_id="test_task",
            workspace=tmpdir,
            permissions=["dangerous_tools"],
        )

        # 创建使用参数替换的计划
        file_path = os.path.join(tmpdir, "output.txt")

        tasks = [
            {
                "id": "write",
                "tool": "bash",
                "parameters": {"command": f"echo 'Hello World' > {file_path}"},
            },
            {
                "id": "read",
                "tool": "file_read",
                "parameters": {
                    "path": file_path,
                    # 注意：实际使用时可以通过 ${write.data.stdout} 等引用
                },
                "depends_on": ["write"],
            },
        ]

        plan = planner.create_plan("substitution_plan", tasks)
        results = await planner.execute_plan(plan, context, parallel=False)

        assert results["write"].success
        assert results["read"].success
        print("  ✓ 参数替换执行成功")


async def main():
    """主测试函数"""
    print("=" * 50)
    print("工具高级功能测试")
    print("=" * 50)

    try:
        await test_permission_control()
        await test_tool_recommender()
        await test_execution_planner()
        await test_version_manager()
        await test_dag_validation()
        await test_parameter_substitution()

        print("\n" + "=" * 50)
        print("✓ 所有高级功能测试通过!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
