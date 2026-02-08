"""
记忆存储 - 统一接口
整合5层记忆架构
"""
import time
from .self_memory import SelfMemory
from .other_memory import OtherMemory, UserProfile
from .raw_event_store import RawEventStore
from .capability_store import CapabilityStore, CapabilityMemory


class MemoryStore:
    """
    记忆存储 - 5层架构统一接口

    L1: 原始事件（非结构化）
    L2: 事件关系（图数据库）- 待实现
    L3: 事件语义（向量嵌入）- 待实现
    L4: 摘要总结（多时间粒度）- 待实现
    L5: 能力记忆（自处理经验）
    """

    def __init__(self, base_path: str = "./data/memories"):
        """
        初始化记忆存储

        Args:
            base_path: 基础路径
        """
        self.base_path = base_path

        # 各层存储
        self.self_memory = SelfMemory(f"{base_path}/self_memory.db")
        self.other_memory = OtherMemory(f"{base_path}/other_memory.db")
        self.raw_events = RawEventStore(
            f"{base_path}/events.db",
            f"{base_path}/../events"
        )
        self.capabilities = CapabilityStore(
            f"{base_path}/capabilities.db",
            f"{base_path}/../chromadb"
        )

    async def init(self):
        """初始化所有存储层"""
        await self.self_memory.init()
        await self.other_memory.init()
        await self.raw_events.init()
        await self.capabilities.init()

    # ===== 自我记忆 =====

    async def get_agent_profile(self):
        return await self.self_memory.get_agent_profile()

    async def update_agent_profile(self, profile):
        await self.self_memory.update_agent_profile(profile)

    async def get_user_preferences(self):
        return await self.self_memory.get_user_preferences()

    async def update_user_preferences(self, updates):
        await self.self_memory.update_user_preferences(updates)

    # ===== 他人记忆 =====

    async def get_user_profile(self, user_id: str) -> UserProfile:
        return await self.other_memory.get_profile(user_id)

    async def update_user_profile(self, user_id: str, events=None):
        await self.other_memory.update_profile(user_id, events)

    async def create_user_profile(self, user_id: str, profile_data):
        await self.other_memory.create_profile(user_id, profile_data)

    # ===== L1: 原始事件 =====

    async def store_event(self, event):
        """存储事件到L1"""
        return await self.raw_events.store(event)

    async def get_event(self, event_id: str):
        """获取事件"""
        return await self.raw_events.get_event(event_id)

    # ===== L5: 能力记忆 =====

    async def save_capability(self, capability: CapabilityMemory):
        """沉淀能力"""
        await self.capabilities.save(capability)

    async def find_capability(self, perception_pattern: dict):
        """查找能力"""
        return await self.capabilities.find(perception_pattern)

    async def update_capability_success_rate(self, capability_id: str, success: bool):
        """更新成功率"""
        await self.capabilities.update_success_rate(capability_id, success)

    # ===== 通用接口 =====

    async def store_experience(self, perception, action, result):
        """
        存储经验（简化版）

        Args:
            perception: 感知
            action: 行动
            result: 结果
        """
        # 1. 存储原始事件
        from ..events.events import Event, EventTypes

        event = Event(
            type=EventTypes.EXPERIENCE_STORED,
            data={
                "perception": str(perception),
                "action": str(action),
                "result": str(result),
            },
            timestamp=time.time(),
            source="agent",
        )
        await self.store_event(event)

        # 2. 如果成功，沉淀能力
        if getattr(result, 'success', True):
            # TODO: 从成功经验中提取能力
            pass
