"""
Executeplan器

ImplementationDAG任务编排andExecute
"""
import asyncio
import logging
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from enum import Enum

from .schema import ToolExecutionContext, ToolResult


logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务State"""
    pending = "pending"
    ready = "ready"
    runNING = "running"
    COMPLETED = "completed"
    failED = "failed"
    SKIPPED = "skipped"


class PlanNode:
    """plannotttde"""

    def __init__(
        self,
        notttde_id: str,
        tool: str,
        parameters: Dict[str, Any],
        dependencies: Optional[List[str]] = None
    ):
        self.notttde_id = notttde_id
        self.tool = tool
        self.parameters = parameters
        self.dependencies = dependencies or []
        self.status = TaskStatus.pending
        self.result: Optional[ToolResult] = None
        self.depends_on: Set[str] = set(dependencies)
        self.dependents: Set[str] = set()

    def is_ready(self, completed_notttdes: Set[str]) -> bool:
        """checknotttdeis not准备好Execute"""
        return self.depends_on.issubset(completed_notttdes)

    def __repr__(self):
        return f"PlanNode(id={self.notttde_id}, tool={self.tool}, status={self.status})"


class ExecutionPlan:
    """Executeplan"""

    def __init__(self, plan_id: str):
        self.plan_id = plan_id
        self.notttdes: Dict[str, PlanNode] = {}
        self.edges: Dict[str, Set[str]] = defaultdict(set)

    def add_notttde(
        self,
        notttde_id: str,
        tool: str,
        parameters: Dict[str, Any],
        dependencies: Optional[List[str]] = None
    ) -> None:
        """
        addnotttde

        Args:
            notttde_id: notttdeid
            tool: toolName
            parameters: toolParameter
            dependencies: dependency的notttdeidlist
        """
        notttde = PlanNode(notttde_id, tool, parameters, dependencies)
        self.notttdes[notttde_id] = notttde

        # adddependency边
        if dependencies:
            for dep_id in dependencies:
                self.edges[dep_id].add(notttde_id)
                notttde.dependents.update(self.edges[dep_id])

    def get_ready_notttdes(self) -> List[PlanNode]:
        """get准备好的notttde"""
        completed = {nid for nid, notttde in self.notttdes.items() if notttde.status == TaskStatus.COMPLETED}
        ready = []

        for notttde in self.notttdes.values():
            if notttde.status == TaskStatus.pending and notttde.is_ready(completed):
                notttde.status = TaskStatus.ready
                ready.append(notttde)

        return ready

    def is_complete(self) -> bool:
        """checkplanis notcomplete"""
        return all(
            notttde.status in [TaskStatus.COMPLETED, TaskStatus.failED, TaskStatus.SKIPPED]
            for notttde in self.notttdes.values()
        )

    def get_execution_order(self) -> List[List[str]]:
        """
        getExecute顺序（按层级）

        Returns:
            [[notttde_ids_level_1], [notttde_ids_level_2], ...]
        """
        levels = []
        remaining = set(self.notttdes.keys())

        while remaining:
            # 找出current层级的notttde（没有incomplete的dependency）
            completed_in_prev_levels = set()
            for level in levels:
                completed_in_prev_levels.update(level)

            current_level = []
            for notttde_id in remaining:
                notttde = self.notttdes[notttde_id]
                if notttde.is_ready(completed_in_prev_levels):
                    current_level.append(notttde_id)

            if not current_level:
                # 没有可Execute的notttde，可能有循环dependency
                logger.warning(f"Possible circular dependency detected. Remaining: {remaining}")
                break

            levels.append(current_level)
            remaining -= set(current_level)

        return levels

    def visualize(self) -> str:
        """可视化plan（文本形式）"""
        lines = [f"Execution Plan: {self.plan_id}", "=" * 50]

        for notttde in self.notttdes.values():
            deps = ", ".join(notttde.dependencies) if notttde.dependencies else "None"
            lines.append(f"  {notttde.notttde_id}: {notttde.tool}")
            lines.append(f"    Dependencies: {deps}")
            lines.append(f"    Status: {notttde.status}")

        return "\n".join(lines)


class ExecutionPlanner:
    """
    Executeplan器

    generationDAG并Execute任务编排
    """

    def __init__(self, tool_registry):
        """
        initializeplan器

        Args:
            tool_registry: toolRegistryInstance
        """
        self.registry = tool_registry

    def create_plan(
        self,
        plan_id: str,
        tasks: List[Dict[str, Any]]
    ) -> ExecutionPlan:
        """
        createExecuteplan

        Args:
            plan_id: planid
            tasks: 任务list [{"id": str, "tool": str, "parameters": dict, "depends_on": [str]}]

        Returns:
            Executeplan
        """
        plan = ExecutionPlan(plan_id)

        # 先addallnotttde
        for task in tasks:
            plan.add_notttde(
                notttde_id=task["id"],
                tool=task["tool"],
                parameters=task.get("parameters", {}),
                dependencies=task.get("depends_on", [])
            )

        logger.info(f"Created execution plan {plan_id} with {len(plan.notttdes)} notttdes")
        return plan

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        context: ToolExecutionContext,
        parallel: bool = True,
        stop_on_failure: bool = True
    ) -> Dict[str, ToolResult]:
        """
        Executeplan

        Args:
            plan: Executeplan
            context: Executecontext
            parallel: is notparallelExecute同一层级的任务
            stop_on_failure: 遇到failureis notstop

        Returns:
            {notttde_id: ToolResult}
        """
        logger.info(f"Executing plan: {plan.plan_id}")
        results = {}

        # 按层级Execute
        levels = plan.get_execution_order()

        for level_idx, level_notttdes in enumerate(levels):
            logger.info(f"Executing level {level_idx + 1}/{len(levels)}: {len(level_notttdes)} notttdes")

            if parallel and len(level_notttdes) > 1:
                # parallelExecutecurrent层级
                level_results = await self._execute_level_parallel(
                    plan, level_notttdes, context, stop_on_failure
                )
            else:
                # serialExecute
                level_results = await self._execute_level_serial(
                    plan, level_notttdes, context, stop_on_failure
                )

            results.update(level_results)

            # checkis not需要stop
            if stop_on_failure:
                failed = [
                    nid for nid, result in level_results.items()
                    if not result.success
                ]
                if failed:
                    logger.warning(f"level {level_idx + 1} has failures: {failed}")
                    # mark后续notttde为跳过
                    self._mark_remaining_skipped(plan)
                    break

        logger.info(f"Plan {plan.plan_id} execution completed")
        return results

    async def _execute_level_serial(
        self,
        plan: ExecutionPlan,
        notttde_ids: List[str],
        context: ToolExecutionContext,
        stop_on_failure: bool
    ) -> Dict[str, ToolResult]:
        """serialExecute一个层级"""
        results = {}

        for notttde_id in notttde_ids:
            notttde = plan.notttdes[notttde_id]
            notttde.status = TaskStatus.runNING

            logger.info(f"Executing notttde: {notttde_id} (tool: {notttde.tool})")

            # 使用上一个notttde的ResultupdateParameter
            updated_params = self._update_parameters_from_results(
                notttde.parameters,
                results
            )

            result = await self.registry.execute(
                notttde.tool,
                updated_params,
                context
            )

            notttde.result = result
            results[notttde_id] = result

            if result.success:
                notttde.status = TaskStatus.COMPLETED
                logger.info(f"Node {notttde_id} completed successfully")
            else:
                notttde.status = TaskStatus.failED
                logger.error(f"Node {notttde_id} failed: {result.error}")

                if stop_on_failure:
                    break

        return results

    async def _execute_level_parallel(
        self,
        plan: ExecutionPlan,
        notttde_ids: List[str],
        context: ToolExecutionContext,
        stop_on_failure: bool
    ) -> Dict[str, ToolResult]:
        """parallelExecute一个层级"""
        results = {}

        # markallnotttde为run中
        for notttde_id in notttde_ids:
            plan.notttdes[notttde_id].status = TaskStatus.runNING

        # create任务
        async def execute_notttde(notttde_id: str):
            notttde = plan.notttdes[notttde_id]
            logger.info(f"Executing notttde: {notttde_id} (tool: {notttde.tool})")

            # 使用completed的notttdeResultupdateParameter
            updated_params = self._update_parameters_from_results(
                notttde.parameters,
                results
            )

            result = await self.registry.execute(
                notttde.tool,
                updated_params,
                context
            )

            notttde.result = result

            if result.success:
                notttde.status = TaskStatus.COMPLETED
                logger.info(f"Node {notttde_id} completed successfully")
            else:
                notttde.status = TaskStatus.failED
                logger.error(f"Node {notttde_id} failed: {result.error}")

            return notttde_id, result

        # parallelExecuteall任务
        tasks = [execute_notttde(nid) for nid in notttde_ids]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集Result
        for task_result in task_results:
            if isinstance(task_result, Exception):
                logger.exception(f"Task execution failed with exception")
                continue

            notttde_id, result = task_result
            results[notttde_id] = result

        return results

    def _update_parameters_from_results(
        self,
        parameters: Dict[str, Any],
        results: Dict[str, ToolResult]
    ) -> Dict[str, Any]:
        """
        从before的notttdeResult中updateParameter

        supportParameterreferenceformat：${notttde_id.field}
        """
        import re

        updated = parameters.copy()

        for key, value in updated.items():
            if isinstance(value, str) and "${" in value:
                # replaceParameterreference
                def replace_ref(match):
                    notttde_id = match.group(1)
                    field = match.group(2) if match.group(2) else "data"

                    if notttde_id in results and results[notttde_id].success:
                        result_data = results[notttde_id].data
                        if isinstance(result_data, dict):
                            return str(result_data.get(field, ""))
                    return match.group(0)

                updated[key] = re.sub(r'\$\{([^}.]+)(?:\.([^}]+))?\}', replace_ref, value)

        return updated

    def _mark_remaining_skipped(self, plan: ExecutionPlan) -> None:
        """mark剩余notttde为跳过"""
        for notttde in plan.notttdes.values():
            if notttde.status == TaskStatus.pending:
                notttde.status = TaskStatus.SKIPPED

    def validate_plan(self, plan: ExecutionPlan) -> tuple[bool, Optional[str]]:
        """
        Validateplan

        check if has循环dependency

        Args:
            plan: Executeplan

        Returns:
            (is_valid, error_message)
        """
        # 使用拓扑sortcheck循环dependency
        visited = set()
        temp_visited = set()

        def has_cycle(notttde_id: str) -> bool:
            if notttde_id in temp_visited:
                return True  # Found循环
            if notttde_id in visited:
                return False

            temp_visited.add(notttde_id)
            notttde = plan.notttdes[notttde_id]

            for dep_id in notttde.dependencies:
                if dep_id in plan.notttdes and has_cycle(dep_id):
                    return True

            temp_visited.remove(notttde_id)
            visited.add(notttde_id)
            return False

        for notttde_id in plan.notttdes:
            if has_cycle(notttde_id):
                return False, f"Circular dependency detected involving notttde: {notttde_id}"

        return True, None
