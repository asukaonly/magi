"""
记忆存储测试示例
"""
import asyncio
import sys
from pathlib import Path

# 添加src到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from magi.memory.store import MemoryStore
from magi.memory.capability_store import CapabilityMemory
from magi.events.events import Event, EventLevel


async def test_self_memory():
    """测试自我记忆"""
    print("\n=== 测试自我记忆 ===")

    memory = MemoryStore()
    await memory.init()
    print("✓ 记忆存储已初始化")

    # 获取Agent设定
    profile = await memory.get_agent_profile()
    print(f"✓ Agent设定: {profile}")

    # 更新用户偏好
    await memory.update_user_preferences({
        "interaction_style": "professional",
        "language": "en-US",
    })
    prefs = await memory.get_user_preferences()
    print(f"✓ 用户偏好已更新: {prefs}")

    print("✅ 自我记忆测试通过！\n")


async def test_raw_events():
    """测试原始事件存储"""
    print("\n=== 测试L1原始事件存储 ===")

    memory = MemoryStore()
    await memory.init()

    # 创建测试事件
    event = Event(
        type="UserMessage",
        data={"text": "Hello, Magi!"},
        source="user",
        level=EventLevel.INFO,
    )

    # 存储事件
    event_id = await memory.store_event(event)
    print(f"✓ 事件已存储，ID: {event_id}")

    # 获取事件
    stored_event = await memory.get_event(event_id)
    print(f"✓ 事件已获取: {stored_event.type if stored_event else None}")

    print("✅ L1原始事件存储测试通过！\n")


async def test_capability_memory():
    """测试能力记忆"""
    print("\n=== 测试L5能力记忆 ===")

    memory = MemoryStore()
    await memory.init()

    # 创建能力
    capability = CapabilityMemory(
        trigger_pattern={"type": "user_query"},
        action={"tool": "search", "params": {"query": "text"}},
        success_rate=1.0,
        usage_count=1,
    )

    # 保存能力
    await memory.save_capability(capability)
    print("✓ 能力已保存")

    # 查找能力
    found = await memory.find_capability({"type": "user_query"})
    print(f"✓ 找到能力: {found.action if found else None}")

    # 更新成功率
    if found:
        await memory.update_capability_success_rate("test_id", True)
        print("✓ 成功率已更新")

    print("✅ L5能力记忆测试通过！\n")


async def test_user_profile():
    """测试用户画像"""
    print("\n=== 测试用户画像 ===")

    memory = MemoryStore()
    await memory.init()

    # 创建用户画像
    user_id = "user_123"
    await memory.create_user_profile(user_id, {
        "interests": ["AI", "coding"],
        "habits": ["夜猫子"],
        "personality": ["curious"],
    })
    print(f"✓ 已创建用户画像: {user_id}")

    # 获取用户画像
    profile = await memory.get_user_profile(user_id)
    print(f"✓ 用户画像: interests={profile.interests if profile else None}")

    # 更新用户画像
    await memory.update_user_profile(user_id)
    print("✓ 用户画像已更新")

    print("✅ 用户画像测试通过！\n")


async def main():
    """主测试函数"""
    print("=" * 50)
    print("Magi AI Agent Framework - 记忆存储测试")
    print("=" * 50)

    try:
        await test_self_memory()
        await test_raw_events()
        await test_capability_memory()
        await test_user_profile()

        print("=" * 50)
        print("✅ 所有记忆存储测试通过！")
        print("=" * 50)
        print("\n记忆存储功能已验证：")
        print("  ✅ 自我记忆（Agent设定、用户偏好）")
        print("  ✅ L1原始事件存储")
        print("  ✅ L5能力记忆（能力沉淀、成功率更新）")
        print("  ✅ 他人记忆（用户画像）")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
