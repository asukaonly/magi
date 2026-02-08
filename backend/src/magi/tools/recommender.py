"""
工具推荐引擎

基于场景和意图智能推荐合适的工具
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import re

from .schema import Tool, ToolSchema, ToolParameter


logger = logging.getLogger(__name__)


class ScenarioType(str, Enum):
    """场景类型"""
    FILE_OPERATION = "file_operation"
    SYSTEM_COMMAND = "system_command"
    DATA_ANALYSIS = "data_analysis"
    NETWORK = "network"
    DATABASE = "database"
    TEXT_PROCESSING = "text_processing"
    UNKNOWN = "unknown"


class ToolRecommender:
    """
    工具推荐引擎

    根据用户意图和场景推荐合适的工具
    """

    def __init__(self, tool_registry):
        """
        初始化推荐引擎

        Args:
            tool_registry: 工具注册表实例
        """
        self.registry = tool_registry

        # 场景关键词映射
        self.scenario_keywords = {
            ScenarioType.FILE_OPERATION: [
                "文件", "file", "读取", "read", "写入", "write", "保存", "save",
                "删除", "delete", "列表", "list", "目录", "directory", "folder"
            ],
            ScenarioType.SYSTEM_COMMAND: [
                "命令", "command", "执行", "execute", "shell", "bash", "终端",
                "terminal", "运行", "run", "脚本", "script"
            ],
            ScenarioType.DATA_ANALYSIS: [
                "分析", "analyze", "统计", "statistics", "计算", "calculate",
                "数据", "data", "处理", "process"
            ],
            ScenarioType.NETWORK: [
                "网络", "network", "请求", "request", "http", "api", "下载",
                "download", "上传", "upload", "url", "访问", "fetch"
            ],
            ScenarioType.DATABASE: [
                "数据库", "database", "查询", "query", "sql", "存储", "store",
                "插入", "insert", "更新", "update"
            ],
            ScenarioType.TEXT_PROCESSING: [
                "文本", "text", "字符串", "string", "替换", "replace", "匹配",
                "match", "搜索", "search", "解析", "parse"
            ],
        }

        # 工具能力映射
        self.tool_capabilities = {
            "file_read": ["读取文件", "查看文件内容", "文件读取", "read file"],
            "file_write": ["写入文件", "保存文件", "创建文件", "write file", "save file"],
            "file_list": ["列出文件", "查看目录", "文件列表", "list files"],
            "bash": ["执行命令", "运行脚本", "shell命令", "execute command"],
        }

    def classify_scenario(self, intent: str) -> ScenarioType:
        """
        场景分类

        Args:
            intent: 用户意图描述

        Returns:
            场景类型
        """
        intent_lower = intent.lower()

        # 计算每个场景的匹配分数
        scores = {}
        for scenario, keywords in self.scenario_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword.lower() in intent_lower:
                    score += 1
            if score > 0:
                scores[scenario] = score

        if not scores:
            return ScenarioType.UNKNOWN

        # 返回分数最高的场景
        return max(scores.items(), key=lambda x: x[1])[0]

    def extract_intent_keywords(self, intent: str) -> List[str]:
        """
        提取意图关键词

        Args:
            intent: 用户意图描述

        Returns:
            关键词列表
        """
        # 简单的关键词提取（可以使用更复杂的NLP方法）
        keywords = []

        # 移除标点符号
        intent_clean = re.sub(r'[^\w\s]', ' ', intent)

        # 分词
        words = intent_clean.split()

        # 过滤停用词
        stopwords = {"的", "是", "在", "和", "与", "或", "the", "is", "at", "which", "on"}
        keywords = [w for w in words if len(w) > 1 and w not in stopwords]

        return keywords

    def match_capabilities(
        self,
        intent: str,
        scenario: ScenarioType
    ) -> List[Tuple[str, float]]:
        """
        能力匹配

        Args:
            intent: 用户意图
            scenario: 场景类型

        Returns:
            [(tool_name, score), ...] 按分数排序
        """
        intent_lower = intent.lower()
        scores = []

        tools = self.registry.list_tools()

        for tool_name in tools:
            tool = self.registry.get_tool(tool_name)
            if not tool:
                continue

            schema = tool.get_schema()
            score = 0.0

            # 1. 检查工具类别是否匹配场景
            category_match = 0
            if scenario == ScenarioType.FILE_OPERATION and schema.category == "file":
                category_match = 0.3
            elif scenario == ScenarioType.SYSTEM_COMMAND and schema.category == "system":
                category_match = 0.3

            score += category_match

            # 2. 检查标签匹配
            tags = schema.tags or []
            for tag in tags:
                if tag.lower() in intent_lower:
                    score += 0.2

            # 3. 检查描述匹配
            description = schema.description.lower()
            keywords = self.extract_intent_keywords(intent)
            for keyword in keywords:
                if keyword.lower() in description:
                    score += 0.1

            # 4. 检查工具能力映射
            if tool_name in self.tool_capabilities:
                for capability in self.tool_capabilities[tool_name]:
                    if capability.lower() in intent_lower:
                        score += 0.3
                        break

            if score > 0:
                scores.append((tool_name, score))

        # 按分数降序排序
        scores.sort(key=lambda x: x[1], reverse=True)

        return scores

    def evaluate_tool(
        self,
        tool_name: str,
        context: "ToolExecutionContext"
    ) -> Tuple[bool, Optional[str]]:
        """
        工具评估

        评估工具是否适合在当前上下文中使用

        Args:
            tool_name: 工具名称
            context: 执行上下文

        Returns:
            (is_suitable, reason)
        """
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return False, f"Tool {tool_name} not found"

        schema = tool.get_schema()

        # 检查是否危险操作
        if schema.dangerous and "dangerous_tools" not in context.permissions:
            return False, f"Tool requires dangerous_tools permission"

        # 检查认证要求
        if schema.requires_auth and "authenticated" not in context.permissions:
            return False, f"Tool requires authentication"

        # 检查角色权限
        if schema.allowed_roles:
            agent_role = context.env_vars.get("role", "guest")
            if agent_role not in schema.allowed_roles:
                return False, f"Tool requires one of roles: {schema.allowed_roles}"

        # 检查历史成功率
        stats = self.registry.get_stats(tool_name)
        if stats and tool_name in stats:
            success_rate = stats[tool_name]["success_rate"]
            if success_rate < 0.5 and stats[tool_name]["total_calls"] > 10:
                return False, f"Tool has low success rate: {success_rate:.2%}"

        return True, None

    def recommend_tools(
        self,
        intent: str,
        context: "ToolExecutionContext",
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        推荐工具

        完整的五步决策流程：
        1. 场景分类
        2. 意图关键词提取
        3. 能力匹配
        4. 工具评估
        5. 生成推荐结果

        Args:
            intent: 用户意图描述
            context: 执行上下文
            top_k: 返回前k个推荐

        Returns:
            推荐工具列表 [{"tool": name, "score": float, "reason": str}, ...]
        """
        logger.info(f"Recommending tools for intent: {intent}")

        # 1. 场景分类
        scenario = self.classify_scenario(intent)
        logger.info(f"Classified scenario: {scenario}")

        # 2. 提取关键词
        keywords = self.extract_intent_keywords(intent)
        logger.info(f"Extracted keywords: {keywords}")

        # 3. 能力匹配
        matched_tools = self.match_capabilities(intent, scenario)
        logger.info(f"Matched tools: {matched_tools}")

        # 4. 工具评估和筛选
        recommendations = []
        for tool_name, score in matched_tools[:top_k * 2]:  # 多取一些候选
            is_suitable, reason = self.evaluate_tool(tool_name, context)

            if is_suitable:
                tool = self.registry.get_tool(tool_name)
                schema = tool.get_schema()

                recommendations.append({
                    "tool": tool_name,
                    "score": score,
                    "reason": schema.description,
                    "category": schema.category,
                    "parameters": [p.dict() for p in schema.parameters],
                })
            else:
                logger.debug(f"Tool {tool_name} not suitable: {reason}")

            if len(recommendations) >= top_k:
                break

        logger.info(f"Final recommendations: {len(recommendations)} tools")

        return recommendations

    def suggest_parameters(
        self,
        tool_name: str,
        intent: str,
        context: "ToolExecutionContext"
    ) -> Dict[str, Any]:
        """
        参数生成

        根据意图为工具生成参数建议

        Args:
            tool_name: 工具名称
            intent: 用户意图
            context: 执行上下文

        Returns:
            参数建议字典
        """
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return {}

        schema = tool.get_schema()
        parameters = {}

        # 从intent中提取参数
        for param in schema.parameters:
            if param.default is not None:
                parameters[param.name] = param.default

            # 尝试从intent中提取文件路径
            if param.name == "path" or param.name == "file":
                # 查找可能的文件路径
                import re
                paths = re.findall(r'[\w/\\.]+\.\w+', intent)
                if paths:
                    parameters[param.name] = paths[0]
                elif "workspace" in context.env_vars:
                    parameters[param.name] = context.env_vars["workspace"]

            # 尝试从intent中提取命令
            elif param.name == "command":
                # 提取引号中的命令
                import re
                commands = re.findall(r'["\']([^"\']+)["\']', intent)
                if commands:
                    parameters[param.name] = commands[0]

        return parameters
