"""Tool recommendation engine."""

from dataclasses import dataclass
from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from ..utils.diagnostic_logging import full_content_logging_enabled
from .schema import ToolSchema

if TYPE_CHECKING:
    from .schema import ToolExecutionContext


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TaskHint:
    task_intent: str
    domain: str
    operation: str


@dataclass(frozen=True)
class _ToolMetadata:
    task_intents: list[str]
    domains: list[str]
    operations: list[str]
    avoid_task_intents: list[str]
    requires_known_target: bool
    blocks_on_user: bool
    cost: str


def _string_list(raw_items: Any) -> list[str]:
    return [str(item).strip() for item in raw_items if str(item).strip()]


class ScenarioType(str, Enum):
    """Scenario type."""

    FILE_OPERATION = "file_operation"
    SYSTEM_COMMAND = "system_command"
    DATA_ANALYSIS = "data_analysis"
    NETWORK = "network"
    DATABASE = "database"
    TEXT_PROCESSING = "text_processing"
    UNKNOWN = "unknown"


_SCENARIO_KEYWORDS = {
    ScenarioType.FILE_OPERATION: [
        "file",
        "read",
        "write",
        "save",
        "delete",
        "list",
        "directory",
        "folder",
        "读取",
        "写入",
    ],
    ScenarioType.SYSTEM_COMMAND: [
        "command",
        "execute",
        "shell",
        "bash",
        "terminal",
        "run",
        "script",
        "终端",
    ],
    ScenarioType.DATA_ANALYSIS: [
        "analysis",
        "analyze",
        "statistics",
        "calculate",
        "data",
        "process",
    ],
    ScenarioType.NETWORK: [
        "network",
        "request",
        "http",
        "api",
        "download",
        "upload",
        "url",
        "fetch",
        "下载",
        "上传",
        "访问",
    ],
    ScenarioType.DATABASE: [
        "database",
        "query",
        "sql",
        "storage",
        "store",
        "insert",
        "update",
    ],
    ScenarioType.TEXT_PROCESSING: [
        "text",
        "string",
        "replace",
        "match",
        "search",
        "parse",
        "文本",
        "匹配",
    ],
}


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
        self.scenario_keywords = {
            scenario: list(keywords) for scenario, keywords in _SCENARIO_KEYWORDS.items()
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
        intent_clean = re.sub(r"[^\w\s]", " ", intent)

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
        hint = self._task_hint(task_hint)
        scores = []
        keywords = self.extract_intent_keywords(intent)

        tools = list(candidate_tools) if candidate_tools is not None else self.registry.list_tools()

        for tool_name in tools:
            tool = self.registry.get_tool(tool_name)
            if not tool:
                continue

            schema = tool.get_schema()
            score = self._capability_score(
                intent=intent,
                scenario=scenario,
                schema=schema,
                keywords=keywords,
                hint=hint,
            )
            if score > 0:
                scores.append((tool_name, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)

        return scores

    def _capability_score(
        self,
        *,
        intent: str,
        scenario: ScenarioType,
        schema: ToolSchema,
        keywords: list[str],
        hint: _TaskHint,
    ) -> float:
        metadata = self._tool_metadata(schema.metadata or {})
        return (
            self._category_score(scenario, schema)
            + self._tag_score(intent, schema)
            + self._description_score(keywords, schema)
            + self._metadata_score(hint, metadata)
        )

    @staticmethod
    def _task_hint(task_hint: Optional[Dict[str, Any]]) -> _TaskHint:
        raw = task_hint or {}
        return _TaskHint(
            task_intent=str(raw.get("task_intent", "") or "").strip(),
            domain=str(raw.get("domain", "") or "").strip(),
            operation=str(raw.get("operation", "") or "").strip(),
        )

    @staticmethod
    def _tool_metadata(metadata: dict[str, Any]) -> _ToolMetadata:
        return _ToolMetadata(
            task_intents=_string_list(metadata.get("task_intents", [])),
            domains=_string_list(metadata.get("domains", [])),
            operations=_string_list(metadata.get("operations", [])),
            avoid_task_intents=_string_list(metadata.get("avoid_task_intents", [])),
            requires_known_target=bool(metadata.get("requires_known_target", False)),
            blocks_on_user=bool(metadata.get("blocks_on_user", False)),
            cost=str(metadata.get("cost", "") or "").strip().lower(),
        )

    @staticmethod
    def _category_score(scenario: ScenarioType, schema: ToolSchema) -> float:
        if scenario == ScenarioType.FILE_OPERATION and schema.category == "file":
            return 0.3
        if scenario == ScenarioType.SYSTEM_COMMAND and schema.category == "system":
            return 0.3
        return 0.0

    @staticmethod
    def _tag_score(intent: str, schema: ToolSchema) -> float:
        intent_lower = intent.lower()
        return sum(0.2 for tag in schema.tags or [] if tag.lower() in intent_lower)

    @staticmethod
    def _description_score(keywords: list[str], schema: ToolSchema) -> float:
        description = schema.description.lower()
        return sum(0.1 for keyword in keywords if keyword.lower() in description)

    @staticmethod
    def _metadata_score(hint: _TaskHint, metadata: _ToolMetadata) -> float:
        score = 0.0
        if hint.task_intent:
            if hint.task_intent in metadata.task_intents:
                score += 0.6
            if hint.task_intent in metadata.avoid_task_intents:
                score -= 0.4
        if hint.domain and hint.domain in metadata.domains:
            score += 0.25
        if hint.operation and hint.operation in metadata.operations:
            score += 0.2
        if metadata.requires_known_target and hint.operation in {
            "discover",
            "narrow",
            "probe",
        }:
            score -= 0.15
        if metadata.blocks_on_user and hint.task_intent != "clarify_requirement":
            score -= 0.7
        if metadata.cost == "cheap":
            score += 0.05
        elif metadata.cost == "high":
            score -= 0.05
        return score

    def evaluate_tool(
        self, tool_name: str, context: "ToolExecutionContext"
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
            return False, "Tool requires dangerous_tools permission"

        # Check authentication requirement
        if schema.requires_auth and "authenticated" not in context.permissions:
            return False, "Tool requires authentication"

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
        if full_content_logging_enabled():
            logger.info("Recommending tools for intent: %s", intent)
        else:
            logger.info(
                "Recommending tools for intent | intent_chars=%d",
                len(intent),
            )
        matched_tools = self._matched_tools_for_recommendation(
            intent,
            task_hint,
            candidate_tools,
        )
        recommendations = self._collect_recommendations(
            matched_tools,
            context,
            top_k,
        )
        logger.info(f"Final recommendations: {len(recommendations)} tools")
        return recommendations

    def _matched_tools_for_recommendation(
        self,
        intent: str,
        task_hint: Optional[Dict[str, Any]],
        candidate_tools: Optional[List[str]],
    ) -> List[Tuple[str, float]]:
        scenario = self.classify_scenario(intent)
        logger.info(f"Classified scenario: {scenario}")
        keywords = self.extract_intent_keywords(intent)
        if full_content_logging_enabled():
            logger.info("Extracted keywords: %s", keywords)
        else:
            logger.info("Extracted keywords | count=%d", len(keywords))
        matched_tools = self.match_capabilities(
            intent,
            scenario,
            task_hint=task_hint,
            candidate_tools=candidate_tools,
        )
        if full_content_logging_enabled():
            logger.info("Matched tools: %s", matched_tools)
        else:
            logger.info("Matched tools | count=%d", len(matched_tools))
        return matched_tools

    def _collect_recommendations(
        self,
        matched_tools: List[Tuple[str, float]],
        context: "ToolExecutionContext",
        top_k: int,
    ) -> List[Dict[str, Any]]:
        recommendations: List[Dict[str, Any]] = []
        for tool_name, score in matched_tools[: top_k * 2]:  # Take extra candidates
            recommendation = self._recommendation_for_tool(tool_name, score, context)
            if recommendation is not None:
                recommendations.append(recommendation)
            if len(recommendations) >= top_k:
                break
        return recommendations

    def _recommendation_for_tool(
        self,
        tool_name: str,
        score: float,
        context: "ToolExecutionContext",
    ) -> Optional[Dict[str, Any]]:
        is_suitable, reason = self.evaluate_tool(tool_name, context)
        if not is_suitable:
            logger.debug(f"Tool {tool_name} not suitable: {reason}")
            return None

        tool = self.registry.get_tool(tool_name)
        schema = tool.get_schema()
        return {
            "tool": tool_name,
            "score": score,
            "reason": str((schema.metadata or {}).get("tool_hint") or schema.description),
            "category": schema.category,
            "metadata": dict(schema.metadata or {}),
            "parameters": [p.model_dump(mode="json") for p in schema.parameters],
        }

    def suggest_parameters(
        self, tool_name: str, intent: str, context: "ToolExecutionContext"
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

                paths = re.findall(r"[\w/\\.]+\.\w+", intent)
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
