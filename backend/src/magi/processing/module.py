"""
自处理模块 - 核心实现
"""
from typing import Dict, Any, Optional, List
from .base import (
    ProcessingResult,
    ProcessingContext,
    ComplexityLevel,
)
from .complexity import ComplexityEvaluator
from .capability import CapabilityExtractor, CapabilityVerifier
from .failure_learning import FailureLearner
from .context import ContextManager
from .learning import ProgressiveLearning
from .human_in_loop import HumanInLoop
from .experience_replay import ExperienceReplay


class SelfProcessingModule:
    """
    自处理模块

    职责：
    - 处理感知输入
    - 能力提取和验证
    - 失败学习
    - 人机协作决策
    - 复杂度评估
    - 渐进式学习
    - 上下文感知处理
    - 经验回放
    """

    def __init__(
        self,
        llm_adapter=None,
        memory_store=None,
        tool_registry=None,
    ):
        """
        初始化自处理模块

        Args:
            llm_adapter: LLM适配器
            memory_store: 记忆存储
            tool_registry: 工具注册表
        """
        self.llm_adapter = llm_adapter
        self.memory_store = memory_store
        self.tool_registry = tool_registry

        # 子模块
        self.complexity_evaluator = ComplexityEvaluator()
        self.capability_extractor = CapabilityExtractor(llm_adapter)
        self.capability_verifier = CapabilityVerifier()
        self.failure_learner = FailureLearner(llm_adapter)
        self.context_manager = ContextManager()
        self.progressive_learning = ProgressiveLearning()
        self.human_in_loop = HumanInLoop()
        self.experience_replay = ExperienceReplay()

    async def process(self, perception: Dict[str, Any]) -> ProcessingResult:
        """
        处理感知输入

        Args:
            perception: 感知数据

        Returns:
            ProcessingResult: 处理结果
        """
        # 1. 收集上下文
        context = await self.context_manager.collect()

        # 2. 评估任务复杂度
        complexity = self.complexity_evaluator.evaluate(perception)

        # 3. 检查是否需要人类帮助
        needs_help = await self._should_request_help(complexity)

        if needs_help:
            # 请求人类帮助
            result = await self.human_in_loop.request_help(
                perception,
                complexity,
                context,
            )
            return result

        # 4. 查找已有能力
        capability = await self._find_capability(perception)

        if capability:
            # 使用已有能力
            action = await self._execute_with_capability(
                capability,
                perception
            )
        else:
            # 生成新动作
            action = await self._generate_action(perception, context)

        # 5. 返回处理结果
        return ProcessingResult(
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
        记录执行结果（用于学习）

        Args:
            perception: 感知
            action: 动作
            result: 结果
            success: 是否成功
        """
        # 记录交互
        self.progressive_learning.record_interaction()

        # 记录经验
        await self.experience_replay.record_experience(
            perception,
            action,
            result,
            success
        )

        if success:
            # 记录成功案例
            await self.capability_extractor.record_success(
                perception,
                {"action": action, "result": result}
            )

            # 检查是否应该提取能力
            if await self.capability_extractor.should_extract(perception):
                await self.capability_extractor.extract_capability(
                    perception,
                    self.memory_store
                )
        else:
            # 记录失败案例
            execution_steps = [{"action": action}]
            await self.failure_learner.record_failure(
                perception,
                result,  # 假设result是Exception
                execution_steps
            )

        # 更新上下文
        await self.context_manager.update_after_task(perception, result)

    async def _should_request_help(
        self,
        complexity: 'TaskComplexity'
    ) -> bool:
        """
        判断是否应该请求人类帮助

        Args:
            complexity: 任务复杂度

        Returns:
            是否需要帮助
        """
        # 1. 基于渐进式学习判断
        if await self.progressive_learning.should_request_help(
            complexity.level
        ):
            return True

        # 2. 基于失败学习判断
        task = {"type": "task"}  # 简化
        if await self.failure_learner.should_request_help(task):
            return True

        # 3. CRITICAL级别必须人类
        if complexity.level == ComplexityLevel.CRITICAL:
            return True

        return False

    async def _find_capability(
        self,
        task: Dict
    ) -> Optional['Capability']:
        """
        查找已有能力

        Args:
            task: 任务描述

        Returns:
            能力或None
        """
        if not self.memory_store:
            return None

        # 从L5层查询能力
        capability = await self.memory_store.find_capability(task)
        return capability

    async def _execute_with_capability(
        self,
        capability: 'Capability',
        task: Dict
    ) -> Dict:
        """
        使用能力执行任务

        Args:
            capability: 能力
            task: 任务

        Returns:
            动作
        """
        # 简化版：返回能力中的执行步骤
        # 实际实现需要调用工具执行
        return {
            "type": "use_capability",
            "capability": capability.name,
            "steps": capability.execution_steps,
        }

    async def _generate_action(
        self,
        perception: Dict,
        context: ProcessingContext
    ) -> Dict:
        """
        生成新动作

        Args:
            perception: 感知
            context: 上下文

        Returns:
            动作
        """
        # 简化版：返回基本动作
        # 实际实现需要使用LLM生成动作
        return {
            "type": "respond",
            "content": f"收到: {perception.get('data', {})}",
        }
