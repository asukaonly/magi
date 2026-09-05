"""
Web Search Tool - Search web using multiple providers
"""

import copy
import time
from dataclasses import dataclass
from datetime import date
from typing import Dict, Any, List

from ..schema import (
    MultiProviderTool,
    ToolSchema,
    ToolExecutionContext,
    ToolResult,
    ToolParameter,
    ParameterType,
    ToolConfigSpec,
    ToolErrorCode,
)
from ..providers.base import ProviderConfig
from ..providers.web_search import (
    DuckDuckGoSearchProvider,
    BraveSearchProvider,
    PerplexitySearchProvider,
    SearXNGSearchProvider,
    TavilySearchProvider,
)
from ..providers.web_search.rate_limit import (
    SharedProviderRateLimiter,
    get_web_search_rate_limiter,
)
from ...config import get_config, save_config
from ...i18n import t

# Provider display info for messages
PROVIDER_INFO = {
    "duckduckgo": {"name": "DuckDuckGo"},
    "brave": {"name": "Brave Search"},
    "perplexity": {"name": "Perplexity AI"},
    "searxng": {"name": "SearXNG"},
    "tavily": {"name": "Tavily"},
}

_DEDUP_CACHE_TTL_SECONDS = 600.0
_RESULT_CACHE_TTL_SECONDS = 900.0

# Deterministic fallback order used when the configured default provider fails
# or is not configured. Keyed / higher-quality providers first; keyless
# DuckDuckGo last as the always-available safety net. The configured default is
# always tried first regardless of its position here.
_FALLBACK_PRIORITY = ("brave", "tavily", "perplexity", "searxng", "duckduckgo")


@dataclass(frozen=True)
class _SearchRequest:
    query: Any
    executed_query: Any
    num_results: int
    configured_provider: str
    date_range_applied: Dict[str, str] | None
    proxy_url: str | None


def _web_search_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="query",
            type=ParameterType.STRING,
            description="The search query",
            required=True,
        ),
        ToolParameter(
            name="num_results",
            type=ParameterType.INTEGER,
            description="Number of results to return",
            required=False,
            default=10,
            min_value=1,
            max_value=50,
        ),
        ToolParameter(
            name="start_date",
            type=ParameterType.STRING,
            description="Optional inclusive start date in YYYY-MM-DD format for time-bounded search",
            required=False,
        ),
        ToolParameter(
            name="end_date",
            type=ParameterType.STRING,
            description="Optional inclusive end date in YYYY-MM-DD format for time-bounded search",
            required=False,
        ),
    ]


def _web_search_examples() -> list[dict[str, Any]]:
    return [
        {
            "input": {"query": "latest AI news"},
            "output": "Returns search results",
        },
        {
            "input": {"query": "OpenAI release notes", "num_results": 5},
            "output": "Returns search results using the configured default provider",
        },
    ]


def _web_search_metadata() -> dict[str, Any]:
    return {
        "task_intents": ["research_external"],
        "domains": ["web"],
        "operations": ["discover"],
        "query_shapes": ["topic_query", "time_bounded_query"],
        "followed_by": ["web-fetch"],
        "avoid_task_intents": [
            "verify_source_claim",
            "apply_change",
            "clarify_requirement",
        ],
        "cost": "cheap",
        "tool_hint": "Use first for broad web discovery and source collection; follow with web-fetch only when article details or verification are needed.",
    }


class WebSearchTool(MultiProviderTool):
    """
    Web Search Tool

    Search the web using configured providers.
    """

    def __init__(self) -> None:
        self._turn_query_cache: dict[str, dict[tuple[str, str, int], float]] = {}
        self._query_result_counts: dict[tuple[str, str, int], tuple[float, int]] = {}
        self._result_cache: dict[
            tuple[str, str, tuple[str, ...], str, int], tuple[float, dict[str, Any]]
        ] = {}
        super().__init__()

    def _init_schema(self) -> None:
        """Initialize Schema"""
        self.schema = ToolSchema(
            name="web-search",
            description=(
                "Search the web for information. The provider is chosen by the "
                "system from the user's configuration — you cannot and need not "
                "select one. The configured default provider is used first, with "
                "automatic fallback to other configured providers if it fails.\n"
                "Configure provider settings via system-settings tool "
                "(for example: tool.web-search.providers.brave.api_key)."
            ),
            category="web",
            version="1.1.0",
            author="Magi Team",
            parameters=_web_search_parameters(),
            examples=_web_search_examples(),
            timeout=30,
            retry_on_failure=False,
            max_retries=0,
            dangerous=False,
            effect_replay_policy="read_only",
            tags=["web", "search", "information"],
            metadata=_web_search_metadata(),
        )

    def _register_providers(self) -> None:
        """Register all available web search providers."""
        self.register_provider(DuckDuckGoSearchProvider())
        self.register_provider(BraveSearchProvider())
        self.register_provider(PerplexitySearchProvider())
        self.register_provider(SearXNGSearchProvider())
        self.register_provider(TavilySearchProvider())

    def _get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get configuration for a specific provider."""
        config = get_config()
        return config.tools.web_search.get_provider_config(provider_name)

    def _get_default_provider(self) -> str:
        """Get the default provider name from config."""
        config = get_config()
        return config.tools.web_search.default_provider

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Execute web search query."""
        revision = self.provider_revision
        if getattr(self, "_cached_provider_revision", None) != revision:
            await self.clear_user_content()
            self._cached_provider_revision = revision
        return await self._handle_query(parameters, context)

    async def clear_user_content(self) -> None:
        """Discard cached user queries and search results."""
        self._turn_query_cache.clear()
        self._query_result_counts.clear()
        self._result_cache.clear()

    def list_config_specs(self) -> List[ToolConfigSpec]:
        """Describe tool-scoped config entries managed by this tool."""
        specs: List[ToolConfigSpec] = [
            ToolConfigSpec(
                path="default_provider",
                type="string",
                description="Default web search provider",
                required=True,
                enum=self.get_all_provider_names(),
            ),
            ToolConfigSpec(
                path="providers.{provider}.api_key",
                type="string",
                description="Provider API key",
                sensitive=True,
                required=True,
                providers=["brave", "perplexity", "tavily"],
            ),
            ToolConfigSpec(
                path="providers.{provider}.base_url",
                type="string",
                description="Search endpoint override or self-hosted instance URL",
                providers=["duckduckgo", "searxng"],
            ),
        ]
        return specs

    async def get_config_value(
        self, path: str, context: ToolExecutionContext
    ) -> ToolResult:
        """Read non-sensitive tool-scoped config values."""
        config = get_config().tools.web_search
        if path == "default_provider":
            return ToolResult(success=True, data=config.default_provider)

        if path.startswith("providers.") and path.endswith(".base_url"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            return ToolResult(
                success=True, data=config.get_provider_config(provider_name).base_url
            )

        return ToolResult(
            success=False,
            error=f"Unsupported config path for web-search: {path}",
            error_code=ToolErrorCode.UNSUPPORTED_PATH.value,
        )

    async def update_config(
        self, path: str, value: Any, context: ToolExecutionContext
    ) -> ToolResult:
        """Update tool-scoped config values via tool-owned validation logic."""
        if path == "default_provider":
            provider_name = str(value)
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            if save_config({"tools.web_search.default_provider": provider_name}):
                return ToolResult(
                    success=True, data={"path": path, "value": provider_name}
                )
            return ToolResult(
                success=False,
                error="Failed to save configuration",
                error_code=ToolErrorCode.SAVE_FAILED.value,
            )

        if path.startswith("providers.") and path.endswith(".api_key"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            if save_config(
                {f"tools.web_search.providers.{provider_name}.api_key": str(value)}
            ):
                info = PROVIDER_INFO.get(provider_name, {"name": provider_name})
                return ToolResult(
                    success=True,
                    data={
                        "provider": provider_name,
                        "name": info["name"],
                        "configured": True,
                    },
                )
            return ToolResult(
                success=False,
                error="Failed to save configuration",
                error_code=ToolErrorCode.SAVE_FAILED.value,
            )

        if path.startswith("providers.") and path.endswith(".base_url"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            if save_config(
                {f"tools.web_search.providers.{provider_name}.base_url": str(value)}
            ):
                return ToolResult(
                    success=True,
                    data={"provider": provider_name, "base_url": str(value)},
                )
            return ToolResult(
                success=False,
                error="Failed to save configuration",
                error_code=ToolErrorCode.SAVE_FAILED.value,
            )

        return ToolResult(
            success=False,
            error=f"Unsupported config path for web-search: {path}",
            error_code=ToolErrorCode.UNSUPPORTED_PATH.value,
        )

    async def _handle_query(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Handle web search query."""
        request = self._prepare_search_request(parameters)
        if isinstance(request, ToolResult):
            return request

        available_providers = self.get_available_providers()
        if not available_providers:
            return self._build_no_providers_guidance()

        candidates = self._build_provider_candidates(
            configured_provider=request.configured_provider,
            available_providers=available_providers,
        )
        primary_provider = candidates[0]

        cached_result = self._build_cached_search_result(
            context=context,
            request=request,
            candidates=candidates,
            primary_provider=primary_provider,
        )
        if cached_result is not None:
            return cached_result

        return await self._execute_search_candidates(
            context=context,
            request=request,
            candidates=candidates,
            primary_provider=primary_provider,
        )

    def _prepare_search_request(
        self, parameters: Dict[str, Any]
    ) -> _SearchRequest | ToolResult:
        query = parameters.get("query")

        if not query:
            return ToolResult(
                success=False,
                error="Missing 'query' parameter. Provide a search query.",
                error_code=ToolErrorCode.MISSING_QUERY.value,
            )

        configured_provider = str(self._get_default_provider()).strip()
        date_range_applied = self._normalize_date_range(
            parameters.get("start_date"),
            parameters.get("end_date"),
        )
        if isinstance(date_range_applied, ToolResult):
            return date_range_applied
        executed_query = self._apply_date_range_to_query(query, date_range_applied)
        num_results = int(parameters.get("num_results", 10))
        proxy_url = get_config().network.proxy_url()
        return _SearchRequest(
            query=query,
            executed_query=executed_query,
            num_results=num_results,
            configured_provider=configured_provider,
            date_range_applied=date_range_applied,
            proxy_url=proxy_url,
        )

    def _build_no_providers_guidance(self) -> ToolResult:
        return ToolResult(
            success=False,
            error=t(
                "tools.web_search.no_providers.error",
                fallback="No search providers are configured. Ask the user to configure a provider API key via system-settings, then retry.",
            ),
            error_code=ToolErrorCode.NO_PROVIDERS_CONFIGURED.value,
            data={
                "next_action": "ask_user_to_configure_api_key",
                "retryable": False,
                "terminal": True,
                "llm_guidance": t(
                    "tools.web_search.no_providers.llm_guidance",
                    fallback="Do not retry web search until at least one search provider is available. Ask the user to confirm tool configuration or restore a supported provider.",
                ),
                "user_message_template": t(
                    "tools.web_search.no_providers.user_message",
                    fallback="To continue web search, please ensure the web search tool is configured. I will resume the current search after it is available.",
                ),
                "config_tool": "system-settings",
                "config_example": {
                    "action": "set",
                    "path": "tool.web-search.default_provider",
                    "value": "duckduckgo",
                },
                "supported_providers": list(PROVIDER_INFO.keys()),
            },
        )

    def _build_provider_candidates(
        self,
        *,
        configured_provider: str,
        available_providers: List[str],
    ) -> List[str]:
        ordered = [configured_provider] + [
            p for p in _FALLBACK_PRIORITY if p != configured_provider
        ]
        ordered.extend(p for p in available_providers if p not in ordered)
        candidates = [p for p in ordered if p in available_providers]
        if not candidates:
            candidates = list(available_providers)
        return candidates

    def _build_cached_search_result(
        self,
        *,
        context: ToolExecutionContext,
        request: _SearchRequest,
        candidates: List[str],
        primary_provider: str,
    ) -> ToolResult | None:
        duplicate_result = self._build_duplicate_turn_result(
            context=context,
            provider_name=primary_provider,
            query=str(request.query),
            executed_query=request.executed_query,
            num_results=request.num_results,
            requested_provider=request.configured_provider,
        )
        if duplicate_result is not None:
            return duplicate_result

        return self._build_cached_result(
            context=context,
            configured_provider=request.configured_provider,
            candidates=candidates,
            query=str(request.query),
            executed_query=request.executed_query,
            num_results=request.num_results,
            date_range_applied=request.date_range_applied,
        )

    async def _execute_search_candidates(
        self,
        *,
        context: ToolExecutionContext,
        request: _SearchRequest,
        candidates: List[str],
        primary_provider: str,
    ) -> ToolResult:
        attempts: List[Dict[str, Any]] = []
        ddg_challenge_seen = False
        for provider_name in candidates:
            limiter = self._rate_limiter_for_provider(provider_name)
            if limiter is not None:
                await limiter.wait(provider_name)
            result = await self.execute_with_provider(
                provider_name,
                {
                    "query": request.executed_query,
                    "num_results": request.num_results,
                    "proxy_url": request.proxy_url,
                },
            )
            if (
                result.error_code == ToolErrorCode.RATE_LIMITED.value
                and limiter is not None
            ):
                retry_after_seconds = (
                    result.data.get("retry_after_seconds")
                    if isinstance(result.data, dict)
                    else None
                )
                limiter.defer(provider_name, retry_after_seconds)
            if result.success:
                self._finalize_successful_search_result(
                    context=context,
                    request=request,
                    candidates=candidates,
                    primary_provider=primary_provider,
                    provider_name=provider_name,
                    attempts=attempts,
                    result=result,
                )
                return result

            attempts.append(self._project_failed_attempt(provider_name, result))
            if self._is_duckduckgo_challenge_error(provider_name, result):
                ddg_challenge_seen = True

        if ddg_challenge_seen and len(candidates) == 1:
            return self._build_duckduckgo_challenge_guidance(
                query=request.query,
                requested_provider=request.configured_provider,
                actual_provider="duckduckgo",
                date_range_applied=request.date_range_applied,
            )
        return self._build_all_providers_failed_guidance(
            query=str(request.query),
            configured_provider=request.configured_provider,
            attempts=attempts,
            date_range_applied=request.date_range_applied,
        )

    def _rate_limiter_for_provider(
        self,
        provider_name: str,
    ) -> SharedProviderRateLimiter | None:
        if provider_name != "brave":
            return None
        config = self._get_provider_config(provider_name)
        if not str(getattr(config, "api_key", None) or "").strip():
            return None
        return get_web_search_rate_limiter()

    def _finalize_successful_search_result(
        self,
        *,
        context: ToolExecutionContext,
        request: _SearchRequest,
        candidates: List[str],
        primary_provider: str,
        provider_name: str,
        attempts: List[Dict[str, Any]],
        result: ToolResult,
    ) -> None:
        result.data["query"] = request.query
        result.data["executed_query"] = request.executed_query
        result.data["requested_provider"] = request.configured_provider
        result.data["actual_provider"] = provider_name
        result.data["fallback_used"] = provider_name != request.configured_provider
        if attempts:
            result.data["fallback_from"] = [a["provider"] for a in attempts]
        if request.date_range_applied is not None:
            result.data["date_range_applied"] = request.date_range_applied
        self._record_successful_result(
            context=context,
            configured_provider=request.configured_provider,
            candidates=candidates,
            executed_query=request.executed_query,
            num_results=request.num_results,
            data=result.data,
        )
        self._record_successful_turn_query(
            context=context,
            provider_name=primary_provider,
            executed_query=request.executed_query,
            num_results=request.num_results,
            result_count=int(
                result.data.get("result_count") or result.data.get("total") or 0
            ),
        )

    @staticmethod
    def _project_failed_attempt(
        provider_name: str,
        result: ToolResult,
    ) -> Dict[str, Any]:
        attempt = {
            "provider": provider_name,
            "error_code": result.error_code,
            "error": str(result.error or ""),
        }
        if (
            isinstance(result.data, dict)
            and result.data.get("retry_after_seconds") is not None
        ):
            attempt["retry_after_seconds"] = result.data["retry_after_seconds"]
        return attempt

    def _build_duplicate_turn_result(
        self,
        *,
        context: ToolExecutionContext,
        provider_name: str,
        query: str,
        executed_query: str,
        num_results: int,
        requested_provider: str,
    ) -> ToolResult | None:
        self._prune_dedup_cache()
        turn_key = self._turn_cache_key(context)
        if not turn_key:
            return None
        cache_key = self._query_cache_key(provider_name, executed_query, num_results)
        if cache_key not in self._turn_query_cache.get(turn_key, {}):
            return None
        _, result_count = self._query_result_counts.get(cache_key, (time.time(), 0))
        return ToolResult(
            success=True,
            data={
                "cached": True,
                "duplicate_query": True,
                "query": query,
                "executed_query": executed_query,
                "requested_provider": requested_provider,
                "actual_provider": provider_name,
                "result_count": result_count,
                "llm_guidance": "This exact web search already ran in this turn. Reuse the earlier search results instead of repeating the same query.",
            },
        )

    def _record_successful_turn_query(
        self,
        *,
        context: ToolExecutionContext,
        provider_name: str,
        executed_query: str,
        num_results: int,
        result_count: int,
    ) -> None:
        turn_key = self._turn_cache_key(context)
        if not turn_key:
            return
        now = time.time()
        cache_key = self._query_cache_key(provider_name, executed_query, num_results)
        self._turn_query_cache.setdefault(turn_key, {})[cache_key] = now
        self._query_result_counts[cache_key] = (now, result_count)

    def _build_cached_result(
        self,
        *,
        context: ToolExecutionContext,
        configured_provider: str,
        candidates: list[str],
        query: str,
        executed_query: str,
        num_results: int,
        date_range_applied: Dict[str, str] | None,
    ) -> ToolResult | None:
        self._prune_result_cache()
        cache_key = self._result_cache_key(
            cache_scope=self._result_cache_scope(context),
            configured_provider=configured_provider,
            candidates=candidates,
            executed_query=executed_query,
            num_results=num_results,
        )
        cached = self._result_cache.get(cache_key)
        if cached is None:
            return None
        _, data = cached
        payload = copy.deepcopy(data)
        payload["cached"] = True
        payload["cache_ttl_seconds"] = int(_RESULT_CACHE_TTL_SECONDS)
        payload["query"] = query
        payload["executed_query"] = executed_query
        if date_range_applied is not None:
            payload["date_range_applied"] = date_range_applied
        return ToolResult(success=True, data=payload)

    def _record_successful_result(
        self,
        *,
        context: ToolExecutionContext,
        configured_provider: str,
        candidates: list[str],
        executed_query: str,
        num_results: int,
        data: Dict[str, Any],
    ) -> None:
        cache_key = self._result_cache_key(
            cache_scope=self._result_cache_scope(context),
            configured_provider=configured_provider,
            candidates=candidates,
            executed_query=executed_query,
            num_results=num_results,
        )
        payload = copy.deepcopy(data)
        payload.pop("cached", None)
        self._result_cache[cache_key] = (time.time(), payload)

    def _prune_result_cache(self) -> None:
        cutoff = time.time() - _RESULT_CACHE_TTL_SECONDS
        stale_keys = [
            key for key, (seen_at, _) in self._result_cache.items() if seen_at < cutoff
        ]
        for key in stale_keys:
            self._result_cache.pop(key, None)

    @staticmethod
    def _result_cache_key(
        *,
        cache_scope: str,
        configured_provider: str,
        candidates: list[str],
        executed_query: str,
        num_results: int,
    ) -> tuple[str, str, tuple[str, ...], str, int]:
        normalized_query = " ".join(str(executed_query or "").lower().split())
        return (
            str(cache_scope or "").strip().lower(),
            str(configured_provider or "").strip().lower(),
            tuple(str(item).strip().lower() for item in candidates),
            normalized_query,
            int(num_results),
        )

    @staticmethod
    def _result_cache_scope(context: ToolExecutionContext) -> str:
        return str(context.agent_id or "unknown").strip() or "unknown"

    def _prune_dedup_cache(self) -> None:
        cutoff = time.time() - _DEDUP_CACHE_TTL_SECONDS
        stale_turns: list[str] = []
        for turn_key, queries in self._turn_query_cache.items():
            stale_queries = [
                key for key, seen_at in queries.items() if seen_at < cutoff
            ]
            for key in stale_queries:
                queries.pop(key, None)
            if not queries:
                stale_turns.append(turn_key)
        for turn_key in stale_turns:
            self._turn_query_cache.pop(turn_key, None)
        stale_result_keys = [
            key
            for key, (seen_at, _) in self._query_result_counts.items()
            if seen_at < cutoff
        ]
        for key in stale_result_keys:
            self._query_result_counts.pop(key, None)

    @staticmethod
    def _turn_cache_key(context: ToolExecutionContext) -> str:
        env_vars = context.env_vars or {}
        turn_id = str(env_vars.get("turn_id") or "").strip()
        if not turn_id:
            return ""
        agent_id = str(context.agent_id or "unknown").strip() or "unknown"
        return f"{turn_id}:{agent_id}"

    @staticmethod
    def _query_cache_key(
        provider_name: str, executed_query: str, num_results: int
    ) -> tuple[str, str, int]:
        normalized_query = " ".join(str(executed_query or "").lower().split())
        return (
            str(provider_name or "").strip().lower(),
            normalized_query,
            int(num_results),
        )

    def _build_all_providers_failed_guidance(
        self,
        *,
        query: str,
        configured_provider: str,
        attempts: List[Dict[str, Any]],
        date_range_applied: Dict[str, str] | None,
    ) -> ToolResult:
        attempted = [a["provider"] for a in attempts]
        data: Dict[str, Any] = {
            "next_action": "ask_user_to_check_search_providers",
            "retryable": False,
            "terminal": True,
            "query": query,
            "configured_provider": configured_provider,
            "attempted_providers": attempted,
            "attempts": attempts,
            "llm_guidance": t(
                "tools.web_search.all_providers_failed.llm_guidance",
                fallback=(
                    "Every configured web search provider was tried in order and "
                    "all failed for this query. Do not keep retrying web search in "
                    "this turn. Tell the user which providers failed and ask them to "
                    "check provider configuration/connectivity, or try again later."
                ),
            ),
            "user_message_template": t(
                "tools.web_search.all_providers_failed.user_message",
                fallback=(
                    "All configured web search providers failed this time ({providers}). "
                    "Please check the search provider settings or network, then I can retry."
                ),
                providers=", ".join(attempted) or configured_provider,
            ),
            "config_tool": "system-settings",
        }
        if date_range_applied is not None:
            data["date_range_applied"] = date_range_applied
        return ToolResult(
            success=False,
            error=t(
                "tools.web_search.all_providers_failed.error",
                fallback="All configured web search providers failed: {providers}.",
                providers=", ".join(attempted) or configured_provider,
            ),
            error_code=ToolErrorCode.PROVIDER_ERROR.value,
            data=data,
        )

    def _is_duckduckgo_challenge_error(
        self, provider_name: str, result: ToolResult
    ) -> bool:
        if provider_name != "duckduckgo":
            return False
        if result.error_code not in {
            ToolErrorCode.PROVIDER_ERROR.value,
            ToolErrorCode.PROVIDER_CHALLENGE.value,
        }:
            return False
        error_text = str(result.error or "").lower()
        return any(
            marker in error_text
            for marker in [
                "duckduckgo search challenge triggered",
                "anti-bot verification",
                "bots use duckduckgo too",
                "challenge",
                "captcha",
            ]
        )

    def _build_duckduckgo_challenge_guidance(
        self,
        *,
        query: str,
        requested_provider: str,
        actual_provider: str,
        date_range_applied: Dict[str, str] | None,
    ) -> ToolResult:
        alternative_providers = [
            name for name in self.get_all_provider_names() if name != "duckduckgo"
        ]
        guidance_data: Dict[str, Any] = {
            "next_action": "ask_user_to_configure_search_provider",
            "retryable": False,
            "terminal": True,
            "llm_guidance": t(
                "tools.web_search.duckduckgo_challenge.llm_guidance",
                fallback="DuckDuckGo is currently blocked by an anti-bot challenge for this search. Ask the user to configure Brave, Perplexity, or Tavily via system-settings before retrying. Do not keep retrying DuckDuckGo for the same request.",
            ),
            "user_message_template": t(
                "tools.web_search.duckduckgo_challenge.user_message",
                fallback="DuckDuckGo hit an anti-bot check this time and could not return stable results. Please configure Brave, Perplexity, or Tavily in settings, then I can continue the search.",
            ),
            "config_tool": "system-settings",
            "requested_provider": requested_provider,
            "actual_provider": actual_provider,
            "fallback_reason": t(
                "tools.web_search.duckduckgo_challenge.fallback_reason",
                fallback="DuckDuckGo returned an anti-bot verification challenge instead of usable search results.",
            ),
            "query": query,
            "supported_providers": alternative_providers,
            "config_examples": self._build_provider_config_examples(
                alternative_providers
            ),
        }
        if date_range_applied is not None:
            guidance_data["date_range_applied"] = date_range_applied
        return ToolResult(
            success=False,
            error=t(
                "tools.web_search.duckduckgo_challenge.error",
                fallback="DuckDuckGo search challenge triggered. Configure another web-search provider and retry.",
            ),
            error_code=ToolErrorCode.PROVIDER_CHALLENGE.value,
            data=guidance_data,
        )

    def _build_provider_config_examples(
        self, providers: List[str]
    ) -> List[Dict[str, str]]:
        examples: List[Dict[str, str]] = []
        for provider in providers:
            if provider == "duckduckgo":
                examples.append(
                    {
                        "action": "set",
                        "path": "tool.web-search.default_provider",
                        "value": "duckduckgo",
                    }
                )
                continue
            examples.append(
                {
                    "action": "set",
                    "path": f"tool.web-search.providers.{provider}.api_key",
                    "value": f"YOUR_{provider.upper()}_API_KEY",
                }
            )
        return examples

    def _normalize_date_range(
        self, start_date: Any, end_date: Any
    ) -> Dict[str, str] | ToolResult | None:
        start = str(start_date or "").strip()
        end = str(end_date or "").strip()
        if not start and not end:
            return None
        if not start or not end:
            return ToolResult(
                success=False,
                error="Both 'start_date' and 'end_date' must be provided together in YYYY-MM-DD format.",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )
        try:
            normalized_start = date.fromisoformat(start)
            normalized_end = date.fromisoformat(end)
        except ValueError:
            return ToolResult(
                success=False,
                error="Invalid date range. Use YYYY-MM-DD for both 'start_date' and 'end_date'.",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )
        if normalized_start > normalized_end:
            return ToolResult(
                success=False,
                error="'start_date' must be on or before 'end_date'.",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )
        return {
            "start_date": normalized_start.isoformat(),
            "end_date": normalized_end.isoformat(),
        }

    def _apply_date_range_to_query(
        self, query: str, date_range: Dict[str, str] | None
    ) -> str:
        if not date_range:
            return query
        return (
            f"{query} after:{date_range['start_date']} before:{date_range['end_date']}"
        )
