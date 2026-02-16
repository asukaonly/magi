"""
Self-processing Module - Core Implementation
"""
from typing import Dict, Any, Optional, List
from .base import (
    processingResult,
    processingContext,
    Complexitylevel,
)
from .complexity import ComplexityEvaluator
from .capability import CapabilityExtractor, CapabilityVerifier
from .failure_learning import FailureLearner
from .context import ContextManager
from .learning import ProgressiveLearning
from .human_in_loop import HumanInLoop
from .experience_replay import ExperienceReplay


class SelfprocessingModule:
    """
    Self-processing Module

    Responsibilities:
    - process perception input
    - Capability extraction and verification
    - Failure learning
    - Human-machine collaboration decisions
    - Complexity assessment
    - Progressive learning
    - Context-aware processing
    - Experience replay
    """

    def __init__(
        self,
        llm_adapter=None,
        memory_store=None,
        tool_registry=None,
    ):
        """
        initialize the self-processing module

        Args:
            llm_adapter: LLM adapter
            memory_store: Memory store
            tool_registry: Tool registry
        """
        self.llm_adapter = llm_adapter
        self.memory_store = memory_store
        self.tool_registry = tool_registry

        # Sub-modules
        self.complexity_evaluator = ComplexityEvaluator()
        self.capability_extractor = CapabilityExtractor(llm_adapter)
        self.capability_verifier = CapabilityVerifier()
        self.failure_learner = FailureLearner(llm_adapter)
        self.context_manager = ContextManager()
        self.progressive_learning = ProgressiveLearning()
        self.human_in_loop = HumanInLoop()
        self.experience_replay = ExperienceReplay()

    async def process(self, perception: Dict[str, Any]) -> processingResult:
        """
        process perception input

        Args:
            perception: Perception data

        Returns:
            processingResult: processing result
        """
        # 1. Collect context
        context = await self.context_manager.collect()

        # 2. Evaluate task complexity
        complexity = self.complexity_evaluator.evaluate(perception)

        # 3. Check if human help is needed
        needs_help = await self._should_request_help(complexity)

        if needs_help:
            # Request human help
            result = await self.human_in_loop.request_help(
                perception,
                complexity,
                context,
            )
            return result

        # 4. Find existing capability
        capability = await self._find_capability(perception)

        if capability:
            # Use existing capability
            action = await self._execute_with_capability(
                capability,
                perception
            )
        else:
            # Generate new action
            action = await self._generate_action(perception, context)

        # 5. Return processing result
        return processingResult(
            action=action,
            needs_human_help=False,
            complexity=complexity,
            metadata={"context": context},
        )

    async def record_execution(
        self,
        perception: Dict,
        action: Dict,
        result: Any,
        success: bool
    ):
        """
        Record execution result (for learning)

        Args:
            perception: Perception
            action: Action
            result: Result
            success: Whether successful
        """
        # Record interaction
        self.progressive_learning.record_interaction()

        # Record experience
        await self.experience_replay.record_experience(
            perception,
            action,
            result,
            success
        )

        if success:
            # Record successful case
            await self.capability_extractor.record_success(
                perception,
                {"action": action, "result": result}
            )

            # Check if capability should be extracted
            if await self.capability_extractor.should_extract(perception):
                await self.capability_extractor.extract_capability(
                    perception,
                    self.memory_store
                )
        else:
            # Record failed case
            execution_steps = [{"action": action}]
            await self.failure_learner.record_failure(
                perception,
                result,  # Assume result is an Exception
                execution_steps
            )

        # Update context
        await self.context_manager.update_after_task(perception, result)

    async def _should_request_help(
        self,
        complexity: 'TaskComplexity'
    ) -> bool:
        """
        Determine whether to request human help

        Args:
            complexity: Task complexity

        Returns:
            Whether help is needed
        """
        # 1. Based on progressive learning
        if await self.progressive_learning.should_request_help(
            complexity.level
        ):
            return True

        # 2. Based on failure learning
        task = {"type": "task"}  # Simplified
        if await self.failure_learner.should_request_help(task):
            return True

        # 3. CRITICAL level must have human
        if complexity.level == Complexitylevel.CRITICAL:
            return True

        return False

    async def _find_capability(
        self,
        task: Dict
    ) -> Optional['Capability']:
        """
        Find existing capability

        Args:
            task: Task description

        Returns:
            Capability or None
        """
        if not self.memory_store:
            return None

        # query capability from L5 layer
        capability = await self.memory_store.find_capability(task)
        return capability

    async def _execute_with_capability(
        self,
        capability: 'Capability',
        task: Dict
    ) -> Dict:
        """
        Execute task using capability

        Args:
            capability: Capability
            task: Task

        Returns:
            Action
        """
        # Simplified version: return execution steps from capability
        # Actual implementation needs to call tools for execution
        return {
            "type": "use_capability",
            "capability": capability.name,
            "steps": capability.execution_steps,
        }

    async def _generate_action(
        self,
        perception: Dict,
        context: processingContext
    ) -> Dict:
        """
        Generate new action

        Args:
            perception: Perception
            context: Context

        Returns:
            Action
        """
        # Simplified version: return basic action
        # Actual implementation needs to use LLM to generate action
        return {
            "type": "respond",
            "content": f"Received: {perception.get('data', {})}",
        }
