"""
toolrecommended引擎

基于scenarioandintent智能recommended合适的tool
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import re

from .schema import Tool, ToolSchema, ToolParameter


logger = logging.getLogger(__name__)


class Scenariotype(str, Enum):
    """scenariotype"""
    FILE_OPERATION = "file_operation"
    system_COMMAND = "system_command"
    DATA_ANALYSIS = "data_analysis"
    network = "network"
    DATABasE = "database"
    TEXT_processING = "text_processing"
    UNKNOWN = "unknown"


class ToolRecommender:
    """
    toolrecommended引擎

    根据userintentandscenariorecommended合适的tool
    """

    def __init__(self, tool_registry):
        """
        initializerecommended引擎

        Args:
            tool_registry: toolRegistryInstance
        """
        self.registry = tool_registry

        # scenario关key词mapping
        self.scenario_keywords = {
            Scenariotype.FILE_OPERATION: [
                "file", "file", "读取", "read", "写入", "write", "save", "save",
                "delete", "delete", "list", "list", "directory", "directory", "folder"
            ],
            Scenariotype.system_COMMAND: [
                "command", "command", "Execute", "execute", "shell", "bash", "终端",
                "terminal", "run", "run", "script", "script"
            ],
            Scenariotype.DATA_ANALYSIS: [
                "analysis", "analyze", "statistics", "statistics", "calculate", "calculate",
                "data", "data", "process", "process"
            ],
            Scenariotype.network: [
                "network", "network", "request", "request", "http", "api", "下载",
                "download", "上传", "upload", "url", "访问", "fetch"
            ],
            Scenariotype.DATABasE: [
                "database", "database", "query", "query", "sql", "storage", "store",
                "insert", "insert", "update", "update"
            ],
            Scenariotype.TEXT_processING: [
                "文本", "text", "string", "string", "replace", "replace", "匹配",
                "match", "search", "search", "parse", "parse"
            ],
        }

        # toolcapabilitymapping
        self.tool_capabilities = {
            "file_read": ["读取file", "查看fileContent", "file读取", "read file"],
            "file_write": ["写入file", "savefile", "createfile", "write file", "save file"],
            "file_list": ["column出file", "查看directory", "filelist", "list files"],
            "bash": ["Executecommand", "runscript", "shellcommand", "execute command"],
        }

    def classify_scenario(self, intent: str) -> Scenariotype:
        """
        scenario分Class

        Args:
            intent: userintentDescription

        Returns:
            scenariotype
        """
        intent_lower = intent.lower()

        # calculate每个scenario的匹配score
        scores = {}
        for scenario, keywords in self.scenario_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword.lower() in intent_lower:
                    score += 1
            if score > 0:
                scores[scenario] = score

        if not scores:
            return Scenariotype.UNKNOWN

        # Returnscore最高的scenario
        return max(scores.items(), key=lambda x: x[1])[0]

    def extract_intent_keywords(self, intent: str) -> List[str]:
        """
        提取intent关key词

        Args:
            intent: userintentDescription

        Returns:
            关key词list
        """
        # simple的关key词提取（可以使用更complex的NLPMethod）
        keywords = []

        # Remove标点符号
        intent_clean = re.sub(r'[^\w\s]', ' ', intent)

        # 分词
        words = intent_clean.split()

        # filter停用词
        stopwords = {"的", "is", "在", "and", "与", "或", "the", "is", "at", "which", "on"}
        keywords = [w for w in words if len(w) > 1 and w not in stopwords]

        return keywords

    def match_capabilities(
        self,
        intent: str,
        scenario: Scenariotype
    ) -> List[Tuple[str, float]]:
        """
        capability匹配

        Args:
            intent: userintent
            scenario: scenariotype

        Returns:
            [(tool_name, score), ...] 按scoresort
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

            # 1. checktoolClass别is not匹配scenario
            category_match = 0
            if scenario == Scenariotype.FILE_OPERATION and schema.category == "file":
                category_match = 0.3
            elif scenario == Scenariotype.system_COMMAND and schema.category == "system":
                category_match = 0.3

            score += category_match

            # 2. checklabel匹配
            tags = schema.tags or []
            for tag in tags:
                if tag.lower() in intent_lower:
                    score += 0.2

            # 3. checkDescription匹配
            description = schema.description.lower()
            keywords = self.extract_intent_keywords(intent)
            for keyword in keywords:
                if keyword.lower() in description:
                    score += 0.1

            # 4. checktoolcapabilitymapping
            if tool_name in self.tool_capabilities:
                for capability in self.tool_capabilities[tool_name]:
                    if capability.lower() in intent_lower:
                        score += 0.3
                        break

            if score > 0:
                scores.append((tool_name, score))

        # 按score降序sort
        scores.sort(key=lambda x: x[1], reverse=True)

        return scores

    def evaluate_tool(
        self,
        tool_name: str,
        context: "ToolExecutionContext"
    ) -> Tuple[bool, Optional[str]]:
        """
        tool评估

        评估toolis not适合在currentcontext中使用

        Args:
            tool_name: toolName
            context: Executecontext

        Returns:
            (is_suitable, reason)
        """
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return False, f"Tool {tool_name} not found"

        schema = tool.get_schema()

        # checkis notdangerousoperation
        if schema.dangerous and "dangerous_tools" not in context.permissions:
            return False, f"Tool requires dangerous_tools permission"

        # checkauthentication要求
        if schema.requires_auth and "authenticated" not in context.permissions:
            return False, f"Tool requires authentication"

        # checkrolepermission
        if schema.allowed_roles:
            agent_role = context.env_vars.get("role", "guest")
            if agent_role not in schema.allowed_roles:
                return False, f"Tool requires one of roles: {schema.allowed_roles}"

        # checkhistorysuccess率
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
        recommendedtool

        完整的五步Decisionprocess：
        1. scenario分Class
        2. intent关key词提取
        3. capability匹配
        4. tool评估
        5. generationrecommendedResult

        Args:
            intent: userintentDescription
            context: Executecontext
            top_k: Return前k个recommended

        Returns:
            recommendedtoollist [{"tool": name, "score": float, "reason": str}, ...]
        """
        logger.info(f"Recommending tools for intent: {intent}")

        # 1. scenario分Class
        scenario = self.classify_scenario(intent)
        logger.info(f"Classified scenario: {scenario}")

        # 2. 提取关key词
        keywords = self.extract_intent_keywords(intent)
        logger.info(f"Extracted keywords: {keywords}")

        # 3. capability匹配
        matched_tools = self.match_capabilities(intent, scenario)
        logger.info(f"Matched tools: {matched_tools}")

        # 4. tool评估and筛选
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
        Parametergeneration

        根据intent为toolgenerationParametersuggestion

        Args:
            tool_name: toolName
            intent: userintent
            context: Executecontext

        Returns:
            Parametersuggestiondictionary
        """
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return {}

        schema = tool.get_schema()
        parameters = {}

        # 从intent中提取Parameter
        for param in schema.parameters:
            if param.default is not None:
                parameters[param.name] = param.default

            # 尝试从intent中提取filepath
            if param.name == "path" or param.name == "file":
                # 查找可能的filepath
                import re
                paths = re.findall(r'[\w/\\.]+\.\w+', intent)
                if paths:
                    parameters[param.name] = paths[0]
                elif "workspace" in context.env_vars:
                    parameters[param.name] = context.env_vars["workspace"]

            # 尝试从intent中提取command
            elif param.name == "command":
                # 提取引号中的command
                import re
                commands = re.findall(r'["\']([^"\']+)["\']', intent)
                if commands:
                    parameters[param.name] = commands[0]

        return parameters
