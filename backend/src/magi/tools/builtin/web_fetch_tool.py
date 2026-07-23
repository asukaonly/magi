"""
Web Fetch Tool - Fetch and extract web page content
"""

import copy
import ipaddress
import re
import time
from dataclasses import dataclass
from html import unescape
from typing import Any, Dict, List
from urllib.parse import urlparse

from ..providers.base import ProviderConfig
from ..providers.web_fetch import CurlFetchProvider, HttpFetchProvider, PlaywrightFetchProvider
from ..schema import (
    MultiProviderTool,
    ParameterType,
    ToolConfigSpec,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
    ToolErrorCode,
)
from ..utils.network_safety import (
    RFC2544_FAKE_IP_COMPATIBILITY_REQUIRED,
    blocked_url_target_reason,
)
from ...config import get_config, save_config

_FETCH_CACHE_TTL_SECONDS = 900.0


@dataclass(frozen=True)
class _FetchRequest:
    url: str
    mode: str
    output_format: str
    wait_until: str
    timeout_ms: int
    max_chars: int
    include_metadata: bool
    allow_rfc2544_benchmark_range: bool
    allow_private_network: bool
    private_network_allowlist: list[str]
    proxy_url: str | None


class WebFetchTool(MultiProviderTool):
    """Fetch web page content with automatic fallback strategies."""

    def __init__(self) -> None:
        self._fetch_cache: dict[
            tuple[str, str, str, str, int, int, bool], tuple[float, dict[str, Any]]
        ] = {}
        super().__init__()

    def _parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="url",
                type=ParameterType.STRING,
                description="The webpage URL to fetch (must start with http:// or https://)",
                required=True,
            ),
            ToolParameter(
                name="mode",
                type=ParameterType.STRING,
                description="Fetch mode: auto/http/browser/curl",
                required=False,
                default="auto",
                enum=["auto", "http", "browser", "curl"],
            ),
            ToolParameter(
                name="output_format",
                type=ParameterType.STRING,
                description="Output format: markdown/text/html",
                required=False,
                default="markdown",
                enum=["markdown", "text", "html"],
            ),
            ToolParameter(
                name="wait_until",
                type=ParameterType.STRING,
                description="Browser wait strategy when mode uses browser",
                required=False,
                default="networkidle",
                enum=["domcontentloaded", "load", "networkidle"],
            ),
            ToolParameter(
                name="timeout_ms",
                type=ParameterType.INTEGER,
                description="Timeout in milliseconds",
                required=False,
                default=15000,
                min_value=1000,
                max_value=120000,
            ),
            ToolParameter(
                name="max_chars",
                type=ParameterType.INTEGER,
                description="Maximum characters returned in content",
                required=False,
                default=20000,
                min_value=1000,
                max_value=200000,
            ),
            ToolParameter(
                name="include_metadata",
                type=ParameterType.BOOLEAN,
                description="Whether to include metadata fields in result",
                required=False,
                default=True,
            ),
        ]

    def _examples(self) -> list[dict[str, Any]]:
        return [
            {
                "input": {"url": "https://example.com"},
                "output": "Returns page main content in markdown",
            },
            {
                "input": {
                    "url": "https://news.ycombinator.com",
                    "mode": "browser",
                },
                "output": "Returns browser-rendered page content",
            },
        ]

    def _metadata(self) -> dict[str, Any]:
        return {
            "task_intents": ["research_external", "verify_external_claim"],
            "domains": ["web"],
            "operations": ["fetch", "verify"],
            "query_shapes": ["exact_url"],
            "followed_by": [],
            "avoid_task_intents": ["explore_codebase", "clarify_requirement"],
            "requires_known_target": True,
            "cost": "medium",
            "tool_hint": (
                "Use after web-search has identified candidate URLs and only "
                "when you need full-page details, verification, or source text."
            ),
        }

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="web-fetch",
            description=(
                "Fetch webpage content from a URL. Supports direct HTTP fetch, browser-rendered "
                "fetch for JavaScript-heavy pages, and curl fallback.\n\n"
                "Default mode is auto: http -> browser (if needed) -> curl."
            ),
            category="web",
            version="1.0.0",
            author="Magi Team",
            parameters=self._parameters(),
            examples=self._examples(),
            timeout=60,
            retry_on_failure=False,
            dangerous=False,
            tags=["web", "fetch", "scrape", "content"],
            metadata=self._metadata(),
        )

    def _register_providers(self) -> None:
        self.register_provider(HttpFetchProvider())
        self.register_provider(PlaywrightFetchProvider())
        self.register_provider(CurlFetchProvider())

    def _get_provider_config(self, provider_name: str) -> ProviderConfig:
        config = get_config()
        return config.tools.web_fetch.get_provider_config(provider_name)

    def _get_default_provider(self) -> str:
        config = get_config()
        return config.tools.web_fetch.default_provider

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        return await self._handle_fetch(parameters)

    def list_config_specs(self) -> List[ToolConfigSpec]:
        return []

    def list_system_config_specs(self) -> List[ToolConfigSpec]:
        """Describe advanced config entries managed through system-settings."""
        return [
            ToolConfigSpec(
                path="default_provider",
                type="string",
                description="Default web-fetch provider for direct mode (http/browser/curl)",
                required=True,
                enum=self.get_all_provider_names(),
            ),
        ]

    async def get_config_value(self, path: str, context: ToolExecutionContext) -> ToolResult:
        config = get_config().tools.web_fetch
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
            return ToolResult(success=True, data=config.get_provider_config(provider_name).base_url)

        return ToolResult(
            success=False,
            error=f"Unsupported config path for web-fetch: {path}",
            error_code=ToolErrorCode.UNSUPPORTED_PATH.value,
        )

    async def update_config(
        self, path: str, value: Any, context: ToolExecutionContext
    ) -> ToolResult:
        if path == "default_provider":
            provider_name = str(value).strip()
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            if save_config({"tools.web_fetch.default_provider": provider_name}):
                return ToolResult(success=True, data={"path": path, "value": provider_name})
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
            if save_config({f"tools.web_fetch.providers.{provider_name}.base_url": str(value)}):
                return ToolResult(
                    success=True, data={"provider": provider_name, "base_url": str(value)}
                )
            return ToolResult(
                success=False,
                error="Failed to save configuration",
                error_code=ToolErrorCode.SAVE_FAILED.value,
            )

        return ToolResult(
            success=False,
            error=f"Unsupported config path for web-fetch: {path}",
            error_code=ToolErrorCode.UNSUPPORTED_PATH.value,
        )

    async def _handle_fetch(self, parameters: Dict[str, Any]) -> ToolResult:
        url = str(parameters.get("url", "")).strip()
        if not self._is_valid_url(url):
            return ToolResult(
                success=False,
                error="Invalid 'url'. URL must start with http:// or https:// and include host.",
                error_code=ToolErrorCode.INVALID_URL.value,
            )

        config = get_config()
        request = self._build_fetch_request(parameters, config, url)
        block_reason = await blocked_url_target_reason(
            request.url,
            allow_private_network=request.allow_private_network,
            private_network_allowlist=request.private_network_allowlist,
            allow_rfc2544_benchmark_range=request.allow_rfc2544_benchmark_range,
        )
        if block_reason:
            return self._blocked_url_result(request.url, block_reason)

        cached = self._build_cached_fetch_result_for_request(request)
        if cached is not None:
            return cached

        fetch_params = self._provider_fetch_params(request)
        if request.mode != "auto":
            return await self._handle_direct_fetch(request, fetch_params)
        return await self._handle_auto_fetch(request, fetch_params)

    def _build_fetch_request(
        self,
        parameters: Dict[str, Any],
        config: Any,
        url: str,
    ) -> _FetchRequest:
        web_fetch_config = getattr(getattr(config, "tools", None), "web_fetch", None)
        return _FetchRequest(
            url,
            mode=str(parameters.get("mode", "auto")).strip().lower(),
            output_format=str(parameters.get("output_format", "markdown")).strip().lower(),
            timeout_ms=int(parameters.get("timeout_ms", 15000)),
            wait_until=str(parameters.get("wait_until", "networkidle")).strip().lower(),
            max_chars=int(parameters.get("max_chars", 20000)),
            include_metadata=bool(parameters.get("include_metadata", True)),
            allow_rfc2544_benchmark_range=bool(
                getattr(web_fetch_config, "allow_rfc2544_benchmark_range", False)
            ),
            allow_private_network=bool(getattr(web_fetch_config, "allow_private_network", False)),
            private_network_allowlist=list(
                getattr(web_fetch_config, "private_network_allowlist", []) or []
            ),
            proxy_url=config.network.proxy_url(),
        )

    @staticmethod
    def _blocked_url_result(url: str, block_reason: str) -> ToolResult:
        parsed_host = (urlparse(url).hostname or "").strip().strip("[]")
        try:
            ipaddress.ip_address(parsed_host)
            is_domain = False
        except ValueError:
            is_domain = True
        fake_ip_compatibility_available = is_domain and "RFC 2544 benchmark range" in block_reason
        guidance = (
            "Ask the user to enable trusted TUN fake-IP compatibility, then retry once. "
            "Do not enable private-network fetch or broaden the private allowlist."
            if fake_ip_compatibility_available
            else (
                "Do not retry this URL with web-fetch. Ask the user to provide "
                "a public URL or use an explicit local tool/workspace path if "
                "they intended to inspect local resources."
            )
        )
        return ToolResult(
            success=False,
            error=f"Blocked web-fetch URL: {block_reason}",
            error_code=ToolErrorCode.POLICY_BLOCKED.value,
            data={
                "url": url,
                "reason": block_reason,
                "reason_code": (
                    RFC2544_FAKE_IP_COMPATIBILITY_REQUIRED
                    if fake_ip_compatibility_available
                    else ToolErrorCode.POLICY_BLOCKED.value
                ),
                "llm_guidance": guidance,
            },
        )

    @staticmethod
    def _provider_fetch_params(request: _FetchRequest) -> dict[str, Any]:
        return {
            "url": request.url,
            "timeout_ms": request.timeout_ms,
            "wait_until": request.wait_until,
            "proxy_url": request.proxy_url,
            "allow_rfc2544_benchmark_range": request.allow_rfc2544_benchmark_range,
            "allow_private_network": request.allow_private_network,
            "private_network_allowlist": request.private_network_allowlist,
        }

    async def _handle_direct_fetch(
        self,
        request: _FetchRequest,
        fetch_params: dict[str, Any],
    ) -> ToolResult:
        provider_result = await self.execute_with_provider(request.mode, fetch_params)
        if not provider_result.success:
            return provider_result
        output = self._build_and_record_output(
            request,
            provider_data=provider_result.data,
            mode=request.mode,
            attempts=[request.mode],
        )
        return output

    async def _handle_auto_fetch(
        self,
        request: _FetchRequest,
        fetch_params: dict[str, Any],
    ) -> ToolResult:
        attempts: List[str] = []

        http_result = await self.execute_with_provider("http", fetch_params)
        attempts.append("http")
        if http_result.success and http_result.data:
            html = str(http_result.data.get("html", ""))
            text = self._to_text(html)
            if not self._looks_like_js_shell(html, text):
                return self._build_and_record_output(
                    request,
                    provider_data=http_result.data,
                    mode="auto",
                    attempts=attempts,
                )

        browser_result = await self.execute_with_provider("browser", fetch_params)
        attempts.append("browser")
        if browser_result.success and browser_result.data:
            return self._build_and_record_output(
                request,
                provider_data=browser_result.data,
                mode="auto",
                attempts=attempts,
            )

        curl_result = await self.execute_with_provider("curl", fetch_params)
        attempts.append("curl")
        if curl_result.success and curl_result.data:
            return self._build_and_record_output(
                request,
                provider_data=curl_result.data,
                mode="auto",
                attempts=attempts,
            )

        return self._auto_fetch_failure_result(
            attempts=attempts,
            http_result=http_result,
            browser_result=browser_result,
            curl_result=curl_result,
        )

    def _build_and_record_output(
        self,
        request: _FetchRequest,
        *,
        provider_data: dict[str, Any],
        mode: str,
        attempts: list[str],
    ) -> ToolResult:
        output = self._build_output(
            provider_data=provider_data,
            output_format=request.output_format,
            max_chars=request.max_chars,
            include_metadata=request.include_metadata,
            mode=mode,
            attempts=attempts,
        )
        self._record_fetch_result_for_request(request, output)
        return output

    @staticmethod
    def _auto_fetch_failure_result(
        *,
        attempts: list[str],
        http_result: ToolResult,
        browser_result: ToolResult,
        curl_result: ToolResult,
    ) -> ToolResult:
        if (
            http_result.success is False
            and browser_result.success is False
            and curl_result.success is False
        ):
            return ToolResult(
                success=False,
                error=(
                    f"All web-fetch providers failed. "
                    f"http={http_result.error}; browser={browser_result.error}; curl={curl_result.error}"
                ),
                error_code=ToolErrorCode.ALL_PROVIDERS_FAILED.value,
                data={"attempts": attempts},
            )
        return ToolResult(
            success=False,
            error="Failed to fetch web page content",
            error_code=ToolErrorCode.FETCH_FAILED.value,
            data={"attempts": attempts},
        )

    def _build_cached_fetch_result_for_request(self, request: _FetchRequest) -> ToolResult | None:
        return self._build_cached_fetch_result(
            url=request.url,
            mode=request.mode,
            output_format=request.output_format,
            wait_until=request.wait_until,
            timeout_ms=request.timeout_ms,
            max_chars=request.max_chars,
            include_metadata=request.include_metadata,
        )

    def _record_fetch_result_for_request(
        self,
        request: _FetchRequest,
        result: ToolResult,
    ) -> None:
        self._record_fetch_result(
            url=request.url,
            mode=request.mode,
            output_format=request.output_format,
            wait_until=request.wait_until,
            timeout_ms=request.timeout_ms,
            max_chars=request.max_chars,
            include_metadata=request.include_metadata,
            result=result,
        )

    def _is_valid_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _build_cached_fetch_result(
        self,
        *,
        url: str,
        mode: str,
        output_format: str,
        wait_until: str,
        timeout_ms: int,
        max_chars: int,
        include_metadata: bool,
    ) -> ToolResult | None:
        self._prune_fetch_cache()
        cache_key = self._fetch_cache_key(
            url=url,
            mode=mode,
            output_format=output_format,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
            max_chars=max_chars,
            include_metadata=include_metadata,
        )
        cached = self._fetch_cache.get(cache_key)
        if cached is None:
            return None
        _, data = cached
        payload = copy.deepcopy(data)
        payload["cached"] = True
        payload["cache_ttl_seconds"] = int(_FETCH_CACHE_TTL_SECONDS)
        return ToolResult(success=True, data=payload)

    def _record_fetch_result(
        self,
        *,
        url: str,
        mode: str,
        output_format: str,
        wait_until: str,
        timeout_ms: int,
        max_chars: int,
        include_metadata: bool,
        result: ToolResult,
    ) -> None:
        if not result.success or not isinstance(result.data, dict):
            return
        cache_key = self._fetch_cache_key(
            url=url,
            mode=mode,
            output_format=output_format,
            wait_until=wait_until,
            timeout_ms=timeout_ms,
            max_chars=max_chars,
            include_metadata=include_metadata,
        )
        payload = copy.deepcopy(result.data)
        payload.pop("cached", None)
        self._fetch_cache[cache_key] = (time.time(), payload)

    def _prune_fetch_cache(self) -> None:
        cutoff = time.time() - _FETCH_CACHE_TTL_SECONDS
        stale_keys = [key for key, (seen_at, _) in self._fetch_cache.items() if seen_at < cutoff]
        for key in stale_keys:
            self._fetch_cache.pop(key, None)

    @staticmethod
    def _fetch_cache_key(
        *,
        url: str,
        mode: str,
        output_format: str,
        wait_until: str,
        timeout_ms: int,
        max_chars: int,
        include_metadata: bool,
    ) -> tuple[str, str, str, str, int, int, bool]:
        return (
            str(url).strip(),
            str(mode).strip().lower(),
            str(output_format).strip().lower(),
            str(wait_until).strip().lower(),
            int(timeout_ms),
            int(max_chars),
            bool(include_metadata),
        )

    def _build_output(
        self,
        provider_data: Dict[str, Any],
        output_format: str,
        max_chars: int,
        include_metadata: bool,
        mode: str,
        attempts: List[str],
    ) -> ToolResult:
        html = str(provider_data.get("html", ""))
        if output_format == "html":
            content = html
        elif output_format == "text":
            content = self._to_text(html)
        else:
            content = self._to_markdown(html)

        content = content.strip()
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars]

        if not include_metadata:
            return ToolResult(success=True, data={"content": content})

        return ToolResult(
            success=True,
            data={
                "url": provider_data.get("url"),
                "final_url": provider_data.get("final_url"),
                "title": provider_data.get("title", ""),
                "provider": provider_data.get("provider"),
                "status_code": provider_data.get("status_code"),
                "content_type": provider_data.get("content_type", ""),
                "rendered": bool(provider_data.get("rendered", False)),
                "mode": mode,
                "attempts": attempts,
                "output_format": output_format,
                "content": content,
            },
        )

    def _looks_like_js_shell(self, html: str, text: str) -> bool:
        html_lower = html.lower()
        text_len = len(text.strip())
        shell_markers = [
            'id="app"',
            "id='app'",
            'id="root"',
            "id='root'",
            'id="__next"',
            "id='__next'",
            "enable javascript",
            "<noscript",
            "webpack",
            "__nuxt",
        ]
        marker_hit = any(marker in html_lower for marker in shell_markers)
        script_count = len(re.findall(r"<script\b", html_lower))
        return (text_len < 180 and script_count >= 3) or (marker_hit and text_len < 600)

    def _to_text(self, html: str) -> str:
        cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
        cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
        cleaned = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", cleaned)
        cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
        cleaned = re.sub(r"(?i)</p\s*>", "\n", cleaned)
        cleaned = re.sub(r"(?i)</div\s*>", "\n", cleaned)
        cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
        cleaned = unescape(cleaned)
        cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
        cleaned = re.sub(r"\n\s+\n", "\n\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _to_markdown(self, html: str) -> str:
        content = html
        content = re.sub(r"(?is)<script.*?>.*?</script>", " ", content)
        content = re.sub(r"(?is)<style.*?>.*?</style>", " ", content)
        content = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", content)

        for level in range(6, 0, -1):
            pattern = rf"(?is)<h{level}[^>]*>(.*?)</h{level}>"
            prefix = "#" * level
            content = re.sub(
                pattern, lambda m: f"\n{prefix} {self._to_text(m.group(1))}\n", content
            )

        content = re.sub(
            r"(?is)<li[^>]*>(.*?)</li>", lambda m: f"\n- {self._to_text(m.group(1))}", content
        )
        content = re.sub(r"(?i)<br\s*/?>", "\n", content)
        content = re.sub(r"(?i)</p\s*>", "\n\n", content)
        content = re.sub(r"(?i)</div\s*>", "\n", content)
        content = re.sub(r"(?is)<[^>]+>", " ", content)
        content = unescape(content)
        content = re.sub(r"[ \t\r\f\v]+", " ", content)
        content = re.sub(r"\n[ \t]+", "\n", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()
