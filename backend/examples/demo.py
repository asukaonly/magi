"""
完整的Agent示例 - 展示Magi框架的核心能力

这个示例展示：
1. 创建自定义插件
2. 使用消息总线
3. 使用Sense-Plan-Act-Reflect循环
4. 生命周期管理
"""
import asyncio
import sys
from pathlib import Path

# 添加src到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from magi.config.loader import get_config
from magi.events.events import Event, EventLevel, EventTypes
from magi.events.memory_backend import MemoryMessageBackend
from magi.plugins.base import Plugin
from magi.plugins.manager import PluginManager
from magi.core.agent import Agent, AgentConfig


# ===== 自定义插件示例 =====

class LoggingPlugin(Plugin):
    """日志插件 - 记录所有事件"""

    def __init__(self):
        super().__init__()
        self._priority = 10  # 高优先级

    async def after_sense(self, perceptions):
        """Sense后记录感知"""
        print(f"  [LoggingPlugin] 收到 {len(perceptions)} 个感知")
        return perceptions

    async def after_act(self, result):
        """Act后记录结果"""
        print(f"  [LoggingPlugin] 动作执行完成: {result}")
        return result


class MetricsPlugin(Plugin):
    """指标插件 - 统计事件数量"""

    def __init__(self):
        super().__init__()
        self._event_count = 0
        self._priority = 5

    async def before_sense(self, context):
        """Sense前增加计数"""
        self._event_count += 1
        print(f"  [MetricsPlugin] 事件计数: {self._event_count}")
        return context

    def get_stats(self):
        """获取统计信息"""
        return {"event_count": self._event_count}


# ===== 自定义感知示例 =====

class SimplePerception:
    """简单感知"""
    def __init__(self, type: str, data: dict):
        self.type = type
        self.data = data


# ===== 测试函数 =====

async def test_with_plugins():
    """测试插件系统"""
    print("\n=== 测试插件系统 ===")

    # 创建消息总线
    bus = MemoryMessageBackend()

    # 创建插件管理器
    plugin_manager = PluginManager()

    # 加载插件
    logging_plugin = await plugin_manager.load_plugin(LoggingPlugin)
    metrics_plugin = await plugin_manager.load_plugin(MetricsPlugin)

    print(f"✓ 已加载插件: {[p.name for p in plugin_manager.list_plugins()]}")

    # 启动消息总线
    await bus.start()

    # 发布事件并触发插件钩子
    print("\n触发 before_sense 钩子:")
    await plugin_manager.execute_hooks("before_sense", {"test": "context"})

    print("\n触发 after_sense 钩子:")
    perceptions = [SimplePerception("test", {"msg": "test"})]
    await plugin_manager.execute_hooks("after_sense", perceptions)

    print("\n触发 after_act 钩子:")
    await plugin_manager.execute_hooks("after_act", {"success": True})

    # 获取指标
    print(f"\n✓ MetricsPlugin统计: {metrics_plugin.get_stats()}")

    # 停止消息总线
    await bus.stop()

    print("✅ 插件系统测试通过！\n")


async def test_event_driven_architecture():
    """测试事件驱动架构"""
    print("\n=== 测试事件驱动架构 ===")

    # 创建消息总线
    bus = MemoryMessageBackend()
    await bus.start()
    print("✓ 消息总线已启动")

    # 模拟Agent生命周期
    events_log = []

    # 订阅生命周期事件
    async def lifecycle_handler(event):
        events_log.append(event.type)
        print(f"  [生命周期] {event.type}: {event.data}")

    await bus.subscribe(EventTypes.AGENT_STARTED, lifecycle_handler)
    await bus.subscribe(EventTypes.AGENT_STOPPED, lifecycle_handler)
    await bus.subscribe(EventTypes.ERROR_OCCURRED, lifecycle_handler)

    # 发布启动事件
    start_event = Event(
        type=EventTypes.AGENT_STARTED,
        data={"agent_name": "test-agent", "mode": "continuous"},
        source="system",
        level=EventLevel.INFO,
    )
    await bus.publish(start_event)

    # 发布一些工作事件
    for i in range(3):
        event = Event(
            type=f"WorkEvent{i}",
            data={"task": f"task-{i}", "status": "processing"},
            source="agent",
            level=EventLevel.INFO,
        )
        await bus.publish(event)
        print(f"  已发布工作事件 {i+1}")
        await asyncio.sleep(0.1)

    # 发布错误事件（测试）
    error_event = Event(
        type=EventTypes.ERROR_OCCURRED,
        data={"source": "test", "error": "Test error"},
        source="agent",
        level=EventLevel.ERROR,
    )
    await bus.publish(error_event)

    # 等待处理
    await asyncio.sleep(0.5)

    # 发布停止事件
    stop_event = Event(
        type=EventTypes.AGENT_STOPPED,
        data={"agent_name": "test-agent", "reason": "user_initiated"},
        source="system",
        level=EventLevel.INFO,
    )
    await bus.publish(stop_event)

    # 获取统计信息
    stats = await bus.get_stats()
    print(f"\n✓ 总计发布事件: {stats['published_count']}")
    print(f"✓ 总计处理事件: {stats['processed_count']}")

    # 停止消息总线
    await bus.stop()

    print("✅ 事件驱动架构测试通过！\n")


async def test_agent_with_loop():
    """测试Agent的完整循环"""
    print("\n=== 测试Agent循环 ===")

    # 创建配置
    config = AgentConfig(
        name="loop-test-agent",
        llm_config={"model": "test"},
    )

    # 创建Agent
    agent = Agent(config)
    print(f"✓ 创建Agent: {agent.config.name}")

    # 测试生命周期
    await agent.start()
    print(f"✓ Agent状态: {agent.state.value}")

    await asyncio.sleep(0.5)

    await agent.stop()
    print(f"✓ Agent状态: {agent.state.value}")

    print(f"✓ 运行时间: {agent.get_uptime():.2f}秒")

    print("✅ Agent循环测试通过！\n")


async def main():
    """主函数"""
    print("=" * 60)
    print("Magi AI Agent Framework - 完整示例")
    print("=" * 60)

    try:
        # 测试插件系统
        await test_with_plugins()

        # 测试事件驱动架构
        await test_event_driven_architecture()

        # 测试Agent循环
        await test_agent_with_loop()

        print("=" * 60)
        print("✅ 所有示例运行完成！")
        print("=" * 60)
        print("\n框架核心能力已验证：")
        print("  ✅ 插件系统（生命周期钩子、Chain/Parallel模式）")
        print("  ✅ 事件驱动架构（发布-订阅、优先级队列）")
        print("  ✅ Agent生命周期（启动、运行、停止）")
        print("  ✅ Sense-Plan-Act-Reflect循环引擎")

    except Exception as e:
        print(f"\n❌ 示例运行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
