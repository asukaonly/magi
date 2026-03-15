"""
Failure learning mechanism
"""
import hashlib
from typing import Dict, Any, List, Optional
from collections import defaultdict
from .base import FailureCase, Failurepattern


class FailureLearner:
    """
    Failure Learner

    Learns from failure experiences to avoid repeating mistakes.
    """

    def __init__(self, llm_adapter=None):
        """
        Initialize the Failure Learner.

        Args:
            llm_adapter: LLM adapter (for intelligent analysis)
        """
        self.llm_adapter = llm_adapter

        # Failure case storage (grouped by type)
        self._failures_by_type: Dict[str, List[FailureCase]] = defaultdict(list)

        # Failure pattern cache
        self._patterns: Dict[str, Failurepattern] = {}

        # Pattern recognition threshold
        self.pattern_recognition_threshold = 5  # 5 failures of the same type trigger pattern recognition

    async def record_failure(
        self,
        task: Dict[str, Any],
        error: Exception,
        execution_steps: List[Dict]
    ):
        """
        Record a failure case.

        Args:
            task: Task description
            error: Error
            execution_steps: Execution steps
        """
        # Generate failure type
        failure_type = self._classify_failure(task, error)

        # Create failure case
        case = FailureCase(
            task_description=task.get("description", ""),
            failure_reason=str(error),
            error_stack=error.__class__.__name__,
            execution_steps=execution_steps,
        )

        # Store failure case
        self._failures_by_type[failure_type].append(case)

        # Check whether pattern recognition is needed
        if await self._should_recognize_pattern(failure_type):
            await self._recognize_pattern(failure_type)

    async def should_request_help(self, task: Dict[str, Any]) -> bool:
        """
        Determine whether to request human help.

        Args:
            task: Task description

        Returns:
            Whether help is needed
        """
        failure_type = self._classify_failure_type(task)

        # If this type has a failure pattern, check for a match
        if failure_type in self._patterns:
            pattern = self._patterns[failure_type]
            # TODO: More refined matching logic
            return True

        # Check historical failure count
        failures = self._failures_by_type.get(failure_type, [])
        return len(failures) >= 3  # Request help after 3+ failures of the same type

    async def get_avoidance_strategy(
        self,
        task: Dict[str, Any]
    ) -> Optional[str]:
        """
        Get avoidance strategy.

        Args:
            task: Task description

        Returns:
            Avoidance strategy or None
        """
        failure_type = self._classify_failure_type(task)

        if failure_type in self._patterns:
            pattern = self._patterns[failure_type]
            return pattern.avoidance_strategy

        return None

    def _classify_failure(self, task: Dict, error: Exception) -> str:
        """
        Classify failure type.

        Args:
            task: Task
            error: Error

        Returns:
            Failure type
        """
        # Classify based on error type
        error_type = error.__class__.__name__

        # Can be further refined by combining task info
        task_type = task.get("type", "")

        return f"{task_type}:{error_type}"

    def _classify_failure_type(self, task: Dict) -> str:
        """
        Predict the likely failure type for a task.

        Args:
            task: Task description

        Returns:
            Failure type
        """
        # Simplified: based on task type
        task_type = task.get("type", "")
        return f"{task_type}:Unknotttwn"

    async def _should_recognize_pattern(self, failure_type: str) -> bool:
        """Determine whether failure pattern recognition should be triggered."""
        failures = self._failures_by_type.get(failure_type, [])
        return len(failures) >= self.pattern_recognition_threshold

    async def _recognize_pattern(self, failure_type: str):
        """
        Recognize failure patterns.

        Args:
            failure_type: Failure type
        """
        failures = self._failures_by_type.get(failure_type, [])

        if not failures:
            return

        # Simplified: generate pattern based on failure reasons
        # Actual implementation could use LLM for intelligent analysis

        # Find the most common failure reason
        reason_count = defaultdict(int)
        for case in failures:
            reason_count[case.failure_reason] += 1

        most_common_reason = max(reason_count.items(), key=lambda x: x[1])[0]

        # Generate pattern ID
        pattern_id = hashlib.md5(failure_type.encode()).hexdigest()[:8]

        # Create failure pattern
        pattern = Failurepattern(
            pattern_id=pattern_id,
            description=f"Failure pattern: {failure_type}",
            avoidance_strategy=f"Avoid: {most_common_reason}",
            case_count=len(failures),
        )

        self._patterns[failure_type] = pattern
