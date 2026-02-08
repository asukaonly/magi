"""
完整框架测试 - 验证所有核心模块协同工作
"""
import asyncio
import sys
import os

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from magi.events.events import Event, EventLevel
from magi.events.memory_backend import MemoryMessageBackend
from magi.llm.anthropic import AnthropicAdapter
from magi.core.agent import Agent, AgentConfig, AgentState
from magi.core.master_agent import MasterAgent
from magi.core.task_agent import TaskAgent
from magi.core.loop import LoopEngine, LoopStrategy
from magi.awareness import (
    PerceptionManager,
    UserMessageSensor,
    EventSensor,
    PerceptionType,
)
from magi.processing import (
    SelfProcessingModule,
    ComplexityEvaluator,
    TaskComplexity,
    ComplexityLevel,
)
from magi.tools.base import Tool, ToolSchema, ToolResult
from magi.tools.registry import ToolRegistry
from magi.memory.store import MemoryStore
from magi.plugins.base import Plugin
from magi.plugins.manager import PluginManager


class SimpleEchoTool(Tool):
    """简单回显工具（测试用）"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="echo",
            description="回显输入内容",
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "要回显的消息"
                    }
                },
                "required": ["message"]
            },
            permissions=[],
            internal=False,
        )

    async def execute(self, params: dict) -> ToolResult:
        """执行回显"""
        message = params.get("message", "")
        return ToolResult(
            success=True,
            data={"echo": message}
        )


class LoggingPlugin(Plugin):
    """日志插件（测试用）"""

    async def before_sense(self, context: dict) -> dict:
        print("[Plugin] before_sense called")
        return context

    async def after_act(self, result: any) -> any:
        print(f"[Plugin] after_act called: {result}")
        return result


async def test_event_system():
    """测试事件系统"""
    print("\n=== 测试事件系统 ===")

    backend = MemoryMessageBackend()
    await backend.start()

    # 订阅事件
    received_events = []

    async def handler(event):
        received_events.append(event)

    await backend.subscribe("test", handler)

    # 发布事件
    event = Event(
        type="test",
        data={"message": "Hello, Magi!"},
        level=EventLevel.INFO,
    )
    await backend.publish(event)

    # 等待处理
    await asyncio.sleep(0.1)

    # 验证
    assert len(received_events) == 1
    assert received_events[0].data["message"] == "Hello, Magi!"

    await backend.stop()
    print("✓ 事件系统测试通过")


async def test_tool_registry():
    """测试工具注册表"""
    print("\n=== 测试工具注册表 ===")

    registry = ToolRegistry()

    # 注册工具
    echo_tool = SimpleEchoTool()
    registry.register(echo_tool)

    # 列出工具
    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "echo"

    # 执行工具
    result = await registry.execute("echo", {"message": "test"})
    assert result.success
    assert result.data["echo"] == "test"

    # 获取统计
    stats = registry.get_stats("echo")
    assert stats["call_count"] == 1
    assert stats["success_count"] == 1

    print("✓ 工具注册表测试通过")


async def test_awareness():
    """测试自感知模块"""
    print("\n=== 测试自感知模块 ===")

    # 创建感知管理器
    manager = PerceptionManager(max_queue_size=50)

    # 注册用户消息传感器
    user_sensor = UserMessageSensor()
    manager.register_sensor("user", user_sensor)

    # 发送消息
    await user_sensor.send_message("Hello, Agent!")

    # 收集感知
    perceptions = await manager.perceive()

    assert len(perceptions) == 1
    assert perceptions[0].data["message"] == "Hello, Agent!"

    # 获取统计
    stats = manager.get_stats()
    assert stats["perceived_count"] == 1
    assert stats["processed_count"] == 1

    print("✓ 自感知模块测试通过")


async def test_processing():
    """测试自处理模块"""
    print("\n=== 测试自处理模块 ===")

    # 创建自处理模块
    processing = SelfProcessingModule()

    # 测试复杂度评估
    task = {
        "type": "simple",
        "description": "测试任务",
        "tools": ["echo"],
        "parameters": {"message": "test"},
    }

    result = await processing.process(task)

    assert result.complexity.level == ComplexityLevel.LOW
    assert not result.needs_human_help

    print("✓ 自处理模块测试通过")


async def test_memory():
    """测试记忆存储"""
    print("\n=== 测试记忆存储 ===")

    memory = MemoryStore(base_path=":memory:")
    await memory.init()

    # 测试自我记忆
    await memory.update_agent_profile({"name": "Magi"})
    profile = await memory.get_agent_profile()
    assert profile["name"] == "Magi"

    # 测试L5能力存储
    from magi.memory.capability_store import CapabilityMemory
    capability = CapabilityMemory(
        trigger_pattern={"type": "test"},
        action={"type": "test_action"},
    )
    await memory.save_capability(capability)

    # 查询能力
    found = await memory.find_capability({"type": "test"})
    assert found is not None

    # MemoryStore没有stop方法
    print("✓ 记忆存储测试通过")


async def test_plugin():
    """测试插件系统"""
    print("\n=== 测试插件系统 ===")

    manager = PluginManager()

    # 加载插件
    plugin_instance = await manager.load_plugin(LoggingPlugin)

    # 执行钩子
    context = {"test": "data"}
    result = await manager.execute_hooks("before_sense", context)
    assert result == context

    await manager.unload_plugin(plugin_instance.name)
    print("✓ 插件系统测试通过")


async def test_agent_lifecycle():
    """测试Agent生命周期"""
    print("\n=== 测试Agent生命周期 ===")

    config = AgentConfig(
        name="test_agent",
        llm_config={"model": "gpt-4"}
    )
    agent = Agent(config)

    # 启动
    await agent.start()
    assert agent.state == AgentState.RUNNING

    # 暂停
    await agent.pause()
    assert agent.state == AgentState.PAUSED

    # 恢复
    await agent.resume()
    assert agent.state == AgentState.RUNNING

    # 停止
    await agent.stop()
    assert agent.state == AgentState.STOPPED

    print("✓ Agent生命周期测试通过")


async def test_timeout_calculator():
    """测试超时计算器"""
    print("\n=== 测试超时计算器 ===")

    from magi.core.timeout import (
        TimeoutCalculator,
        TaskType,
        TaskPriority,
    )

    calculator = TimeoutCalculator()

    # 计算简单任务超时
    timeout = calculator.calculate_timeout(
        task_type=TaskType.SIMPLE,
        priority=TaskPriority.NORMAL,
    )
    assert timeout > 0

    # 高优先级任务应该超时更短
    high_priority_timeout = calculator.calculate_timeout(
        task_type=TaskType.SIMPLE,
        priority=TaskPriority.HIGH,
    )
    assert high_priority_timeout < timeout

    print("✓ 超时计算器测试通过")


async def test_task_database():
    """测试任务数据库"""
    print("\n=== 测试任务数据库 ===")

    from magi.core.task_database import (
        TaskDatabase,
        Task,
        TaskStatus,
        TaskPriority,
    )

    db = TaskDatabase(":memory:")
    await db.start()

    # 创建任务
    task = Task(
        id="task-1",
        type="test",
        data={"message": "test"},
        status=TaskStatus.PENDING,
        priority=TaskPriority.NORMAL,
    )
    await db.create_task(task)

    # 获取任务
    retrieved = await db.get_task("task-1")
    assert retrieved is not None
    assert retrieved.id == "task-1"

    # 更新任务
    retrieved.status = TaskStatus.COMPLETED
    await db.update_task(retrieved)

    updated = await db.get_task("task-1")
    assert updated.status == TaskStatus.COMPLETED

    await db.stop()
    print("✓ 任务数据库测试通过")


async def main():
    """主测试函数"""
    print("=" * 50)
    print("Magi AI Agent Framework - 完整测试")
    print("=" * 50)

    try:
        await test_event_system()
        await test_tool_registry()
        await test_awareness()
        await test_processing()
        await test_memory()
        await test_plugin()
        await test_agent_lifecycle()
        await test_timeout_calculator()
        await test_task_database()

        print("\n" + "=" * 50)
        print("✓ 所有测试通过!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
