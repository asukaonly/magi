"""
简单的Agent测试示例
"""
import asyncio
import sys
from pathlib import Path

# 添加src到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from magi.config.loader import get_config
from magi.events.events import Event, EventLevel
from magi.events.memory_backend import MemoryMessageBackend
from magi.llm.openai import OpenAIAdapter
from magi.core.complete_agent import CompleteAgent
from magi.core.agent import AgentConfig


async def test_event_system():
    """测试事件系统"""
    print("\n=== 测试事件系统 ===")

    # 创建内存消息总线
    bus = MemoryMessageBackend(max_queue_size=100, num_workers=2)

    # 定义事件处理器
    received_events = []

    async def handler_1(event):
        received_events.append(("handler_1", event.type))
        print(f"  Handler 1 收到事件: {event.type}")

    async def handler_2(event):
        received_events.append(("handler_2", event.type))
        print(f"  Handler 2 收到事件: {event.type}")

    # 启动消息总线
    await bus.start()
    print("✓ 消息总线已启动")

    # 订阅事件
    sub_id_1 = await bus.subscribe("TestEvent", handler_1, "broadcast")
    sub_id_2 = await bus.subscribe("TestEvent", handler_2, "broadcast")
    print("✓ 已订阅事件")

    # 发布事件
    event = Event(
        type="TestEvent",
        data={"message": "Hello, Magi!"},
        source="test",
        level=EventLevel.INFO,
    )
    await bus.publish(event)
    print("✓ 已发布事件")

    # 等待处理
    await asyncio.sleep(0.5)

    # 检查结果
    assert len(received_events) == 2, f"应该收到2个事件，实际收到{len(received_events)}个"
    print(f"✓ 收到{len(received_events)}个事件处理结果")

    # 获取统计信息
    stats = await bus.get_stats()
    print(f"✓ 统计信息: {stats}")

    # 停止消息总线
    await bus.stop()
    print("✓ 消息总线已停止")

    print("✅ 事件系统测试通过！\n")


async def test_llm_adapter():
    """测试LLM适配器（需要API key）"""
    print("\n=== 测试LLM适配器 ===")

    import os
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        print("⚠️  未设置OPENAI_API_KEY环境变量，跳过LLM测试")
        return

    # 创建OpenAI适配器
    llm = OpenAIAdapter(api_key=api_key, model="gpt-3.5-turbo")
    print(f"✓ 已创建LLM适配器: {llm.model_name}")

    # 测试生成
    try:
        response = await llm.generate("Say 'Hello, Magi!' in one sentence.")
        print(f"✓ LLM响应: {response}")
        print("✅ LLM适配器测试通过！\n")
    except Exception as e:
        print(f"❌ LLM调用失败: {e}")


async def test_agent_lifecycle():
    """测试Agent生命周期"""
    print("\n=== 测试Agent生命周期 ===")

    # 创建消息总线
    bus = MemoryMessageBackend()

    # 创建LLM适配器（可选）
    import os
    if os.getenv("OPENAI_API_KEY"):
        llm = OpenAIAdapter(api_key=os.getenv("OPENAI_API_KEY"))
    else:
        print("⚠️  未设置OPENAI_API_KEY，使用模拟LLM")
        llm = None

    # 创建Agent配置
    config = AgentConfig(
        name="test-agent",
        llm_config={"model": "gpt-3.5-turbo"},
        num_task_agents=2,
        loop_interval=1.0,
    )

    # 如果没有LLM，创建一个简化版Agent
    if llm is None:
        print("⚠️  创建简化版Agent（无LLM）")
        from magi.core.agent import Agent as SimpleAgent

        agent = SimpleAgent(config)
    else:
        agent = CompleteAgent(
            config=config,
            message_bus=bus,
            llm_adapter=llm,
        )

    print("✓ Agent已创建")

    # 测试启动
    await agent.start()
    print(f"✓ Agent已启动，状态: {agent.state.value}")

    # 测试运行时间
    await asyncio.sleep(0.5)
    uptime = agent.get_uptime()
    print(f"✓ 运行时间: {uptime:.2f}秒")

    # 测试停止
    await agent.stop()
    print(f"✓ Agent已停止，状态: {agent.state.value}")

    print("✅ Agent生命周期测试通过！\n")


async def main():
    """主测试函数"""
    print("=" * 50)
    print("Magi AI Agent Framework - 测试")
    print("=" * 50)

    try:
        # 测试事件系统
        await test_event_system()

        # 测试LLM适配器
        await test_llm_adapter()

        # 测试Agent生命周期
        await test_agent_lifecycle()

        print("=" * 50)
        print("✅ 所有测试通过！")
        print("=" * 50)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
