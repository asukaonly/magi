"""
优雅启停测试

测试顺序启动、逆序停止、超时控制、失败回滚等功能
"""
import asyncio
import sys
import os

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from magi.core.lifecycle import (
    GracefulShutdownManager,
    AgentLifecycleManager,
    ShutdownState,
)
from magi.core.agent import Agent, AgentConfig, AgentState
from magi.events.memory_backend import MemoryMessageBackend


class MockAgent(Agent):
    """模拟Agent（用于测试）"""

    def __init__(self, name: str, fail_on_start: bool = False, fail_on_stop: bool = False):
        super().__init__(
            AgentConfig(
                name=name,
                llm_config={"model": "gpt-4"},
            )
        )
        self.fail_on_start = fail_on_start
        self.fail_on_stop = fail_on_stop
        self.start_count = 0
        self.stop_count = 0

    async def _on_start(self):
        """启动逻辑"""
        self.start_count += 1
        print(f"  [{self.config.name}] Starting...")

        if self.fail_on_start:
            raise RuntimeError(f"{self.config.name} startup failed")

        await asyncio.sleep(0.1)  # 模拟启动耗时

        # 设置状态为RUNNING
        self.state = AgentState.RUNNING
        print(f"  [{self.config.name}] Started")

    async def _on_stop(self):
        """停止逻辑"""
        self.stop_count += 1
        print(f"  [{self.config.name}] Stopping...")

        if self.fail_on_stop:
            raise RuntimeError(f"{self.config.name} stop failed")

        await asyncio.sleep(0.1)  # 模拟停止耗时

        # 设置状态为STOPPED
        self.state = AgentState.STOPPED
        print(f"  [{self.config.name}] Stopped")


async def test_graceful_shutdown_manager():
    """测试优雅关闭管理器"""
    print("\n=== 测试GracefulShutdownManager ===")

    # 创建管理器
    manager = GracefulShutdownManager(
        shutdown_timeout=10.0,
        stop_order_reversed=True,
    )

    # 添加启动阶段
    manager.add_startup_stage(
        name="stage1",
        start_func=lambda: asyncio.sleep(0.01),
        stop_func=lambda: asyncio.sleep(0.01),
        critical=True,
    )

    manager.add_startup_stage(
        name="stage2",
        start_func=lambda: asyncio.sleep(0.01),
        stop_func=lambda: asyncio.sleep(0.01),
        dependencies=["stage1"],
        critical=False,
    )

    manager.add_startup_stage(
        name="stage3",
        start_func=lambda: asyncio.sleep(0.01),
        stop_func=lambda: asyncio.sleep(0.01),
        dependencies=["stage2"],
        critical=False,
    )

    # 测试启动
    success = await manager.startup()
    assert success, "Startup should succeed"

    # 测试关闭
    success = await manager.shutdown()
    assert success, "Shutdown should succeed"

    # 测试关闭状态
    assert manager.get_shutdown_state() == ShutdownState.SHUTDOWN_COMPLETE

    print("✓ GracefulShutdownManager测试通过")


async def test_startup_order():
    """测试启动顺序"""
    print("\n=== 测试启动顺序 ===")

    manager = GracefulShutdownManager()

    # 记录启动顺序
    startup_order = []

    async def start_stage1():
        startup_order.append("stage1")
        await asyncio.sleep(0.01)

    async def start_stage2():
        startup_order.append("stage2")
        await asyncio.sleep(0.01)

    async def start_stage3():
        startup_order.append("stage3")
        await asyncio.sleep(0.01)

    # 添加阶段（stage2依赖stage1，stage3依赖stage2）
    manager.add_startup_stage(
        "stage1", start_stage1, lambda: asyncio.sleep(0.01), critical=True
    )
    manager.add_startup_stage(
        "stage2", start_stage2, lambda: asyncio.sleep(0.01),
        dependencies=["stage1"], critical=False
    )
    manager.add_startup_stage(
        "stage3", start_stage3, lambda: asyncio.sleep(0.01),
        dependencies=["stage2"], critical=False
    )

    # 启动
    await manager.startup()

    # 验证顺序
    assert startup_order == ["stage1", "stage2", "stage3"], \
        f"Startup order should be stage1->stage2->stage3, got {startup_order}"

    # 关闭
    await manager.shutdown()

    print("✓ 启动顺序测试通过")


async def test_reverse_stop_order():
    """测试逆序停止"""
    print("\n=== 测试逆序停止 ===")

    manager = GracefulShutdownManager(stop_order_reversed=True)

    # 记录停止顺序
    stop_order = []

    async def stop_stage(name):
        stop_order.append(name)
        await asyncio.sleep(0.01)

    # 添加3个阶段
    for i in range(3):
        manager.add_startup_stage(
            f"stage{i}",
            lambda: asyncio.sleep(0.01),
            lambda n=i: stop_stage(f"stage{n}"),
            critical=False,
        )

    # 启动
    await manager.startup()

    # 关闭
    await manager.shutdown()

    # 验证逆序
    assert stop_order == ["stage2", "stage1", "stage0"], \
        f"Stop order should be reversed, got {stop_order}"

    print("✓ 逆序停止测试通过")


async def test_rollback_on_failure():
    """测试启动失败回滚"""
    print("\n=== 测试启动失败回滚 ===")

    manager = GracefulShutdownManager()

    # 记录回滚操作
    rolled_back = []

    async def start_fail():
        raise RuntimeError("Startup failed")

    async def stop_and_record(name):
        rolled_back.append(name)
        await asyncio.sleep(0.01)

    # 添加阶段：stage1正常，stage2失败（关键阶段），stage3
    manager.add_startup_stage(
        "stage1",
        lambda: asyncio.sleep(0.01),
        lambda: stop_and_record("stage1"),
        critical=False,
    )

    manager.add_startup_stage(
        "stage2",
        start_fail,
        lambda: asyncio.sleep(0.01),
        critical=True,  # 关键阶段，失败会触发回滚
    )

    manager.add_startup_stage(
        "stage3",
        lambda: asyncio.sleep(0.01),
        lambda: stop_and_record("stage3"),
        critical=False,
    )

    # 启动（应该在stage2失败并回滚stage1）
    success = await manager.startup()

    assert not success, "Startup should fail"
    assert "stage1" in rolled_back, "stage1 should be rolled back"

    print("✓ 启动失败回滚测试通过")


async def test_timeout_control():
    """测试超时控制"""
    print("\n=== 测试超时控制 ===")

    manager = GracefulShutdownManager()

    # 添加一个会超时的阶段
    async def slow_start():
        await asyncio.sleep(5.0)  # 5秒，超过超时时间

    manager.add_startup_stage(
        "slow_stage",
        slow_start,
        lambda: asyncio.sleep(0.01),
        timeout=0.5,  # 0.5秒超时
        critical=True,  # 关键阶段，超时会失败
    )

    # 启动（应该超时并失败）
    start_time = asyncio.get_event_loop().time()
    success = await manager.startup()
    duration = asyncio.get_event_loop().time() - start_time

    assert not success, "Startup should fail due to timeout"
    assert duration < 2.0, f"Should timeout quickly, took {duration}s"

    print("✓ 超时控制测试通过")


async def test_agent_lifecycle_manager():
    """测试Agent生命周期管理器"""
    print("\n=== 测试AgentLifecycleManager ===")

    # 创建模拟Agents
    master = MockAgent("master")
    task1 = MockAgent("task1")
    task2 = MockAgent("task2")

    # 创建消息总线
    message_bus = MemoryMessageBackend()

    # 设置master的message_bus
    master.message_bus = message_bus
    master.task_agents = [task1, task2]

    # 创建生命周期管理器
    lifecycle = AgentLifecycleManager(
        master_agent=master,
        task_agents=[task1, task2],
        shutdown_timeout=10.0,
    )

    # 测试启动
    success = await lifecycle.startup()
    assert success, "Startup should succeed"

    # 验证状态
    assert master.state == AgentState.RUNNING
    assert task1.state == AgentState.RUNNING
    assert task2.state == AgentState.RUNNING

    assert master.start_count == 1
    assert task1.start_count == 1
    assert task2.start_count == 1

    # 测试关闭
    success = await lifecycle.shutdown()
    assert success, "Shutdown should succeed"

    # 验证状态
    assert master.state == AgentState.STOPPED
    assert task1.state == AgentState.STOPPED
    assert task2.state == AgentState.STOPPED

    assert master.stop_count == 1
    assert task1.stop_count == 1
    assert task2.stop_count == 1

    print("✓ AgentLifecycleManager测试通过")


async def test_shutdown_callback():
    """测试关闭回调"""
    print("\n=== 测试关闭回调 ===")

    manager = GracefulShutdownManager()

    # 记录回调调用
    callback_called = []

    async def callback1():
        callback_called.append("callback1")
        print("  [Callback1] Cleanup resources...")

    async def callback2():
        callback_called.append("callback2")
        print("  [Callback2] Save state...")

    manager.register_shutdown_callback(callback1)
    manager.register_shutdown_callback(callback2)

    # 添加简单的阶段
    manager.add_startup_stage(
        "stage1",
        lambda: asyncio.sleep(0.01),
        lambda: asyncio.sleep(0.01),
        critical=False,
    )

    # 启动和关闭
    await manager.startup()
    await manager.shutdown()

    # 验证回调被调用
    assert "callback1" in callback_called
    assert "callback2" in callback_called

    print("✓ 关闭回调测试通过")


async def main():
    """主测试函数"""
    print("=" * 50)
    print("优雅启停测试")
    print("=" * 50)

    try:
        await test_graceful_shutdown_manager()
        await test_startup_order()
        await test_reverse_stop_order()
        await test_rollback_on_failure()
        await test_timeout_control()
        await test_agent_lifecycle_manager()
        await test_shutdown_callback()

        print("\n" + "=" * 50)
        print("✓ 所有优雅启停测试通过!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
