"""
负载均衡机制测试

测试Master Agent的TaskAgent负载均衡分发
"""
import asyncio
import sys
import os
from unittest.mock import MagicMock

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from magi.core.master_agent import MasterAgent
from magi.core.task_agent import TaskAgent
from magi.core.agent import AgentConfig, AgentState
from magi.events.memory_backend import MemoryMessageBackend


async def test_load_balancing():
    """测试负载均衡机制"""
    print("\n=== 测试负载均衡机制 ===")

    # 创建消息总线
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    # 创建Mock LLM适配器
    llm_adapter = MagicMock()

    # 创建3个TaskAgent（不启动，由MasterAgent启动）
    task_agents = []
    for i in range(3):
        config = AgentConfig(
            name=f"task-agent-{i}",
            llm_config={"model": "gpt-4"},
        )
        task_agent = TaskAgent(
            agent_id=i,
            config=config,
            message_bus=message_bus,
            llm_adapter=llm_adapter,
        )
        task_agents.append(task_agent)

    # 创建Master Agent
    master_config = AgentConfig(
        name="master-agent",
        llm_config={"model": "gpt-4"},
    )
    master_agent = MasterAgent(
        config=master_config,
        message_bus=message_bus,
        task_agents=task_agents,
    )
    await master_agent.start()

    # 模拟不同的pending数量
    task_agents[0]._pending_count = 5
    task_agents[1]._pending_count = 2
    task_agents[2]._pending_count = 8

    print(f"  初始负载: {master_agent.get_task_agents_load()}")

    # 测试选择：应该选择agent1（pending=2，最少）
    selected = master_agent._select_task_agent_by_load()
    assert selected.agent_id == 1, f"Should select agent 1, got {selected.agent_id}"
    print(f"  ✓ 选择负载最低的Agent: TaskAgent-{selected.agent_id} (pending={selected.get_pending_count()})")

    # 测试分发任务（会增加pending）
    task = {"task_id": "test-001", "type": "test", "data": {}}
    success = await master_agent.dispatch_task(task)
    assert success, "Task dispatch should succeed"
    print(f"  ✓ 任务分发成功")

    # 验证pending增加
    load_after = master_agent.get_task_agents_load()
    print(f"  分发后负载: {load_after}")
    assert load_after[1] == 3, f"Agent 1 pending should be 3, got {load_after[1]}"

    # 继续分发多个任务，验证负载均衡
    print("\n  测试连续分发任务...")
    for i in range(6):
        task = {"task_id": f"test-{i:03d}", "type": "test", "data": {}}
        await master_agent.dispatch_task(task)

    final_load = master_agent.get_task_agents_load()
    print(f"  最终负载: {final_load}")

    # 验证负载相对均衡
    max_pending = max(final_load.values())
    min_pending = min(final_load.values())
    diff = max_pending - min_pending

    print(f"  负载差: {diff} (max={max_pending}, min={min_pending})")
    assert diff <= 2, f"Load difference should be <= 2, got {diff}"

    # 停止
    await master_agent.stop()

    await message_bus.stop()
    print("✓ 负载均衡机制测试通过")


async def test_select_from_running_agents():
    """测试只从运行的Agent中选择"""
    print("\n=== 测试只选择运行中的Agent ===")

    # 创建消息总线
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    # 创建Mock LLM适配器
    llm_adapter = MagicMock()

    # 创建3个TaskAgent（不启动）
    task_agents = []
    for i in range(3):
        config = AgentConfig(
            name=f"task-agent-{i}",
            llm_config={"model": "gpt-4"},
        )
        task_agent = TaskAgent(
            agent_id=i,
            config=config,
            message_bus=message_bus,
            llm_adapter=llm_adapter,
        )
        task_agents.append(task_agent)

    # 只启动agent 0和2（手动设置状态为RUNNING）
    task_agents[0].state = AgentState.RUNNING
    task_agents[2].state = AgentState.RUNNING

    # 创建Master Agent（不启动，避免冲突）
    master_config = AgentConfig(
        name="master-agent",
        llm_config={"model": "gpt-4"},
    )
    master_agent = MasterAgent(
        config=master_config,
        message_bus=message_bus,
        task_agents=task_agents,
    )

    # 设置不同的pending
    task_agents[0]._pending_count = 10
    task_agents[2]._pending_count = 5

    load = master_agent.get_task_agents_load()
    print(f"  运行中Agent的负载: {load}")

    # 应该选择agent2（运行中且pending最少）
    selected = master_agent._select_task_agent_by_load()
    assert selected is not None, "Should select an agent"
    assert selected.agent_id == 2, f"Should select agent 2, got {selected.agent_id}"
    print(f"  ✓ 正确选择运行中的Agent: TaskAgent-{selected.agent_id}")

    # 清理
    task_agents[0].state = AgentState.STOPPED
    task_agents[2].state = AgentState.STOPPED
    await message_bus.stop()
    print("✓ 运行中Agent选择测试通过")


async def test_no_available_agents():
    """测试没有可用Agent的情况"""
    print("\n=== 测试没有可用Agent ===")

    # 创建消息总线
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    # 创建Master Agent（没有TaskAgent）
    master_config = AgentConfig(
        name="master-agent",
        llm_config={"model": "gpt-4"},
    )
    master_agent = MasterAgent(
        config=master_config,
        message_bus=message_bus,
        task_agents=[],
    )

    # 选择Agent（应该返回None）
    selected = master_agent._select_task_agent_by_load()
    assert selected is None, "Should return None when no agents available"
    print(f"  ✓ 没有Agent时返回None")

    # 分发任务（应该失败）
    task = {"task_id": "test-001", "type": "test", "data": {}}
    success = await master_agent.dispatch_task(task)
    assert not success, "Task dispatch should fail when no agents available"
    print(f"  ✓ 分发任务正确失败")

    await message_bus.stop()
    print("✓ 没有可用Agent测试通过")


async def test_dispatch_error_handling():
    """测试分发过程中的错误处理"""
    print("\n=== 测试分发错误处理 ===")

    # 创建消息总线
    message_bus = MemoryMessageBackend()
    await message_bus.start()

    # 创建Mock LLM适配器
    llm_adapter = MagicMock()

    # 创建TaskAgent（不启动）
    config = AgentConfig(
        name="task-agent-0",
        llm_config={"model": "gpt-4"},
    )
    task_agent = TaskAgent(
        agent_id=0,
        config=config,
        message_bus=message_bus,
        llm_adapter=llm_adapter,
    )
    task_agent.state = AgentState.RUNNING  # 手动设置为运行状态

    # 创建Master Agent（不启动）
    master_config = AgentConfig(
        name="master-agent",
        llm_config={"model": "gpt-4"},
    )
    master_agent = MasterAgent(
        config=master_config,
        message_bus=message_bus,
        task_agents=[task_agent],
    )

    initial_pending = task_agent.get_pending_count()
    print(f"  初始pending: {initial_pending}")

    # 注意：当前实现中，dispatch_task不会抛出异常
    # 因为事件发布失败不会导致dispatch_task返回False
    # 这里测试基本流程
    task = {"task_id": "test-001", "type": "test", "data": {}}
    await master_agent.dispatch_task(task)

    final_pending = task_agent.get_pending_count()
    print(f"  分发后pending: {final_pending}")
    assert final_pending == initial_pending + 1, "Pending should increase"

    # 清理
    task_agent.state = AgentState.STOPPED
    await message_bus.stop()
    print("✓ 错误处理测试通过")


async def main():
    """主测试函数"""
    print("=" * 50)
    print("负载均衡机制测试")
    print("=" * 50)

    try:
        await test_load_balancing()
        await test_select_from_running_agents()
        await test_no_available_agents()
        await test_dispatch_error_handling()

        print("\n" + "=" * 50)
        print("✓ 所有负载均衡测试通过!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
