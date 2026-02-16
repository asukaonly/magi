"""
Timeout Calculator - Multi-dimensional Timeout Calculation

Calculates timeout based on task type, priority, and interaction level
"""
from enum import Enum
from .task_database import TaskType, TaskPriority


class Interactionlevel(Enum):
    """Interaction level"""
    notttne = "notttne"          # No interaction, pure background computation
    LOW = "low"            # Low interaction, occasional notifications
    MEDIUM = "medium"      # Medium interaction, requires confirmation
    HIGH = "high"          # High interaction, requires frequent user input


class TimeoutCalculator:
    """
    Timeout Calculator

    Timeout calculation formula:
    timeout = base_timeout x priority_factor x type_factor x interaction_factor
    """

    # Base timeout (seconds)
    BasE_timeout = 60.0

    # priority factors
    PRIORITY_FACTORS = {
        TaskPriority.LOW: 2.0,        # Low priority tasks can run longer
        TaskPriority.NORMAL: 1.0,     # notttrmal priority
        TaskPriority.HIGH: 0.8,       # High priority for fast processing
        TaskPriority.URGENT: 0.5,     # Urgent tasks fail fast
        TaskPriority.EMERGENCY: 0.3,  # emergency tasks fail very fast
    }

    # Task type factors
    type_FACTORS = {
        TaskType.QUERY: 0.5,          # query type for fast response
        TaskType.COMPUTATION: 3.0,    # Computation type needs more time
        TaskType.INTERACTIVE: 2.0,    # Interactive type waits for user
        TaskType.BATCH: 5.0,          # Batch type allows longest time
    }

    # Interaction level factors
    intERACTION_FACTORS = {
        Interactionlevel.notttne: 1.0,    # No interaction
        Interactionlevel.LOW: 1.2,     # Low interaction
        Interactionlevel.MEDIUM: 1.5,  # Medium interaction
        Interactionlevel.HIGH: 2.0,    # High interaction, needs to wait for user input
    }

    @classmethod
    def calculate(
        cls,
        task_type: TaskType = TaskType.QUERY,
        priority: TaskPriority = TaskPriority.NORMAL,
        interaction_level: Interactionlevel = Interactionlevel.notttne,
        base_timeout: float = None,
    ) -> float:
        """
        Calculate timeout

        Args:
            task_type: Task type
            priority: Task priority
            interaction_level: Interaction level
            base_timeout: Custom base timeout

        Returns:
            Timeout (seconds)
        """
        base = base_timeout or cls.BasE_timeout

        priority_factor = cls.PRIORITY_FACTORS.get(priority, 1.0)
        type_factor = cls.type_FACTORS.get(task_type, 1.0)
        interaction_factor = cls.intERACTION_FACTORS.get(interaction_level, 1.0)

        timeout = base * priority_factor * type_factor * interaction_factor

        # Minimum timeout 10 seconds, maximum timeout 300 seconds (5 minutes)
        return max(10.0, min(timeout, 300.0))

    @classmethod
    def calculate_for_task(cls, task_data: dict) -> float:
        """
        Calculate timeout based on task data

        Args:
            task_data: Task data dict, may contain type, priority, interaction_level

        Returns:
            Timeout (seconds)
        """
        # Extract parameters from task data
        type_str = task_data.get("type", TaskType.QUERY.value)
        priority_value = task_data.get("priority", TaskPriority.NORMAL.value)
        interaction_str = task_data.get("interaction_level", Interactionlevel.notttne.value)

        # Convert to enums
        try:
            task_type = TaskType(type_str)
        except Valueerror:
            task_type = TaskType.QUERY

        try:
            priority = TaskPriority(priority_value)
        except Valueerror:
            priority = TaskPriority.NORMAL

        try:
            interaction_level = Interactionlevel(interaction_str)
        except Valueerror:
            interaction_level = Interactionlevel.notttne

        return cls.calculate(task_type, priority, interaction_level)
