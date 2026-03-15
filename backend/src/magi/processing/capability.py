"""
Capability extraction and verification mechanism
"""
import asyncio
import hashlib
from typing import Dict, Any, List, Optional
from .base import Capability, TaskComplexity


class CapabilityExtractor:
    """
    Capability Extractor

    Extracts capabilities from successful experiences.
    """

    def __init__(self, llm_adapter=None):
        """
        Initialize the Capability Extractor.

        Args:
            llm_adapter: LLM adapter (for intelligent analysis)
        """
        self.llm_adapter = llm_adapter

        # Success case cache (task description -> execution count)
        self._success_cases: Dict[str, List[Dict]] = {}

        # Extraction threshold
        self.extraction_threshold = 3  # Trigger extraction after 3 successes

    async def record_success(self, task: Dict[str, Any], execution: Dict[str, Any]):
        """
        Record a success case.

        Args:
            task: Task description
            execution: Execution process
        """
        # Generate task fingerprint
        fingerprint = self._generate_fingerprint(task)

        if fingerprint not in self._success_cases:
            self._success_cases[fingerprint] = []

        self._success_cases[fingerprint].append({
            "task": task,
            "execution": execution,
        })

    async def should_extract(self, task: Dict[str, Any]) -> bool:
        """
        Determine whether a capability should be extracted.

        Args:
            task: Task description

        Returns:
            Whether extraction should proceed
        """
        fingerprint = self._generate_fingerprint(task)
        cases = self._success_cases.get(fingerprint, [])
        return len(cases) >= self.extraction_threshold

    async def extract_capability(
        self,
        task: Dict[str, Any],
        memory_store=None
    ) -> Optional[Capability]:
        """
        Extract a capability.

        Args:
            task: Task description
            memory_store: Memory store (for persisting capabilities)

        Returns:
            Extracted capability or None
        """
        fingerprint = self._generate_fingerprint(task)
        cases = self._success_cases.get(fingerprint, [])

        if not cases:
            return None

        # Analyze success cases
        capability = await self._analyze_cases(cases)

        if capability and memory_store:
            # Store in L5 layer
            await memory_store.store_capability(capability)

        return capability

    async def _analyze_cases(self, cases: List[Dict]) -> Optional[Capability]:
        """
        Analyze success cases and generate a capability definition.

        Args:
            cases: List of success cases

        Returns:
            Capability definition or None
        """
        if not cases:
            return None

        # Simplified: extract from the first case
        first_case = cases[0]
        task = first_case["task"]
        execution = first_case["execution"]

        # Generate capability name (simplified)
        name = self._generate_capability_name(task)

        # Extract trigger pattern
        trigger_pattern = task.get("description", task.get("type", ""))

        # Extract required tools
        required_tools = task.get("tools", [])

        # Extract execution steps
        execution_steps = execution.get("steps", [])

        # Generate description
        description = f"Capability for handling {name} tasks"

        return Capability(
            name=name,
            description=description,
            trigger_pattern=trigger_pattern,
            required_tools=required_tools,
            execution_steps=execution_steps,
            success_rate=1.0,  # Initial success rate is 100%
            usage_count=len(cases),
        )

    def _generate_fingerprint(self, task: Dict[str, Any]) -> str:
        """Generate task fingerprint."""
        # Generate fingerprint based on task type and description
        task_type = task.get("type", "")
        description = task.get("description", "")
        content = f"{task_type}:{description}"
        return hashlib.md5(content.encode()).hexdigest()

    def _generate_capability_name(self, task: Dict[str, Any]) -> str:
        """Generate capability name."""
        task_type = task.get("type", "unknown")
        return f"handle_{task_type}"


class CapabilityVerifier:
    """
    Capability Verifier

    Verifies the validity of extracted capabilities.
    """

    def __init__(self):
        """Initialize the Capability Verifier."""
        self.verification_threshold = 0.8  # Verification threshold 80%
        self.elimination_threshold = 0.6  # Elimination threshold 60%
        self.max_failures = 5  # Maximum consecutive failure count

    async def verify(
        self,
        capability: Capability,
        test_tasks: List[Dict],
        executor=None
    ) -> bool:
        """
        Verify a capability.

        Args:
            capability: Capability to verify
            test_tasks: List of test tasks
            executor: Executor

        Returns:
            Whether verification passed
        """
        if not test_tasks:
            return True  # No test tasks, pass by default

        # Calculate success rate
        success_count = 0
        total_count = len(test_tasks)

        for task in test_tasks:
            try:
                # Execute task
                result = await self._execute_with_capability(
                    capability,
                    task,
                    executor
                )
                if result:
                    success_count += 1
            except Exception:
                pass

        success_rate = success_count / total_count
        capability.success_rate = success_rate
        capability.verified = success_rate >= self.verification_threshold

        return capability.verified

    async def should_eliminate(self, capability: Capability) -> bool:
        """
        Determine whether a capability should be eliminated.

        Args:
            capability: Capability

        Returns:
            Whether the capability should be eliminated
        """
        # Success rate too low
        if capability.success_rate < self.elimination_threshold:
            return True

        # TODO: Check consecutive failure count (requires additional tracking)
        return False

    async def _execute_with_capability(
        self,
        capability: Capability,
        task: Dict,
        executor=None
    ) -> bool:
        """Execute a task using a capability."""
        # Simplified: return True directly
        # Actual implementation needs to call the executor to run the task
        return True
