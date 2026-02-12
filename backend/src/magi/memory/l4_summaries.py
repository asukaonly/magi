"""
L4: 摘要层 (Summary Layer)

生成和存储多时间粒度的事件摘要
支持小时、天、周、月级别的摘要
"""
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


class EventSummary:
    """事件摘要"""

    def __init__(
        self,
        period_type: str,  # hour, day, week, month
        period_key: str,     # 时间窗口标识，如 "2024-01-01-12"
        start_time: float,
        end_time: float,
        event_count: int,
        summary: str,
        event_types: Dict[str, int],
        metrics: Dict[str, Any],
        key_events: List[Dict[str, Any]],
    ):
        self.period_type = period_type
        self.period_key = period_key
        self.start_time = start_time
        self.end_time = end_time
        self.event_count = event_count
        self.summary = summary
        self.event_types = event_types
        self.metrics = metrics
        self.key_events = key_events
        self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period_type": self.period_type,
            "period_key": self.period_key,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "event_count": self.event_count,
            "summary": self.summary,
            "event_types": self.event_types,
            "metrics": self.metrics,
            "key_events": self.key_events,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventSummary":
        return cls(**data)


class SummaryStore:
    """
    摘要存储

    生成和管理多时间粒度的事件摘要
    """

    def __init__(self, persist_path: str = None):
        """
        初始化摘要存储

        Args:
            persist_path: 持久化文件路径
        """
        self.persist_path = persist_path

        # 摘要存储：{period_type: {period_key: EventSummary}}
        self._summaries: Dict[str, Dict[str, EventSummary]] = defaultdict(dict)

        # 事件缓存：{period_type: {period_key: [events]}}
        self._event_cache: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))

        # 加载持久化数据
        if persist_path:
            self._load_from_disk()

    def add_event(self, event: Dict[str, Any]):
        """
        添加事件到缓存

        Args:
            event: 事件数据
        """
        event_timestamp = event.get("timestamp", time.time())

        # 缓存到各级时间窗口
        for period_type in ["hour", "day", "week", "month"]:
            period_key = self._get_period_key(event_timestamp, period_type)
            self._event_cache[period_type][period_key].append(event)

            # 限制缓存大小
            if len(self._event_cache[period_type][period_key]) > 1000:
                self._event_cache[period_type][period_key] = \
                    self._event_cache[period_type][period_key][-1000:]

    def generate_summary(
        self,
        period_type: str,
        period_key: str = None,
        force: bool = False,
    ) -> Optional[EventSummary]:
        """
        生成指定时间窗口的摘要

        Args:
            period_type: 时间粒度（hour/day/week/month）
            period_key: 时间窗口标识（None表示当前窗口）
            force: 是否强制重新生成

        Returns:
            事件摘要
        """
        if not period_key:
            period_key = self._get_period_key(time.time(), period_type)

        # 检查是否已存在
        if not force and period_key in self._summaries[period_type]:
            return self._summaries[period_type][period_key]

        # 获取该时间窗口的事件
        events = self._event_cache[period_type].get(period_key, [])
        if not events:
            return None

        # 生成摘要
        summary = self._generate_summary_from_events(events, period_type, period_key)

        # 存储摘要
        self._summaries[period_type][period_key] = summary

        # 持久化
        if self.persist_path:
            self._save_to_disk()

        logger.info(f"Summary generated: {period_type}/{period_key} ({len(events)} events)")

        return summary

    def _generate_summary_from_events(
        self,
        events: List[Dict[str, Any]],
        period_type: str,
        period_key: str,
    ) -> EventSummary:
        """
        从事件列表生成摘要

        Args:
            events: 事件列表
            period_type: 时间粒度
            period_key: 时间窗口标识

        Returns:
            事件摘要
        """
        if not events:
            return None

        # 分析事件
        event_types = defaultdict(int)
        key_events = []
        error_count = 0

        for event in events:
            event_type = event.get("type", "unknown")
            event_types[event_type] += 1

            # 记录关键事件
            if event.get("level") in ["EMERGENCY", "HIGH"] or event_type == "ErrorOccurred":
                key_events.append({
                    "timestamp": event.get("timestamp", 0),
                    "type": event_type,
                    "data": event.get("data", {}),
                })

            if event_type == "ErrorOccurred":
                error_count += 1

        # 计算时间范围
        timestamps = [e.get("timestamp", 0) for e in events]
        start_time = min(timestamps) if timestamps else time.time()
        end_time = max(timestamps) if timestamps else time.time()

        # 生成文本摘要
        summary_text = self._generate_text_summary(events, period_type, period_key, event_types)

        # 计算指标
        metrics = {
            "duration_hours": (end_time - start_time) / 3600,
            "error_rate": error_count / len(events) if events else 0,
            "most_common_type": max(event_types.items(), key=lambda x: x[1])[0] if event_types else "unknown",
        }

        return EventSummary(
            period_type=period_type,
            period_key=period_key,
            start_time=start_time,
            end_time=end_time,
            event_count=len(events),
            summary=summary_text,
            event_types=dict(event_types),
            metrics=metrics,
            key_events=key_events[:10],  # 最多10个关键事件
        )

    def _generate_text_summary(
        self,
        events: List[Dict[str, Any]],
        period_type: str,
        period_key: str,
        event_types: Dict[str, int],
    ) -> str:
        """
        生成文本摘要

        Args:
            events: 事件列表
            period_type: 时间粒度
            period_key: 时间窗口标识
            event_types: 事件类型统计

        Returns:
            文本摘要
        """
        lines = []

        # 标题
        period_name = self._format_period_name(period_type, period_key)
        lines.append(f"# {period_name} 摘要")

        # 基本统计
        lines.append(f"- 总事件数: {len(events)}")
        lines.append(f"- 时间范围: {self._format_timestamp(events[0].get('timestamp', 0))} - {self._format_timestamp(events[-1].get('timestamp', 0))}")

        # 事件类型分布
        if event_types:
            lines.append("- 事件类型分布:")
            for event_type, count in sorted(event_types.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  - {event_type}: {count}")

        # 关键事件
        key_events = [e for e in events if e.get("level") in ["EMERGENCY", "HIGH"]]
        if key_events:
            lines.append("- 关键事件:")
            for event in key_events[:5]:
                timestamp = datetime.fromtimestamp(event.get("timestamp", 0)).strftime("%H:%M:%S")
                lines.append(f"  - [{timestamp}] {event.get('type', 'unknown')}")

        # 错误统计
        error_count = event_types.get("ErrorOccurred", 0)
        if error_count > 0:
            lines.append(f"⚠️  错误数: {error_count}")

        return "\n".join(lines)

    def get_summary(
        self,
        period_type: str,
        period_key: str = None,
    ) -> Optional[EventSummary]:
        """
        获取摘要

        Args:
            period_type: 时间粒度
            period_key: 时间窗口标识（None表示当前）

        Returns:
            事件摘要
        """
        if not period_key:
            period_key = self._get_period_key(time.time(), period_type)

        return self._summaries[period_type].get(period_key)

    def get_summaries(
        self,
        period_type: str,
        limit: int = 10,
    ) -> List[EventSummary]:
        """
        获取多个摘要

        Args:
            period_type: 时间粒度
            limit: 数量限制

        Returns:
            摘要列表（按时间倒序）
        """
        summaries = list(self._summaries[period_type].values())
        summaries.sort(key=lambda s: s.end_time, reverse=True)
        return summaries[:limit]

    def _get_period_key(self, timestamp: float, period_type: str) -> str:
        """获取时间窗口标识"""
        dt = datetime.fromtimestamp(timestamp)

        if period_type == "hour":
            return dt.strftime("%Y-%m-%d-%H")
        elif period_type == "day":
            return dt.strftime("%Y-%m-%d")
        elif period_type == "week":
            # ISO 周数
            year, week, _ = dt.isocalendar()
            return f"{year}-W{week:02d}"
        elif period_type == "month":
            return dt.strftime("%Y-%m")
        else:
            return "unknown"

    def _format_period_name(self, period_type: str, period_key: str) -> str:
        """格式化时间窗口名称"""
        if period_type == "hour":
            return f"小时 ({period_key})"
        elif period_type == "day":
            return f"日期 ({period_key})"
        elif period_type == "week":
            return f"周 ({period_key})"
        elif period_type == "month":
            return f"月 ({period_key})"
        else:
            return period_key

    def _format_timestamp(self, timestamp: float) -> str:
        """格式化时间戳"""
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def _save_to_disk(self):
        """持久化到磁盘"""
        if not self.persist_path:
            return

        try:
            data = {
                "summaries": {
                    pt: {
                        pk: summary.to_dict()
                        for pk, summary in summaries.items()
                    }
                    for pt, summaries in self._summaries.items()
                }
            }

            with open(self.persist_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Summaries saved to {self.persist_path}")
        except Exception as e:
            logger.error(f"Failed to save summaries: {e}")

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

            summaries_data = data.get("summaries", {})
            for period_type, summaries in summaries_data.items():
                for period_key, summary_data in summaries.items():
                    self._summaries[period_type][period_key] = EventSummary.from_dict(summary_data)

            logger.info(f"Summaries loaded from {self.persist_path}")
        except Exception as e:
            logger.warning(f"Failed to load summaries: {e}")

    def clear_old_summaries(self, older_than_months: int = 12):
        """
        清理旧的摘要数据

        Args:
            older_than_months: 清理多少个月前的数据
        """
        cutoff_time = time.time() - (older_than_months * 30 * 86400)

        for period_type, summaries in self._summaries.items():
            keys_to_remove = []
            for key, summary in summaries.items():
                if summary.end_time < cutoff_time:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del summaries[key]

        logger.info(f"Cleared {sum(len(v) for v in self._summaries.values())} old summaries")

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        summary_counts = {
            period_type: len(summaries)
            for period_type, summaries in self._summaries.items()
        }

        return {
            "summary_counts": summary_counts,
            "total_summaries": sum(summary_counts.values()),
        }


class AutoSummarizer:
    """
    自动摘要生成器

    定期生成事件摘要
    """

    def __init__(self, summary_store: SummaryStore):
        self.summary_store = summary_store
        self._running = False

    async def start(self):
        """启动自动摘要生成"""
        self._running = True
        logger.info("Auto summarizer started")

    def stop(self):
        """停止自动摘要生成"""
        self._running = False
        logger.info("Auto summarizer stopped")

    async def generate_all_pending(self):
        """生成所有待处理的摘要"""
        now = time.time()

        for period_type in ["hour", "day", "week"]:
            period_key = self.summary_store._get_period_key(now, period_type)

            # 如果该窗口的摘要不存在，生成它
            if period_key not in self.summary_store._summaries[period_type]:
                self.summary_store.generate_summary(period_type, period_key)

        logger.info("All pending summaries generated")
