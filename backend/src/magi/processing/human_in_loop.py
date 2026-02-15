"""
人机协作Decision
"""
from typing import Dict, Any, Optional, Callable
from .base import processingResult, TaskComplexity


class HumanInLoop:
    """
    人机协作

    在无法自主process时主动request人Class帮助
    """

    def __init__(self):
        """initialize人机协作"""
        # 人Class帮助callback
        self._help_callback: Optional[Callable] = None

        # pending的帮助request
        self._pending_requests: Dict[str, Dict] = {}

    def set_help_callback(self, callback: Callable):
        """
        Setting帮助callback

        Args:
            callback: callbackFunction，receive帮助context
        """
        self._help_callback = callback

    async def request_help(
        self,
        task: Dict[str, Any],
        complexity: TaskComplexity,
        context: Dict[str, Any]
    ) -> processingResult:
        """
        request人Class帮助

        Args:
            task: 任务Description
            complexity: complex度
            context: context

        Returns:
            processResult
        """
        # generation帮助context
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

        # 调用帮助callback
        if self._help_callback:
            result = await self._help_callback(help_context)
            return processingResult(
                action=result.get("action", {}),
                needs_human_help=True,
                complexity=complexity,
                human_help_context=help_context,
            )
        else:
            # 无callback，mark需要帮助
            return processingResult(
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
        从人Classprocessinglearning

        Args:
            task: 任务Description
            human_action: 人ClassExecute的action
        """
        # record人Classprocessway
        # TODO: storage到Memory System，用于后续learning
        pass

    async def _generate_options(self, task: Dict) -> list:
        """
        generationotttptional方案

        Args:
            task: 任务Description

        Returns:
            方案list
        """
        # 简化版：Return基本方案
        return [
            {"name": "skip", "description": "跳过任务"},
            {"name": "retry", "description": "重试任务"},
            {"name": "delegate", "description": "委托给otherAgent"},
        ]

    async def _generate_suggestion(self, task: Dict) -> str:
        """
        generationsuggestion

        Args:
            task: 任务Description

        Returns:
            suggestion文本
        """
        task_type = task.get("type", "unknotttwn")
        return f"suggestion人工process {task_type} type的任务"
