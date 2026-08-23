"""
Curl Fetch Provider

Fallback fetch provider using curl command.
"""
import asyncio
import os
from typing import Any, Dict

from magi_plugin_sdk.subprocess import hidden_process_kwargs
from ..base import Provider, ProviderConfig


class CurlFetchProvider(Provider):
    """Fallback provider using curl."""

    @property
    def name(self) -> str:
        return "curl"

    @property
    def display_name(self) -> str:
        return "Curl Fetch"

    def is_ready(self, config: ProviderConfig) -> bool:
        """curl mode is always available when curl exists in PATH."""
        return True

    async def execute(self, params: Dict[str, Any], config: ProviderConfig) -> Dict[str, Any]:
        """Execute curl-based web fetch."""
        url = str(params["url"]).strip()
        timeout_ms = int(params.get("timeout_ms", 15000))
        timeout_sec = max(1, timeout_ms // 1000)
        proxy_url = str(params.get("proxy_url") or "").strip()
        user_agent = str(
            params.get(
                "user_agent",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
        )

        command = [
            "curl",
            "-sS",
            "--max-time",
            str(timeout_sec),
            "-A",
            user_agent,
        ]
        if proxy_url:
            command.extend(["--proxy", proxy_url])
        else:
            command.extend(["--noproxy", "*"])
        command.append(url)

        env = os.environ.copy()
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
        ):
            env.pop(key, None)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            **hidden_process_kwargs(),
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_text = stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"curl fetch failed (exit={process.returncode}): {error_text}")

        html = stdout.decode("utf-8", errors="ignore")
        if not html.strip():
            raise RuntimeError("curl fetch returned empty content")

        return {
            "provider": self.name,
            "url": url,
            "final_url": url,
            "status_code": None,
            "content_type": "",
            "title": "",
            "html": html,
            "rendered": False,
        }
