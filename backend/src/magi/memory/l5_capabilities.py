"""
L5: 能力记忆层 (Capability Memory Layer)

从成功经验中提取可复用的能力
支持能力存储、查询、复用
"""
import logging
import time
from typing import Dict, Any, List, Optional, Callable, Set
from datetime import datetime
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


class Capability:
    """
    能力定义

    从成功经验中提取的可复用能力
    """

    def __init__(
        self,
        capability_id: str,
        name: str,
        description: str,
        trigger_pattern: Dict[str, Any],  # 触发条件
        action: Dict[str, Any],           # 执行动作
        success_rate: float = 0.0,        # 成功率
        usage_count: int = 0,             # 使用次数
        avg_duration: float = 0.0,         # 平均执行时间
        last_used: float = 0,             # 最后使用时间
        created_at: float = None,          # 创建时间
        examples: List[Dict[str, Any]] = None,  # 成功案例
        failures: List[str] = None,        # 失败教训
    ):
        self.capability_id = capability_id
        self.name = name
        self.description = description
        self.trigger_pattern = trigger_pattern
        self.action = action
        self.success_rate = success_rate
        self.usage_count = usage_count
        self.avg_duration = avg_duration
        self.last_used = last_used
        self.created_at = created_at or time.time()
        self.examples = examples or []
        self.failures = failures or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "trigger_pattern": self.trigger_pattern,
            "action": self.action,
            "success_rate": self.success_rate,
            "usage_count": self.usage_count,
            "avg_duration": self.avg_duration,
            "last_used": self.last_used,
            "created_at": self.created_at,
            "examples": self.examples,
            "failures": self.failures,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Capability":
        return cls(**data)

    def matches(self, context: Dict[str, Any]) -> float:
        """
        判断能力是否匹配当前上下文

        Args:
            context: 上下文信息

        Returns:
            匹配分数（0-1）
        """
        score = 0.0

        # 检查触发条件
        pattern = self.trigger_pattern

        # 检查类型匹配
        if "event_types" in pattern:
            context_type = context.get("event_type", "")
            if context_type in pattern["event_types"]:
                score += 0.3

        # 检查关键词匹配
        if "keywords" in pattern:
            context_text = str(context.get("message", ""))
            for keyword in pattern["keywords"]:
                if keyword.lower() in context_text.lower():
                    score += 0.2

        # 检查参数匹配
        if "requires_params" in pattern:
            context_params = context.get("parameters", {})
            required = pattern["requires_params"]
            if all(k in context_params for k in required):
                score += 0.5

        return min(score, 1.0)


class CapabilityMemory:
    """
    能力记忆系统

    管理能力的提取、存储、查询和复用
    """

    def __init__(self, persist_path: str = None):
        """
        初始化能力记忆

        Args:
            persist_path: 持久化文件路径
        """
        self.persist_path = persist_path

        # 能力存储：{capability_id: Capability}
        self._capabilities: Dict[str, Capability] = {}

        # 使用统计：{capability_id: {attempt: total, success: success_count}}
        self._stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"attempt": 0, "success": 0})

        # 黑名单：成功率过低的能力
        self._blacklist: Set[str] = set()

        # 加载持久化数据
        if persist_path:
            self._load_from_disk()

    def record_attempt(
        self,
        task_id: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        success: bool,
        duration: float = 0.0,
        error: str = None,
    ):
        """
        记录任务执行尝试

        Args:
            task_id: 任务ID
            context: 上下文信息
            action: 执行的动作
            success: 是否成功
            duration: 执行时间
            error: 错误信息
        """
        # 更新统计
        self._stats[task_id]["attempt"] += 1
        if success:
            self._stats[task_id]["success"] += 1

        # 计算成功率
        stats = self._stats[task_id]
        success_rate = stats["success"] / stats["attempt"] if stats["attempt"] > 0 else 0

        # 检查是否需要提取能力
        if stats["attempt"] >= 3 and success_rate >= 0.7:
            self._extract_capability(task_id, context, action, stats)

        # 更新现有能力的统计
        for capability in self._capabilities.values():
            if capability.matches(context):
                capability.usage_count += 1
                capability.last_used = time.time()

                # 更新成功率（指数移动平均）
                alpha = 0.3
                capability.success_rate = alpha * success_rate + (1 - alpha) * capability.success_rate

                # 更新平均执行时间
                if duration > 0:
                    if capability.avg_duration > 0:
                        capability.avg_duration = 0.7 * capability.avg_duration + 0.3 * duration
                    else:
                        capability.avg_duration = duration

                # 记录使用案例或失败
                if success:
                    if len(capability.examples) < 10:
                        capability.examples.append({
                            "timestamp": time.time(),
                            "context": context,
                        })
                else:
                    if error and len(capability.failures) < 5:
                        capability.failures.append(error)

        # 检查黑名单
        if success_rate < 0.3 and stats["attempt"] >= 5:
            self._blacklist.add(task_id)

        # 持久化
        if self.persist_path:
            self._save_to_disk()

    def _extract_capability(
        self,
        task_id: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        stats: Dict[str, int],
    ):
        """
        从任务执行中提取能力

        Args:
            task_id: 任务ID
            context: 上下文
            action: 执行的动作
            stats: 统计信息
        """
        # 生成触发条件
        trigger_pattern = self._analyze_trigger_pattern(context, action)

        capability_id = f"cap_{task_id}"

        capability = Capability(
            capability_id=capability_id,
            name=self._generate_capability_name(context, action),
            description=f"从任务 '{task_id}' 提取的能力",
            trigger_pattern=trigger_pattern,
            action=action,
            success_rate=stats["success"] / stats["attempt"],
            usage_count=stats["attempt"],
            avg_duration=0.0,
            last_used=time.time(),
        )

        self._capabilities[capability_id] = capability
        logger.info(f"Capability extracted: {capability_id}")

    def _analyze_trigger_pattern(self, context: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
        """分析触发条件"""
        pattern = {
            "event_types": [],
            "keywords": [],
            "requires_params": [],
        }

        # 从上下文中提取类型
        if "event_type" in context:
            pattern["event_types"].append(context["event_type"])

        # 从动作中提取参数
        if "tool" in action:
            pattern["keywords"].append(action["tool"])

        # 从消息中提取关键词
        message = context.get("message", "")
        if isinstance(message, str):
            # 简单的关键词提取
            words = message.split()
            pattern["keywords"].extend([w for w in words if len(w) > 3])

        return pattern

    def _generate_capability_name(self, context: Dict[str, Any], action: Dict[str, Any]) -> str:
        """生成能力名称"""
        tool = action.get("tool", "")
        event_type = context.get("event_type", "")

        if tool:
            return f"{tool}能力"
        elif event_type:
            return f"{event_type}处理能力"
        else:
            return "通用能力"

    def find_capability(
        self,
        context: Dict[str, Any],
        threshold: float = 0.5,
    ) -> Optional[Capability]:
        """
        查找匹配的能力

        Args:
            context: 上下文信息
            threshold: 匹配阈值

        Returns:
            匹配的能力，或 None
        """
        best_capability = None
        best_score = threshold

        for capability in self._capabilities.values():
            # 跳过黑名单
            if capability.capability_id in self._blacklist:
                continue

            score = capability.matches(context)
            if score > best_score:
                best_score = score
                best_capability = capability

        return best_capability

    def get_all_capabilities(self) -> List[Capability]:
        """获取所有能力"""
        return list(self._capabilities.values())

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        """获取指定能力"""
        return self._capabilities.get(capability_id)

    def delete_capability(self, capability_id: str) -> bool:
        """
        删除能力

        Args:
            capability_id: 能力ID

        Returns:
            是否删除成功
        """
        if capability_id in self._capabilities:
            del self._capabilities[capability_id]
            if capability_id in self._stats:
                del self._stats[capability_id]
            self._blacklist.discard(capability_id)

            if self.persist_path:
                self._save_to_disk()

            logger.info(f"Capability deleted: {capability_id}")
            return True
        return False

    def _save_to_disk(self):
        """持久化到磁盘"""
        if not self.persist_path:
            return

        try:
            data = {
                "capabilities": {
                    cap_id: cap.to_dict()
                    for cap_id, cap in self._capabilities.items()
                },
                "stats": dict(self._stats),
                "blacklist": list(self._blacklist),
            }

            with open(self.persist_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Capabilities saved to {self.persist_path}")
        except Exception as e:
            logger.error(f"Failed to save capabilities: {e}")

    def _load_from_disk(self):
        """从磁盘加载"""
        if not self.persist_path:
            return

        try:
            from pathlib import Path
            path = Path(self.persist_path)
            if not path.exists():
                return

            with open(self.persist_path, "r") as f:
                data = json.load(f)

            # 加载能力
            for cap_id, cap_data in data.get("capabilities", {}).items():
                self._capabilities[cap_id] = Capability.from_dict(cap_data)

            # 加载统计
            self._stats = defaultdict(lambda: {"attempt": 0, "success": 0})
            for task_id, stats in data.get("stats", {}).items():
                self._stats[task_id] = stats

            # 加载黑名单
            self._blacklist = set(data.get("blacklist", []))

            logger.info(f"Capabilities loaded from {self.persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load capabilities: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_capabilities": len(self._capabilities),
            "blacklist_count": len(self._blacklist),
            "most_used_capabilities": sorted(
                [(cap_id, cap.usage_count) for cap_id, cap in self._capabilities.items()],
                key=lambda x: x[1],
                reverse=True
            )[:5],
        }
