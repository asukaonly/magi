"""
Router layer for five-layer architecture.
"""
from __future__ import annotations

from .contracts import LayerContext, RouteDecision
from .types import LayerTaskType, StubCapability


class RouterLayer:
    """Maps normalized context to task routing decisions."""

    def route(self, context: LayerContext) -> RouteDecision:
        text = context.message.lower()

        stub_map = (
            (("通知", "notification", "提醒"), StubCapability.MSG_NOTIFICATION, "notification"),
            (("资产", "asset", "记录"), StubCapability.DIGITAL_ASSET_STORAGE, "asset_storage"),
            (("定时", "schedule", "cron"), StubCapability.SCHEDULE_TASK, "schedule"),
            (("设备", "physical", "环境干预"), StubCapability.PHYSICAL_ENV_INTERVENTION, "physical_intervention"),
        )
        for keywords, capability, intent in stub_map:
            if any(keyword in text for keyword in keywords):
                return RouteDecision(
                    task_type=LayerTaskType.STUB_CAPABILITY,
                    intent=intent,
                    reasoning=f"Matched reserved capability: {capability.value}",
                    stub_capability=capability,
                )

        if any(word in text for word in ("calculate", "statistics", "analysis", "计算", "统计", "分析")):
            return RouteDecision(
                task_type=LayerTaskType.COMPUTATION,
                intent="computation",
                reasoning="Detected computation intent",
            )

        if any(word in text for word in ("帮我", "请", "can you", "help", "帮助")):
            return RouteDecision(
                task_type=LayerTaskType.INTERACTIVE,
                intent="interactive",
                reasoning="Detected interactive intent",
            )

        return RouteDecision(
            task_type=LayerTaskType.CHAT,
            intent="chat",
            reasoning="Default chat route",
        )
