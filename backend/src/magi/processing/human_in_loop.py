"""
Human-agent collaboration decision
"""
from typing import Dict, Any, Optional, Callable
from .base import processingResult, TaskComplexity


class HumanInLoop:
    """
    Human-in-the-Loop

    Proactively requests human help when autonomous processing is not possible.
    """

    def __init__(self):
        """Initialize Human-in-the-Loop."""
        # Human help callback
        self._help_callback: Optional[Callable] = None

        # Pending help requests
        self._pending_requests: Dict[str, Dict] = {}

    def set_help_callback(self, callback: Callable):
        """
        Set the help callback.

        Args:
            callback: Callback function that receives the help context
        """
        self._help_callback = callback

    async def request_help(
        self,
        task: Dict[str, Any],
        complexity: TaskComplexity,
        context: Dict[str, Any]
    ) -> processingResult:
        """
        Request human help.

        Args:
            task: Task description
            complexity: Complexity
            context: Context

        Returns:
            Processing result
        """
        # Generate help context
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

        # Invoke help callback
        if self._help_callback:
            result = await self._help_callback(help_context)
            return processingResult(
                action=result.get("action", {}),
                needs_human_help=True,
                complexity=complexity,
                human_help_context=help_context,
            )
        else:
            # No callback, mark as needing help
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
        Learn from human processing.

        Args:
            task: Task description
            human_action: Action performed by the human
        """
        # Record human processing approach
        # TODO: Store in Memory System for future learning
        pass

    async def _generate_options(self, task: Dict) -> list:
        """
        Generate available options.

        Args:
            task: Task description

        Returns:
            List of options
        """
        # Simplified: return basic options
        return [
            {"name": "skip", "description": "Skip task"},
            {"name": "retry", "description": "Retry task"},
            {"name": "delegate", "description": "Delegate to another agent"},
        ]

    async def _generate_suggestion(self, task: Dict) -> str:
        """
        Generate a suggestion.

        Args:
            task: Task description

        Returns:
            Suggestion text
        """
        task_type = task.get("type", "unknown")
        return f"Suggest manual processing for {task_type} type tasks"
