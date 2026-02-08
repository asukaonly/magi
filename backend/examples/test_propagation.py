"""
双传播模式测试

测试事件系统的双传播模式（BROADCAST/COMPETING/ROUND_ROBIN）
"""
import asyncio
import sys
import os

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from magi.events.events import Event, EventLevel
from magi.events.enhanced_backend import (
    EnhancedMemoryMessageBackend,
    PropagationMode,
    DropPolicy,
    BoundedPriorityQueue,
    LoadAwareDispatcher,
)


class EventTracker:
    """事件跟踪器（用于测试）"""

    def __init__(self, name: str):
        self.name = name
        self.received_events = []
        self.processed_events = []

    async def handle(self, event: Event):
        """处理事件"""
        self.received_events.append(event)

        # 模拟处理耗时
        await asyncio.sleep(0.01)

        self.processed_events.append(event)

    def get_count(self) -> int:
        """获取接收事件数量"""
        return len(self.received_events)

    def clear(self):
        """清空"""
        self.received_events.clear()
        self.processed_events.clear()


async def test_broadcast_mode():
    """测试广播模式"""
    print("\n=== 测试Broadcast模式 ===")

    backend = EnhancedMemoryMessageBackend(
        max_queue_size=100,
        num_workers=2,
    )
    await backend.start()

    # 创建3个订阅者
    tracker1 = EventTracker("handler1")
    tracker2 = EventTracker("handler2")
    tracker3 = EventTracker("handler3")

    # 订阅事件（都使用BROADCAST模式）
    await backend.subscribe(
        "test.event",
        tracker1.handle,
        PropagationMode.BROADCAST,
    )
    await backend.subscribe(
        "test.event",
        tracker2.handle,
        PropagationMode.BROADCAST,
    )
    await backend.subscribe(
        "test.event",
        tracker3.handle,
        PropagationMode.BROADCAST,
    )

    # 发布事件
    event = Event(
        type="test.event",
        data={"message": "broadcast test"},
        level=EventLevel.INFO,
    )
    await backend.publish(event)

    # 等待处理
    await asyncio.sleep(0.2)

    # 验证：所有订阅者都收到事件
    assert tracker1.get_count() == 1, f"handler1 should receive 1 event, got {tracker1.get_count()}"
    assert tracker2.get_count() == 1, f"handler2 should receive 1 event, got {tracker2.get_count()}"
    assert tracker3.get_count() == 1, f"handler3 should receive 1 event, got {tracker3.get_count()}"

    await backend.stop()
    print("✓ Broadcast模式测试通过")


async def test_competing_mode():
    """测试竞争模式"""
    print("\n=== 测试Competing模式 ===")

    backend = EnhancedMemoryMessageBackend(
        max_queue_size=100,
        num_workers=2,
    )
    await backend.start()

    # 创建3个订阅者（都使用COMPETING模式）
    tracker1 = EventTracker("handler1")
    tracker2 = EventTracker("handler2")
    tracker3 = EventTracker("handler3")

    await backend.subscribe(
        "test.event",
        tracker1.handle,
        PropagationMode.COMPETING,
    )
    await backend.subscribe(
        "test.event",
        tracker2.handle,
        PropagationMode.COMPETING,
    )
    await backend.subscribe(
        "test.event",
        tracker3.handle,
        PropagationMode.COMPETING,
    )

    # 发布3个事件
    for i in range(3):
        event = Event(
            type="test.event",
            data={"index": i},
            level=EventLevel.INFO,
        )
        await backend.publish(event)

    # 等待处理
    await asyncio.sleep(0.5)

    # 验证：负载均衡分布（每个handler应该处理约1个事件）
    total = tracker1.get_count() + tracker2.get_count() + tracker3.get_count()
    assert total == 3, f"Total should be 3, got {total}"

    # 验证分布相对均衡
    counts = [tracker1.get_count(), tracker2.get_count(), tracker3.get_count()]
    max_count = max(counts)
    min_count = min(counts)
    assert max_count - min_count <= 1, "Load should be balanced"

    print(f"  分布: {counts}")
    await backend.stop()
    print("✓ Competing模式测试通过")


async def test_round_robin_mode():
    """测试轮询模式"""
    print("\n=== 测试Round-Robin模式 ===")

    backend = EnhancedMemoryMessageBackend(
        max_queue_size=100,
        num_workers=2,
    )
    await backend.start()

    # 创建3个订阅者（都使用ROUND_ROBIN模式）
    tracker1 = EventTracker("handler1")
    tracker2 = EventTracker("handler2")
    tracker3 = EventTracker("handler3")

    await backend.subscribe(
        "test.event",
        tracker1.handle,
        PropagationMode.ROUND_ROBIN,
    )
    await backend.subscribe(
        "test.event",
        tracker2.handle,
        PropagationMode.ROUND_ROBIN,
    )
    await backend.subscribe(
        "test.event",
        tracker3.handle,
        PropagationMode.ROUND_ROBIN,
    )

    # 发布6个事件
    for i in range(6):
        event = Event(
            type="test.event",
            data={"index": i},
            level=EventLevel.INFO,
        )
        await backend.publish(event)

    # 等待处理
    await asyncio.sleep(0.5)

    # 验证：轮询分布（每个handler应该处理2个事件）
    assert tracker1.get_count() == 2, f"handler1 should receive 2 events, got {tracker1.get_count()}"
    assert tracker2.get_count() == 2, f"handler2 should receive 2 events, got {tracker2.get_count()}"
    assert tracker3.get_count() == 2, f"handler3 should receive 2 events, got {tracker3.get_count()}"

    print(f"  分布: {[tracker1.get_count(), tracker2.get_count(), tracker3.get_count()]}")
    await backend.stop()
    print("✓ Round-Robin模式测试通过")


async def test_mixed_modes():
    """测试混合传播模式"""
    print("\n=== 测试混合传播模式 ===")

    backend = EnhancedMemoryMessageBackend(
        max_queue_size=100,
        num_workers=2,
    )
    await backend.start()

    # 创建订阅者：2个BROADCAST，2个COMPETING
    broadcast1 = EventTracker("broadcast1")
    broadcast2 = EventTracker("broadcast2")
    competing1 = EventTracker("competing1")
    competing2 = EventTracker("competing2")

    await backend.subscribe("test.event", broadcast1.handle, PropagationMode.BROADCAST)
    await backend.subscribe("test.event", broadcast2.handle, PropagationMode.BROADCAST)
    await backend.subscribe("test.event", competing1.handle, PropagationMode.COMPETING)
    await backend.subscribe("test.event", competing2.handle, PropagationMode.COMPETING)

    # 发布事件
    event = Event(
        type="test.event",
        data={"message": "mixed mode test"},
        level=EventLevel.INFO,
    )
    await backend.publish(event)

    # 等待处理
    await asyncio.sleep(0.2)

    # 验证：BROADCAST订阅者都收到，COMPETING只有一个收到
    assert broadcast1.get_count() == 1
    assert broadcast2.get_count() == 1

    competing_total = competing1.get_count() + competing2.get_count()
    assert competing_total == 1, f"Only one competing handler should receive, got {competing_total}"

    await backend.stop()
    print("✓ 混合传播模式测试通过")


async def test_event_filter():
    """测试事件过滤"""
    print("\n=== 测试事件过滤 ===")

    backend = EnhancedMemoryMessageBackend(
        max_queue_size=100,
        num_workers=2,
    )
    await backend.start()

    # 创建订阅者和过滤函数
    tracker = EventTracker("filtered_handler")

    # 只处理priority >= WARNING的事件
    def filter_high_priority(event: Event) -> bool:
        return event.level.value >= EventLevel.WARNING.value

    await backend.subscribe(
        "test.event",
        tracker.handle,
        PropagationMode.BROADCAST,
        filter_func=filter_high_priority,
    )

    # 发布INFO事件（应该被过滤）
    info_event = Event(
        type="test.event",
        data={"level": "info"},
        level=EventLevel.INFO,
    )
    await backend.publish(info_event)

    await asyncio.sleep(0.1)

    assert tracker.get_count() == 0, "INFO event should be filtered"

    # 发布WARNING事件（应该通过）
    warning_event = Event(
        type="test.event",
        data={"level": "warning"},
        level=EventLevel.WARNING,
    )
    await backend.publish(warning_event)

    await asyncio.sleep(0.1)

    assert tracker.get_count() == 1, "WARNING event should pass through"

    await backend.stop()
    print("✓ 事件过滤测试通过")


async def test_backpressure():
    """测试背压机制"""
    print("\n=== 测试背压机制 ===")

    backend = EnhancedMemoryMessageBackend(
        max_queue_size=5,  # 小队列测试背压
        num_workers=2,
        drop_policy=DropPolicy.LOWEST_PRIORITY,
    )
    await backend.start()

    # 创建慢速handler
    class SlowHandler:
        def __init__(self):
            self.count = 0
            self.lock = asyncio.Lock()

        async def handle(self, event: Event):
            async with self.lock:
                self.count += 1
                # 模拟慢速处理
                await asyncio.sleep(0.2)

    slow_handler = SlowHandler()

    await backend.subscribe(
        "test.event",
        slow_handler.handle,
        PropagationMode.BROADCAST,
    )

    # 快速发布多个事件
    published_count = 0
    for i in range(10):
        event = Event(
            type="test.event",
            data={"index": i},
            level=EventLevel.INFO,
        )
        success = await backend.publish(event)
        if success:
            published_count += 1

    # 由于队列大小限制和慢速handler，部分事件会被丢弃
    print(f"  发布了 {published_count}/10 个事件")

    # 等待队列清空
    await asyncio.sleep(1.0)

    stats = backend.get_stats()
    print(f"  队列统计: {stats['queue_stats']}")
    print(f"  处理了: {slow_handler.count} 个事件")

    assert stats["queue_stats"]["current_size"] <= 5, "Queue should be bounded"

    await backend.stop()
    print("✓ 背压机制测试通过")


async def test_error_isolation():
    """测试错误隔离"""
    print("\n=== 测试错误隔离 ===")

    backend = EnhancedMemoryMessageBackend(
        max_queue_size=100,
        num_workers=2,
    )
    await backend.start()

    # 创建订阅者
    good_handler = EventTracker("good_handler")
    bad_handler = EventTracker("bad_handler")

    # bad_handler会抛异常
    async def failing_handler(event: Event):
        raise RuntimeError("Handler failed!")

    await backend.subscribe("test.event", good_handler.handle, PropagationMode.BROADCAST)
    await backend.subscribe("test.event", failing_handler, PropagationMode.BROADCAST)

    # 发布事件
    event = Event(
        type="test.event",
        data={"message": "error isolation test"},
        level=EventLevel.INFO,
    )
    await backend.publish(event)

    # 等待处理
    await asyncio.sleep(0.2)

    # 验证：good_handler仍然收到事件，尽管bad_handler失败
    assert good_handler.get_count() == 1, "Good handler should still receive event"

    stats = backend.get_stats()
    assert stats["error_count"] > 0, "Should have recorded errors"

    await backend.stop()
    print("✓ 错误隔离测试通过")


async def test_graceful_shutdown():
    """测试优雅关闭"""
    print("\n=== 测试优雅关闭 ===")

    backend = EnhancedMemoryMessageBackend(
        max_queue_size=100,
        num_workers=2,
    )
    await backend.start()

    # 创建handler
    tracker = EventTracker("shutdown_handler")

    async def slow_handler(event: Event):
        await asyncio.sleep(0.1)
        await tracker.handle(event)

    await backend.subscribe("test.event", slow_handler, PropagationMode.BROADCAST)

    # 发布多个事件
    for i in range(5):
        event = Event(
            type="test.event",
            data={"index": i},
            level=EventLevel.INFO,
        )
        await backend.publish(event)

    # 立即停止
    stats_before = backend.get_stats()
    print(f"  停止前队列大小: {stats_before['queue_stats']['current_size']}")

    await backend.stop()

    stats_after = backend.get_stats()
    print(f"  停止后队列大小: {stats_after['queue_stats']['current_size']}")

    print("✓ 优雅关闭测试通过")


async def test_queue_stats():
    """测试队列统计"""
    print("\n=== 测试队列统计 ===")

    queue = BoundedPriorityQueue(
        max_size=10,
        drop_policy=DropPolicy.LOWEST_PRIORITY,
    )

    # 发布一些事件
    for i in range(5):
        event = Event(
            type="test",
            data={"index": i},
            level=EventLevel.INFO,
        )
        await queue.enqueue(event)

    stats = queue.get_stats()
    print(f"  统计: {stats}")
    assert stats["current_size"] == 5
    assert stats["utilization"] == 0.5

    print("✓ 队列统计测试通过")


async def main():
    """主测试函数"""
    print("=" * 50)
    print("双传播模式测试")
    print("=" * 50)

    try:
        await test_broadcast_mode()
        await test_competing_mode()
        await test_round_robin_mode()
        await test_mixed_modes()
        await test_event_filter()
        await test_backpressure()
        await test_error_isolation()
        await test_graceful_shutdown()
        await test_queue_stats()

        print("\n" + "=" * 50)
        print("✓ 所有双传播模式测试通过!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
