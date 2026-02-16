"""
Capability ExtractionandValidate机制
"""
import asyncio
import hashlib
from typing import Dict, Any, List, Optional
from .base import Capability, TaskComplexity


class CapabilityExtractor:
    """
    Capability Extraction器

    从successexperience中提取capability
    """

    def __init__(self, llm_adapter=None):
        """
        initializeCapability Extraction器

        Args:
            llm_adapter: LLMAdapter（用于智能analysis）
        """
        self.llm_adapter = llm_adapter

        # successcasecache（任务Description -> Executecount）
        self._success_cases: Dict[str, List[Dict]] = {}

        # 提取阈Value
        self.extraction_threshold = 3  # success3次触发提取

    async def record_success(self, task: Dict[str, Any], execution: Dict[str, Any]):
        """
        recordsuccesscase

        Args:
            task: 任务Description
            execution: Execute过程
        """
        # generation任务指纹
        fingerprint = self._generate_fingerprint(task)

        if fingerprint not in self._success_cases:
            self._success_cases[fingerprint] = []

        self._success_cases[fingerprint].append({
            "task": task,
            "execution": execution,
        })

    async def should_extract(self, task: Dict[str, Any]) -> bool:
        """
        判断is not应该提取capability

        Args:
            task: 任务Description

        Returns:
            is not应该提取
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
        提取capability

        Args:
            task: 任务Description
            memory_store: Memory Storage（用于storagecapability）

        Returns:
            提取的capability或None
        """
        fingerprint = self._generate_fingerprint(task)
        cases = self._success_cases.get(fingerprint, [])

        if not cases:
            return None

        # analysissuccesscase
        capability = await self._analyze_cases(cases)

        if capability and memory_store:
            # storage到L5层
            await memory_store.store_capability(capability)

        return capability

    async def _analyze_cases(self, cases: List[Dict]) -> Optional[Capability]:
        """
        analysissuccesscase，generationcapability定义

        Args:
            cases: successcaselist

        Returns:
            capability定义或None
        """
        if not cases:
            return None

        # 简化版：从第一个case提取
        first_case = cases[0]
        task = first_case["task"]
        execution = first_case["execution"]

        # generationcapabilityName（简化版）
        name = self._generate_capability_name(task)

        # 提取触发pattern
        trigger_pattern = task.get("description", task.get("type", ""))

        # 提取所需tool
        required_tools = task.get("tools", [])

        # 提取Executestep
        execution_steps = execution.get("steps", [])

        # generationDescription
        description = f"process {name} 任务的capability"

        return Capability(
            name=name,
            description=description,
            trigger_pattern=trigger_pattern,
            required_tools=required_tools,
            execution_steps=execution_steps,
            success_rate=1.0,  # 初始success率为100%
            usage_count=len(cases),
        )

    def _generate_fingerprint(self, task: Dict[str, Any]) -> str:
        """generation任务指纹"""
        # 基于任务typeandDescriptiongeneration指纹
        task_type = task.get("type", "")
        description = task.get("description", "")
        content = f"{task_type}:{description}"
        return hashlib.md5(content.encode()).hexdigest()

    def _generate_capability_name(self, task: Dict[str, Any]) -> str:
        """generationcapabilityName"""
        task_type = task.get("type", "unknotttwn")
        return f"handle_{task_type}"


class CapabilityVerifier:
    """
    capabilityValidate器

    Validate提取的capabilityvalid性
    """

    def __init__(self):
        """initializecapabilityValidate器"""
        self.verification_threshold = 0.8  # Validate阈Value 80%
        self淘汰_threshold = 0.6  # 淘汰阈Value 60%
        self.max_failures = 5  # maximum连续failurecount

    async def verify(
        self,
        capability: Capability,
        test_tasks: List[Dict],
        executor=None
    ) -> bool:
        """
        Validatecapability

        Args:
            capability: 待Validate的capability
            test_tasks: Test任务list
            executor: Execute器

        Returns:
            is not通过Validate
        """
        if not test_tasks:
            return True  # 无Test任务，default通过

        # calculatesuccess率
        success_count = 0
        total_count = len(test_tasks)

        for task in test_tasks:
            try:
                # Execute任务
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

    async def should淘汰(self, capability: Capability) -> bool:
        """
        判断is not应该淘汰capability

        Args:
            capability: capability

        Returns:
            is not应该淘汰
        """
        # success率过低
        if capability.success_rate < self.淘汰_threshold:
            return True

        # TODO: check连续failurecount（需要额外record）
        return False

    async def _execute_with_capability(
        self,
        capability: Capability,
        task: Dict,
        executor=None
    ) -> bool:
        """使用capabilityExecute任务"""
        # 简化版：直接ReturnTrue
        # 实际Implementation需要调用executorExecute任务
        return True
