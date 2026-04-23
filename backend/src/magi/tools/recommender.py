"""Tool recommendation engine."""
import logging
from typing import Dict, List, Any, Optional, Tuple, TYPE_CHECKING
from enum import Enum
import re

from .schema import Tool, ToolSchema, ToolParameter

if TYPE_CHECKING:
    from .schema import ToolExecutionContext


logger = logging.getLogger(__name__)


class ScenarioType(str, Enum):
    """Scenario type."""
    FILE_OPERATION = "file_operation"
    SYSTEM_COMMAND = "system_command"
    DATA_ANALYSIS = "data_analysis"
    NETWORK = "network"
    DATABASE = "database"
    TEXT_PROCESSING = "text_processing"
    UNKNOWN = "unknown"


class ToolRecommender:
    """
    Tool recommendation engine.

    Recommends suitable tools based on user intent and scenario.
    """

    def __init__(self, tool_registry):
        """
        Initialize recommendation engine.

        Args:
            tool_registry: Tool registry instance.
        """
        self.registry = tool_registry

        # Scenario keyword mapping
        self.scenario_keywords = {
            ScenarioType.FILE_OPERATION: [
                "file", "file", "读取", "read", "写入", "write", "save", "save",
                "delete", "delete", "list", "list", "directory", "directory", "folder"
            ],
            ScenarioType.SYSTEM_COMMAND: [
                "command", "command", "Execute", "execute", "shell", "bash", "终端",
                "terminal", "run", "run", "script", "script"
            ],
            ScenarioType.DATA_ANALYSIS: [
                "analysis", "analyze", "statistics", "statistics", "calculate", "calculate",
                "data", "data", "process", "process"
            ],
            ScenarioType.NETWORK: [
                "network", "network", "request", "request", "http", "api", "下载",
                "download", "上传", "upload", "url", "访问", "fetch"
            ],
            ScenarioType.DATABASE: [
                "database", "database", "query", "query", "sql", "storage", "store",
                "insert", "insert", "update", "update"
            ],
            ScenarioType.TEXT_PROCESSING: [
                "文本", "text", "string", "string", "replace", "replace", "匹配",
                "match", "search", "search", "parse", "parse"
            ],
        }

        # Tool capability mapping
        self.tool_capabilities = {
            "file_read": ["读取file", "查看fileContent", "file读取", "read file"],
            "file_write": ["写入file", "savefile", "createfile", "write file", "save file"],
            "bash": ["Executecommand", "runscript", "shellcommand", "execute command"],
        }

    def classify_scenario(self, intent: str) -> ScenarioType:
        """
        Classify scenario from user intent.

        Args:
            intent: User intent description.

        Returns:
            Scenario type.
        """
        intent_lower = intent.lower()

        # Calculate match score for each scenario
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

        # Return highest scoring scenario
        return max(scores.items(), key=lambda x: x[1])[0]

    def extract_intent_keywords(self, intent: str) -> List[str]:
        """
        Extract keywords from user intent.

        Args:
            intent: User intent description.

        Returns:
            List of keywords.
        """
        # Simple keyword extraction (can use more complex NLP)
        keywords = []

        # Remove punctuation
        intent_clean = re.sub(r'[^\w\s]', ' ', intent)

        # Tokenize
        words = intent_clean.split()

        # Filter stopwords
        stopwords = {"的", "is", "在", "and", "与", "或", "the", "is", "at", "which", "on"}
        keywords = [w for w in words if len(w) > 1 and w not in stopwords]

        return keywords

    def match_capabilities(
        self,
        intent: str,
        scenario: ScenarioType,
        task_hint: Optional[Dict[str, Any]] = None,
        candidate_tools: Optional[List[str]] = None,
    ) -> List[Tuple[str, float]]:
        """
        Match tools by capability.

        Args:
            intent: User intent.
            scenario: Scenario type.

        Returns:
            [(tool_name, score), ...] sorted by score.
        """
        intent_lower = intent.lower()
        task_intent = str((task_hint or {}).get("task_intent", "") or "").strip()
        domain = str((task_hint or {}).get("domain", "") or "").strip()
        operation = str((task_hint or {}).get("operation", "") or "").strip()
        scores = []

        tools = list(candidate_tools) if candidate_tools is not None else self.registry.list_tools()

        for tool_name in tools:
            tool = self.registry.get_tool(tool_name)
            if not tool:
                continue

            schema = tool.get_schema()
            score = 0.0
            metadata = schema.metadata or {}

            # 1. Check if tool category matches scenario
            category_match = 0
            if scenario == ScenarioType.FILE_OPERATION and schema.category == "file":
                category_match = 0.3
            elif scenario == ScenarioType.SYSTEM_COMMAND and schema.category == "system":
                category_match = 0.3

            score += category_match

            # 2. Check tag match
            tags = schema.tags or []
            for tag in tags:
                if tag.lower() in intent_lower:
                    score += 0.2

            # 3. Check description match
            description = schema.description.lower()
            keywords = self.extract_intent_keywords(intent)
            for keyword in keywords:
                if keyword.lower() in description:
                    score += 0.1

            task_intents = [str(item).strip() for item in metadata.get("task_intents", []) if str(item).strip()]
            domains = [str(item).strip() for item in metadata.get("domains", []) if str(item).strip()]
            operations = [str(item).strip() for item in metadata.get("operations", []) if str(item).strip()]
            avoid_task_intents = [str(item).strip() for item in metadata.get("avoid_task_intents", []) if str(item).strip()]
            requires_known_target = bool(metadata.get("requires_known_target", False))
            blocks_on_user = bool(metadata.get("blocks_on_user", False))
            cost = str(metadata.get("cost", "") or "").strip().lower()
            if task_intent:
                if task_intent in task_intents:
                    score += 0.6
                if task_intent in avoid_task_intents:
                    score -= 0.4
            if domain and domain in domains:
                score += 0.25
            if operation and operation in operations:
                score += 0.2
            if requires_known_target and operation in {"discover", "narrow", "probe"}:
                score -= 0.15
            if blocks_on_user and task_intent != "clarify_requirement":
                score -= 0.7
            if cost == "cheap":
                score += 0.05
            elif cost == "high":
                score -= 0.05

            # 4. Check tool capability mapping
            if tool_name in self.tool_capabilities:
                for capability in self.tool_capabilities[tool_name]:
                    if capability.lower() in intent_lower:
                        score += 0.3
                        break

            if score > 0:
                scores.append((tool_name, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)

        return scores

    def evaluate_tool(
        self,
        tool_name: str,
        context: "ToolExecutionContext"
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluate tool suitability.

        Assess whether tool is suitable for current context.

        Args:
            tool_name: Tool name.
            context: Execution context.

        Returns:
            (is_suitable, reason)
        """
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return False, f"Tool {tool_name} not found"

        schema = tool.get_schema()

        # Check for dangerous operation
        if schema.dangerous and "dangerous_tools" not in context.permissions:
            return False, f"Tool requires dangerous_tools permission"

        # Check authentication requirement
        if schema.requires_auth and "authenticated" not in context.permissions:
            return False, f"Tool requires authentication"

        # Check role permission
        if schema.allowed_roles:
            agent_role = context.env_vars.get("role", "guest")
            if agent_role not in schema.allowed_roles:
                return False, f"Tool requires one of roles: {schema.allowed_roles}"

        # Check historical success rate
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
        top_k: int = 5,
        task_hint: Optional[Dict[str, Any]] = None,
        candidate_tools: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recommend tools for user intent.

        Five-step decision process:
        1. Scenario classification
        2. Intent keyword extraction
        3. Capability matching
        4. Tool evaluation
        5. Generate recommendations

        Args:
            intent: User intent description.
            context: Execution context.
            top_k: Return top k recommendations.

        Returns:
            List of recommendations [{"tool": name, "score": float, "reason": str}, ...].
        """
        logger.info(f"Recommending tools for intent: {intent}")

        # 1. Classify scenario
        scenario = self.classify_scenario(intent)
        logger.info(f"Classified scenario: {scenario}")

        # 2. Extract keywords
        keywords = self.extract_intent_keywords(intent)
        logger.info(f"Extracted keywords: {keywords}")

        # 3. Capability matching
        matched_tools = self.match_capabilities(
            intent,
            scenario,
            task_hint=task_hint,
            candidate_tools=candidate_tools,
        )
        logger.info(f"Matched tools: {matched_tools}")

        # 4. Evaluate and filter tools
        recommendations = []
        for tool_name, score in matched_tools[:top_k * 2]:  # Take extra candidates
            is_suitable, reason = self.evaluate_tool(tool_name, context)

            if is_suitable:
                tool = self.registry.get_tool(tool_name)
                schema = tool.get_schema()

                recommendations.append({
                    "tool": tool_name,
                    "score": score,
                    "reason": str((schema.metadata or {}).get("tool_hint") or schema.description),
                    "category": schema.category,
                    "metadata": dict(schema.metadata or {}),
                    "parameters": [p.model_dump(mode="json") for p in schema.parameters],
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
        Generate parameter suggestions.

        Suggest parameters based on intent for the tool.

        Args:
            tool_name: Tool name.
            intent: User intent.
            context: Execution context.

        Returns:
            Parameter suggestion dictionary.
        """
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return {}

        schema = tool.get_schema()
        parameters = {}

        # Extract parameters from intent
        for param in schema.parameters:
            if param.default is not None:
                parameters[param.name] = param.default

            # Try to extract file path from intent
            if param.name == "path" or param.name == "file":
                # Find possible file path
                import re
                paths = re.findall(r'[\w/\\.]+\.\w+', intent)
                if paths:
                    parameters[param.name] = paths[0]
                elif "workspace" in context.env_vars:
                    parameters[param.name] = context.env_vars["workspace"]

            # Try to extract command from intent
            elif param.name == "command":
                # Extract command from quotes
                import re
                commands = re.findall(r'["\']([^"\']+)["\']', intent)
                if commands:
                    parameters[param.name] = commands[0]

        return parameters
