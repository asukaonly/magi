"""
人机协作决策
"""
from typing import Dict, Any, Optional, Callable
from .base import ProcessingResult, TaskComplexity


class HumanInLoop:
    """
    人机协作

    在无法自主处理时主动请求人类帮助
    """

    def __init__(self):
        """初始化人机协作"""
        # 人类帮助回调
        self._help_callback: Optional[Callable] = None

        # 待处理的帮助请求
        self._pending_requests: Dict[str, Dict] = {}

    def set_help_callback(self, callback: Callable):
        """
        设置帮助回调

        Args:
            callback: 回调函数，接收帮助上下文
        """
        self._help_callback = callback

    async def request_help(
        self,
        task: Dict[str, Any],
        complexity: TaskComplexity,
        context: Dict[str, Any]
    ) -> ProcessingResult:
        """
        请求人类帮助

        Args:
            task: 任务描述
            complexity: 复杂度
            context: 上下文

        Returns:
            处理结果
        """
        # 生成帮助上下文
        help_context = {
            "task": task,
            "complexity": {
                "level": complexity.level.value,
                "score": complexity.score,
            },
            "context": context,
            "options": await self._generate_options(task),
            "suggestion": await self._generate_suggestion(task),
        }

        # 调用帮助回调
        if self._help_callback:
            result = await self._help_callback(help_context)
            return ProcessingResult(
                action=result.get("action", {}),
                needs_human_help=True,
                complexity=complexity,
                human_help_context=help_context,
            )
        else:
            # 无回调，标记需要帮助
            return ProcessingResult(
                action={},
                needs_human_help=True,
                complexity=complexity,
                human_help_context=help_context,
            )

    async def learn_from_human(
        self,
        task: Dict[str, Any],
        human_action: Dict[str, Any]
    ):
        """
        从人类处理中学习

        Args:
            task: 任务描述
            human_action: 人类执行的动作
        """
        # 记录人类处理方式
        # TODO: 存储到记忆系统，用于后续学习
        pass

    async def _generate_options(self, task: Dict) -> list:
        """
        生成可选方案

        Args:
            task: 任务描述

        Returns:
            方案列表
        """
        # 简化版：返回基本方案
        return [
            {"name": "skip", "description": "跳过任务"},
            {"name": "retry", "description": "重试任务"},
            {"name": "delegate", "description": "委托给其他Agent"},
        ]

    async def _generate_suggestion(self, task: Dict) -> str:
        """
        生成建议

        Args:
            task: 任务描述

        Returns:
            建议文本
        """
        task_type = task.get("type", "unknown")
        return f"建议人工处理 {task_type} 类型的任务"
