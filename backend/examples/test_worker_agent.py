"""
WorkerAgent测试

测试WorkerAgent的：
- 任务执行
- 超时控制
- 重试机制
- 回调调用
- 轻量级特性
"""
import asyncio
import sys
import os

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from magi.core.worker_agent import WorkerAgent, WorkerAgentConfig
from magi.core.task_database import Task, TaskStatus, TaskPriority
from magi.tools.registry import ToolRegistry
from magi.tools.base import Tool, ToolSchema, ToolResult


class SlowTool(Tool):
    """慢速工具（用于测试超时）"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="slow_tool",
            description="执行慢速操作",
            parameters={
                "type": "object",
                "properties": {
                    "duration": {
                        "type": "number",
                        "description": "执行时长（秒）"
                    }
                },
                "required": ["duration"]
            },
            permissions=[],
            internal=False,
        )

    async def execute(self, params: dict) -> ToolResult:
        """执行慢速操作"""
        duration = params.get("duration", 1.0)
        await asyncio.sleep(duration)
        return ToolResult(
            success=True,
            data={"slept": duration}
        )


class FailingTool(Tool):
    """会失败的工具（用于测试重试）"""

    def __init__(self):
        super().__init__()
        self.call_count = 0

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="failing_tool",
            description="执行会失败的操作",
            parameters={
                "type": "object",
                "properties": {},
            },
            permissions=[],
            internal=False,
        )

    async def execute(self, params: dict) -> ToolResult:
        """执行操作，前两次失败，第三次成功"""
        self.call_count += 1

        if self.call_count < 3:
            return ToolResult(
                success=False,
                error=f"Attempt {self.call_count} failed"
            )
        else:
            return ToolResult(
                success=True,
                data={"attempt": self.call_count}
            )


class FastTool(Tool):
    """快速工具"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="fast_tool",
            description="快速工具",
            parameters={"type": "object", "properties": {}},
            permissions=[],
            internal=False,
        )

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(
            success=True,
            data={"result": "done"}
        )


async def test_worker_agent_basic_execution():
    """测试WorkerAgent基本执行"""
    print("\n=== 测试WorkerAgent基本执行 ===")

    # 创建工具注册表
    registry = ToolRegistry()
    fast_tool = FastTool()
    registry.register(fast_tool)

    # 创建任务
    task = Task(
        id="task-1",
        type="tool_execution",
        data={
            "tool_name": "fast_tool",
            "parameters": {},
        },
        status=TaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
    )

    # 创建回调
    completed = False
    result_data = None

    async def on_complete(task, result):
        nonlocal completed, result_data
        completed = True
        result_data = result
        print(f"[Callback] Task completed: {result}")

    # 创建WorkerAgent
    config = WorkerAgentConfig(
        name="worker-1",
        llm_config={"model": "gpt-4"},
        task=task,
        tool_registry=registry,
        on_complete=on_complete,
    )

    agent = WorkerAgent(config)

    # 启动Agent
    await agent.start()

    # 等待完成
    success = await agent.wait_for_completion(timeout=5.0)

    assert success, "Task should complete successfully"
    assert completed, "Completion callback should be called"
    assert result_data == {"result": "done"}
    assert task.status == TaskStatus.COMPLETED

    # 获取结果
    result = agent.get_result()
    assert result == {"result": "done"}

    # 获取指标
    metrics = agent.get_metrics()
    assert metrics["tasks_completed"] == 1
    assert metrics["success_count"] == 1

    print("✓ WorkerAgent基本执行测试通过")


async def test_worker_agent_timeout():
    """测试WorkerAgent超时控制"""
    print("\n=== 测试WorkerAgent超时控制 ===")

    # 创建工具注册表
    registry = ToolRegistry()
    slow_tool = SlowTool()
    registry.register(slow_tool)

    # 创建任务
    task = Task(
        id="task-2",
        type="tool_execution",
        data={
            "tool_name": "slow_tool",
            "parameters": {"duration": 5.0},  # 5秒
        },
        status=TaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
    )

    # 创建WorkerAgent，设置2秒超时
    config = WorkerAgentConfig(
        name="worker-2",
        llm_config={"model": "gpt-4"},
        task=task,
        tool_registry=registry,
        timeout=2.0,  # 2秒超时
        max_retries=0,  # 不重试
    )

    agent = WorkerAgent(config)

    # 启动Agent
    await agent.start()

    # 等待完成（应该超时失败）
    success = await agent.wait_for_completion(timeout=10.0)

    assert not success, "Task should fail due to timeout"
    assert task.status == TaskStatus.FAILED
    assert agent.get_error() is not None

    print(f"✓ WorkerAgent超时控制测试通过 (error: {agent.get_error()})")


async def test_worker_agent_retry():
    """测试WorkerAgent重试机制"""
    print("\n=== 测试WorkerAgent重试机制 ===")

    # 创建工具注册表
    registry = ToolRegistry()
    failing_tool = FailingTool()
    registry.register(failing_tool)

    # 创建任务
    task = Task(
        id="task-3",
        type="tool_execution",
        data={
            "tool_name": "failing_tool",
            "parameters": {},
        },
        status=TaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
    )

    # 创建WorkerAgent，允许重试
    config = WorkerAgentConfig(
        name="worker-3",
        llm_config={"model": "gpt-4"},
        task=task,
        tool_registry=registry,
        max_retries=3,  # 最多重试3次
        timeout=10.0,
    )

    agent = WorkerAgent(config)

    # 启动Agent
    await agent.start()

    # 等待完成
    success = await agent.wait_for_completion(timeout=15.0)

    assert success, "Task should complete after retries"
    assert task.status == TaskStatus.COMPLETED
    assert failing_tool.call_count == 3  # 第3次成功

    result = agent.get_result()
    assert result["attempt"] == 3

    print(f"✓ WorkerAgent重试机制测试通过 (成功在第{failing_tool.call_count}次尝试)")


async def test_worker_agent_lightweight():
    """测试WorkerAgent轻量级特性"""
    print("\n=== 测试WorkerAgent轻量级特性 ===")

    # 创建多个WorkerAgent
    agents = []

    for i in range(10):
        task = Task(
            id=f"task-{i}",
            type="custom",
            data={"index": i},
            status=TaskStatus.PENDING,
            priority=TaskPriority.NORMAL,
        )

        config = WorkerAgentConfig(
            name=f"worker-{i}",
            llm_config={"model": "gpt-4"},
            task=task,
        )

        agent = WorkerAgent(config)
        agents.append(agent)

    # 同时启动所有Agent
    start_time = asyncio.get_event_loop().time()

    for agent in agents:
        asyncio.create_task(agent.start())

    # 等待所有Agent完成
    for agent in agents:
        await agent.wait_for_completion(timeout=5.0)

    duration = asyncio.get_event_loop().time() - start_time

    assert duration < 2.0, "Should complete quickly in parallel"

    print(f"✓ WorkerAgent轻量级特性测试通过 (10个Agent在{duration:.2f}秒内完成)")


class SimpleTool(Tool):
    """简单工具"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="simple_tool",
            description="简单工具",
            parameters={"type": "object", "properties": {}},
            permissions=[],
            internal=False,
        )

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(
            success=True,
            data={"done": True}
        )


async def test_worker_agent_metrics():
    """测试WorkerAgent指标收集"""
    print("\n=== 测试WorkerAgent指标收集 ===")

    # 创建工具注册表
    registry = ToolRegistry()
    simple_tool = SimpleTool()
    registry.register(simple_tool)

    # 创建任务
    task = Task(
        id="task-metrics",
        type="tool_execution",
        data={
            "tool_name": "simple_tool",
            "parameters": {},
        },
        status=TaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
    )

    # 创建WorkerAgent
    config = WorkerAgentConfig(
        name="worker-metrics",
        llm_config={"model": "gpt-4"},
        task=task,
        tool_registry=registry,
    )

    agent = WorkerAgent(config)

    # 启动Agent
    await agent.start()
    await agent.wait_for_completion(timeout=5.0)

    # 获取指标
    metrics = agent.get_metrics()

    assert metrics["agent_id"] == "worker-metrics"
    assert metrics["tasks_completed"] == 1
    assert metrics["success_count"] == 1
    assert metrics["error_count"] == 0
    assert metrics["success_rate"] == 1.0
    assert metrics["uptime"] > 0

    print(f"✓ WorkerAgent指标收集测试通过")
    print(f"  指标: {metrics}")


async def main():
    """主测试函数"""
    print("=" * 50)
    print("WorkerAgent测试")
    print("=" * 50)

    try:
        await test_worker_agent_basic_execution()
        await test_worker_agent_timeout()
        await test_worker_agent_retry()
        await test_worker_agent_lightweight()
        await test_worker_agent_metrics()

        print("\n" + "=" * 50)
        print("✓ 所有WorkerAgent测试通过!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
