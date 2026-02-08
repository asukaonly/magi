"""
执行计划器

实现DAG任务编排和执行
"""
import asyncio
import logging
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from enum import Enum

from .schema import ToolExecutionContext, ToolResult


logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanNode:
    """计划节点"""

    def __init__(
        self,
        node_id: str,
        tool: str,
        parameters: Dict[str, Any],
        dependencies: Optional[List[str]] = None
    ):
        self.node_id = node_id
        self.tool = tool
        self.parameters = parameters
        self.dependencies = dependencies or []
        self.status = TaskStatus.PENDING
        self.result: Optional[ToolResult] = None
        self.depends_on: Set[str] = set(dependencies)
        self.dependents: Set[str] = set()

    def is_ready(self, completed_nodes: Set[str]) -> bool:
        """检查节点是否准备好执行"""
        return self.depends_on.issubset(completed_nodes)

    def __repr__(self):
        return f"PlanNode(id={self.node_id}, tool={self.tool}, status={self.status})"


class ExecutionPlan:
    """执行计划"""

    def __init__(self, plan_id: str):
        self.plan_id = plan_id
        self.nodes: Dict[str, PlanNode] = {}
        self.edges: Dict[str, Set[str]] = defaultdict(set)

    def add_node(
        self,
        node_id: str,
        tool: str,
        parameters: Dict[str, Any],
        dependencies: Optional[List[str]] = None
    ) -> None:
        """
        添加节点

        Args:
            node_id: 节点ID
            tool: 工具名称
            parameters: 工具参数
            dependencies: 依赖的节点ID列表
        """
        node = PlanNode(node_id, tool, parameters, dependencies)
        self.nodes[node_id] = node

        # 添加依赖边
        if dependencies:
            for dep_id in dependencies:
                self.edges[dep_id].add(node_id)
                node.dependents.update(self.edges[dep_id])

    def get_ready_nodes(self) -> List[PlanNode]:
        """获取准备好的节点"""
        completed = {nid for nid, node in self.nodes.items() if node.status == TaskStatus.COMPLETED}
        ready = []

        for node in self.nodes.values():
            if node.status == TaskStatus.PENDING and node.is_ready(completed):
                node.status = TaskStatus.READY
                ready.append(node)

        return ready

    def is_complete(self) -> bool:
        """检查计划是否完成"""
        return all(
            node.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED]
            for node in self.nodes.values()
        )

    def get_execution_order(self) -> List[List[str]]:
        """
        获取执行顺序（按层级）

        Returns:
            [[node_ids_level_1], [node_ids_level_2], ...]
        """
        levels = []
        remaining = set(self.nodes.keys())

        while remaining:
            # 找出当前层级的节点（没有未完成的依赖）
            completed_in_prev_levels = set()
            for level in levels:
                completed_in_prev_levels.update(level)

            current_level = []
            for node_id in remaining:
                node = self.nodes[node_id]
                if node.is_ready(completed_in_prev_levels):
                    current_level.append(node_id)

            if not current_level:
                # 没有可执行的节点，可能有循环依赖
                logger.warning(f"Possible circular dependency detected. Remaining: {remaining}")
                break

            levels.append(current_level)
            remaining -= set(current_level)

        return levels

    def visualize(self) -> str:
        """可视化计划（文本形式）"""
        lines = [f"Execution Plan: {self.plan_id}", "=" * 50]

        for node in self.nodes.values():
            deps = ", ".join(node.dependencies) if node.dependencies else "None"
            lines.append(f"  {node.node_id}: {node.tool}")
            lines.append(f"    Dependencies: {deps}")
            lines.append(f"    Status: {node.status}")

        return "\n".join(lines)


class ExecutionPlanner:
    """
    执行计划器

    生成DAG并执行任务编排
    """

    def __init__(self, tool_registry):
        """
        初始化计划器

        Args:
            tool_registry: 工具注册表实例
        """
        self.registry = tool_registry

    def create_plan(
        self,
        plan_id: str,
        tasks: List[Dict[str, Any]]
    ) -> ExecutionPlan:
        """
        创建执行计划

        Args:
            plan_id: 计划ID
            tasks: 任务列表 [{"id": str, "tool": str, "parameters": dict, "depends_on": [str]}]

        Returns:
            执行计划
        """
        plan = ExecutionPlan(plan_id)

        # 先添加所有节点
        for task in tasks:
            plan.add_node(
                node_id=task["id"],
                tool=task["tool"],
                parameters=task.get("parameters", {}),
                dependencies=task.get("depends_on", [])
            )

        logger.info(f"Created execution plan {plan_id} with {len(plan.nodes)} nodes")
        return plan

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        context: ToolExecutionContext,
        parallel: bool = True,
        stop_on_failure: bool = True
    ) -> Dict[str, ToolResult]:
        """
        执行计划

        Args:
            plan: 执行计划
            context: 执行上下文
            parallel: 是否并行执行同一层级的任务
            stop_on_failure: 遇到失败是否停止

        Returns:
            {node_id: ToolResult}
        """
        logger.info(f"Executing plan: {plan.plan_id}")
        results = {}

        # 按层级执行
        levels = plan.get_execution_order()

        for level_idx, level_nodes in enumerate(levels):
            logger.info(f"Executing level {level_idx + 1}/{len(levels)}: {len(level_nodes)} nodes")

            if parallel and len(level_nodes) > 1:
                # 并行执行当前层级
                level_results = await self._execute_level_parallel(
                    plan, level_nodes, context, stop_on_failure
                )
            else:
                # 串行执行
                level_results = await self._execute_level_serial(
                    plan, level_nodes, context, stop_on_failure
                )

            results.update(level_results)

            # 检查是否需要停止
            if stop_on_failure:
                failed = [
                    nid for nid, result in level_results.items()
                    if not result.success
                ]
                if failed:
                    logger.warning(f"Level {level_idx + 1} has failures: {failed}")
                    # 标记后续节点为跳过
                    self._mark_remaining_skipped(plan)
                    break

        logger.info(f"Plan {plan.plan_id} execution completed")
        return results

    async def _execute_level_serial(
        self,
        plan: ExecutionPlan,
        node_ids: List[str],
        context: ToolExecutionContext,
        stop_on_failure: bool
    ) -> Dict[str, ToolResult]:
        """串行执行一个层级"""
        results = {}

        for node_id in node_ids:
            node = plan.nodes[node_id]
            node.status = TaskStatus.RUNNING

            logger.info(f"Executing node: {node_id} (tool: {node.tool})")

            # 使用上一个节点的结果更新参数
            updated_params = self._update_parameters_from_results(
                node.parameters,
                results
            )

            result = await self.registry.execute(
                node.tool,
                updated_params,
                context
            )

            node.result = result
            results[node_id] = result

            if result.success:
                node.status = TaskStatus.COMPLETED
                logger.info(f"Node {node_id} completed successfully")
            else:
                node.status = TaskStatus.FAILED
                logger.error(f"Node {node_id} failed: {result.error}")

                if stop_on_failure:
                    break

        return results

    async def _execute_level_parallel(
        self,
        plan: ExecutionPlan,
        node_ids: List[str],
        context: ToolExecutionContext,
        stop_on_failure: bool
    ) -> Dict[str, ToolResult]:
        """并行执行一个层级"""
        results = {}

        # 标记所有节点为运行中
        for node_id in node_ids:
            plan.nodes[node_id].status = TaskStatus.RUNNING

        # 创建任务
        async def execute_node(node_id: str):
            node = plan.nodes[node_id]
            logger.info(f"Executing node: {node_id} (tool: {node.tool})")

            # 使用已完成的节点结果更新参数
            updated_params = self._update_parameters_from_results(
                node.parameters,
                results
            )

            result = await self.registry.execute(
                node.tool,
                updated_params,
                context
            )

            node.result = result

            if result.success:
                node.status = TaskStatus.COMPLETED
                logger.info(f"Node {node_id} completed successfully")
            else:
                node.status = TaskStatus.FAILED
                logger.error(f"Node {node_id} failed: {result.error}")

            return node_id, result

        # 并行执行所有任务
        tasks = [execute_node(nid) for nid in node_ids]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集结果
        for task_result in task_results:
            if isinstance(task_result, Exception):
                logger.exception(f"Task execution failed with exception")
                continue

            node_id, result = task_result
            results[node_id] = result

        return results

    def _update_parameters_from_results(
        self,
        parameters: Dict[str, Any],
        results: Dict[str, ToolResult]
    ) -> Dict[str, Any]:
        """
        从之前的节点结果中更新参数

        支持参数引用格式：${node_id.field}
        """
        import re

        updated = parameters.copy()

        for key, value in updated.items():
            if isinstance(value, str) and "${" in value:
                # 替换参数引用
                def replace_ref(match):
                    node_id = match.group(1)
                    field = match.group(2) if match.group(2) else "data"

                    if node_id in results and results[node_id].success:
                        result_data = results[node_id].data
                        if isinstance(result_data, dict):
                            return str(result_data.get(field, ""))
                    return match.group(0)

                updated[key] = re.sub(r'\$\{([^}.]+)(?:\.([^}]+))?\}', replace_ref, value)

        return updated

    def _mark_remaining_skipped(self, plan: ExecutionPlan) -> None:
        """标记剩余节点为跳过"""
        for node in plan.nodes.values():
            if node.status == TaskStatus.PENDING:
                node.status = TaskStatus.SKIPPED

    def validate_plan(self, plan: ExecutionPlan) -> tuple[bool, Optional[str]]:
        """
        验证计划

        检查是否有循环依赖

        Args:
            plan: 执行计划

        Returns:
            (is_valid, error_message)
        """
        # 使用拓扑排序检查循环依赖
        visited = set()
        temp_visited = set()

        def has_cycle(node_id: str) -> bool:
            if node_id in temp_visited:
                return True  # 找到循环
            if node_id in visited:
                return False

            temp_visited.add(node_id)
            node = plan.nodes[node_id]

            for dep_id in node.dependencies:
                if dep_id in plan.nodes and has_cycle(dep_id):
                    return True

            temp_visited.remove(node_id)
            visited.add(node_id)
            return False

        for node_id in plan.nodes:
            if has_cycle(node_id):
                return False, f"Circular dependency detected involving node: {node_id}"

        return True, None
