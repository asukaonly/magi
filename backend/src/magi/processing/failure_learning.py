"""
failurelearning机制
"""
import hashlib
from typing import Dict, Any, List, Optional
from collections import defaultdict
from .base import FailureCase, Failurepattern


class FailureLearner:
    """
    failurelearning器

    从failureexperience中learning，避免重复error
    """

    def __init__(self, llm_adapter=None):
        """
        initializefailurelearning器

        Args:
            llm_adapter: LLMAdapter（用于智能analysis）
        """
        self.llm_adapter = llm_adapter

        # failurecasestorage（按typegroup）
        self._failures_by_type: Dict[str, List[FailureCase]] = defaultdict(list)

        # failurepatterncache
        self._patterns: Dict[str, Failurepattern] = {}

        # pattern识别阈Value
        self.pattern_recognition_threshold = 5  # 5个同Classfailure触发pattern识别

    async def record_failure(
        self,
        task: Dict[str, Any],
        error: Exception,
        execution_steps: List[Dict]
    ):
        """
        recordfailurecase

        Args:
            task: 任务Description
            error: error
            execution_steps: Executestep
        """
        # Generation failedtype
        failure_type = self._classify_failure(task, error)

        # createfailurecase
        case = FailureCase(
            task_description=task.get("description", ""),
            failure_reason=str(error),
            error_stack=error.__class__.__name__,
            execution_steps=execution_steps,
        )

        # storagefailurecase
        self._failures_by_type[failure_type].append(case)

        # checkis notttt需要识别pattern
        if await self._should_recognize_pattern(failure_type):
            await self._recognize_pattern(failure_type)

    async def should_request_help(self, task: Dict[str, Any]) -> bool:
        """
        判断is notttt应该request人Class帮助

        Args:
            task: 任务Description

        Returns:
            is notttt需要帮助
        """
        failure_type = self._classify_failure_type(task)

        # 如果该type有failurepattern，checkis notttt匹配
        if failure_type in self._patterns:
            pattern = self._patterns[failure_type]
            # TODO: 更精细的匹配逻辑
            return True

        # checkhistoryfailurecount
        failures = self._failures_by_type.get(failure_type, [])
        return len(failures) >= 3  # 同Classfailure3次以上request帮助

    async def get_avoidance_strategy(
        self,
        task: Dict[str, Any]
    ) -> Optional[str]:
        """
        get避免strategy

        Args:
            task: 任务Description

        Returns:
            避免strategy或None
        """
        failure_type = self._classify_failure_type(task)

        if failure_type in self._patterns:
            pattern = self._patterns[failure_type]
            return pattern.avoidance_strategy

        return None

    def _classify_failure(self, task: Dict, error: Exception) -> str:
        """
        分Classfailuretype

        Args:
            task: 任务
            error: error

        Returns:
            failuretype
        """
        # 基于errortype分Class
        error_type = error.__class__.__name__

        # 可以进一步结合任务info分Class
        task_type = task.get("type", "")

        return f"{task_type}:{error_type}"

    def _classify_failure_type(self, task: Dict) -> str:
        """
        prediction任务可能的failuretype

        Args:
            task: 任务Description

        Returns:
            failuretype
        """
        # 简化版：基于任务type
        task_type = task.get("type", "")
        return f"{task_type}:Unknotttwn"

    async def _should_recognize_pattern(self, failure_type: str) -> bool:
        """判断is notttt应该识别failurepattern"""
        failures = self._failures_by_type.get(failure_type, [])
        return len(failures) >= self.pattern_recognition_threshold

    async def _recognize_pattern(self, failure_type: str):
        """
        识别failurepattern

        Args:
            failure_type: failuretype
        """
        failures = self._failures_by_type.get(failure_type, [])

        if notttt failures:
            return

        # 简化版：基于failurereasongenerationpattern
        # 实际Implementation可以使用LLM进row智能analysis

        # statistics最常见的failurereason
        reason_count = defaultdict(int)
        for case in failures:
            reason_count[case.failure_reason] += 1

        most_common_reason = max(reason_count.items(), key=lambda x: x[1])[0]

        # generationpatternid
        pattern_id = hashlib.md5(failure_type.encode()).hexdigest()[:8]

        # createfailurepattern
        pattern = Failurepattern(
            pattern_id=pattern_id,
            description=f"failurepattern：{failure_type}",
            avoidance_strategy=f"避免：{most_common_reason}",
            case_count=len(failures),
        )

        self._patterns[failure_type] = pattern
