"""
能力提取和验证机制
"""
import asyncio
import hashlib
from typing import Dict, Any, List, Optional
from .base import Capability, TaskComplexity


class CapabilityExtractor:
    """
    能力提取器

    从成功经验中提取能力
    """

    def __init__(self, llm_adapter=None):
        """
        初始化能力提取器

        Args:
            llm_adapter: LLM适配器（用于智能分析）
        """
        self.llm_adapter = llm_adapter

        # 成功案例缓存（任务描述 -> 执行次数）
        self._success_cases: Dict[str, List[Dict]] = {}

        # 提取阈值
        self.extraction_threshold = 3  # 成功3次触发提取

    async def record_success(self, task: Dict[str, Any], execution: Dict[str, Any]):
        """
        记录成功案例

        Args:
            task: 任务描述
            execution: 执行过程
        """
        # 生成任务指纹
        fingerprint = self._generate_fingerprint(task)

        if fingerprint not in self._success_cases:
            self._success_cases[fingerprint] = []

        self._success_cases[fingerprint].append({
            "task": task,
            "execution": execution,
        })

    async def should_extract(self, task: Dict[str, Any]) -> bool:
        """
        判断是否应该提取能力

        Args:
            task: 任务描述

        Returns:
            是否应该提取
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
        提取能力

        Args:
            task: 任务描述
            memory_store: 记忆存储（用于存储能力）

        Returns:
            提取的能力或None
        """
        fingerprint = self._generate_fingerprint(task)
        cases = self._success_cases.get(fingerprint, [])

        if not cases:
            return None

        # 分析成功案例
        capability = await self._analyze_cases(cases)

        if capability and memory_store:
            # 存储到L5层
            await memory_store.store_capability(capability)

        return capability

    async def _analyze_cases(self, cases: List[Dict]) -> Optional[Capability]:
        """
        分析成功案例，生成能力定义

        Args:
            cases: 成功案例列表

        Returns:
            能力定义或None
        """
        if not cases:
            return None

        # 简化版：从第一个案例提取
        first_case = cases[0]
        task = first_case["task"]
        execution = first_case["execution"]

        # 生成能力名称（简化版）
        name = self._generate_capability_name(task)

        # 提取触发模式
        trigger_pattern = task.get("description", task.get("type", ""))

        # 提取所需工具
        required_tools = task.get("tools", [])

        # 提取执行步骤
        execution_steps = execution.get("steps", [])

        # 生成描述
        description = f"处理 {name} 任务的能力"

        return Capability(
            name=name,
            description=description,
            trigger_pattern=trigger_pattern,
            required_tools=required_tools,
            execution_steps=execution_steps,
            success_rate=1.0,  # 初始成功率为100%
            usage_count=len(cases),
        )

    def _generate_fingerprint(self, task: Dict[str, Any]) -> str:
        """生成任务指纹"""
        # 基于任务类型和描述生成指纹
        task_type = task.get("type", "")
        description = task.get("description", "")
        content = f"{task_type}:{description}"
        return hashlib.md5(content.encode()).hexdigest()

    def _generate_capability_name(self, task: Dict[str, Any]) -> str:
        """生成能力名称"""
        task_type = task.get("type", "unknown")
        return f"handle_{task_type}"


class CapabilityVerifier:
    """
    能力验证器

    验证提取的能力有效性
    """

    def __init__(self):
        """初始化能力验证器"""
        self.verification_threshold = 0.8  # 验证阈值 80%
        self淘汰_threshold = 0.6  # 淘汰阈值 60%
        self.max_failures = 5  # 最大连续失败次数

    async def verify(
        self,
        capability: Capability,
        test_tasks: List[Dict],
        executor=None
    ) -> bool:
        """
        验证能力

        Args:
            capability: 待验证的能力
            test_tasks: 测试任务列表
            executor: 执行器

        Returns:
            是否通过验证
        """
        if not test_tasks:
            return True  # 无测试任务，默认通过

        # 计算成功率
        success_count = 0
        total_count = len(test_tasks)

        for task in test_tasks:
            try:
                # 执行任务
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
        判断是否应该淘汰能力

        Args:
            capability: 能力

        Returns:
            是否应该淘汰
        """
        # 成功率过低
        if capability.success_rate < self.淘汰_threshold:
            return True

        # TODO: 检查连续失败次数（需要额外记录）
        return False

    async def _execute_with_capability(
        self,
        capability: Capability,
        task: Dict,
        executor=None
    ) -> bool:
        """使用能力执行任务"""
        # 简化版：直接返回True
        # 实际实现需要调用executor执行任务
        return True
