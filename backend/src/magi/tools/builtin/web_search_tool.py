"""
Web Search Tool - Search web using multiple providers
"""
import os
import aiohttp
from typing import Dict, Any, List, Optional
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, Parametertype


class WebSearchTool(Tool):
    """
    Web Search Tool

    Search the web using multiple providers (Brave, Perplexity, Tavily).
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = ToolSchema(
            name="web-search",
            description="Search the web for information. Supports multiple search providers.",
            category="web",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="query",
                    type=Parametertype.strING,
                    description="The search query",
                    required=True,
                ),
                ToolParameter(
                    name="provider",
                    type=Parametertype.strING,
                    description="Search provider: 'brave', 'perplexity', or 'tavily'",
                    required=False,
                    default="brave",
                    enum=["brave", "perplexity", "tavily"],
                ),
                ToolParameter(
                    name="num_results",
                    type=Parametertype.intEGER,
                    description="Number of results to return",
                    required=False,
                    default=10,
                    min_value=1,
                    max_value=50,
                ),
            ],
            examples=[
                {
                    "input": {"query": "latest AI news", "provider": "brave"},
                    "output": "Returns search results from Brave",
                },
                {
                    "input": {"query": "Python async programming", "provider": "perplexity", "num_results": 5},
                    "output": "Returns 5 search results from Perplexity",
                },
            ],
            timeout=30,
            retry_on_failure=True,
            max_retries=2,
            dangerous=False,
            tags=["web", "search", "information"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute web search"""
        query = parameters["query"]
        provider = parameters.get("provider", "brave")
        num_results = parameters.get("num_results", 10)

        try:
            if provider == "brave":
                results = await self._search_brave(query, num_results)
            elif provider == "perplexity":
                results = await self._search_perplexity(query, num_results)
            elif provider == "tavily":
                results = await self._search_tavily(query, num_results)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknotttwn provider: {provider}",
                    error_code="INVALid_PROVidER",
                )

            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "provider": provider,
                    "results": results,
                    "total": len(results),
                },
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="SEARCH_error",
            )

    async def _search_brave(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Search using Brave Search API"""
        api_key = os.environ.get("BRAVE_API_key")
        if not api_key:
            raise Valueerror("BRAVE_API_key environment variable not set")

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }
        params = {
            "q": query,
            "count": num_results,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Brave API error: {response.status} - {error_text}")

                data = await response.json()

        results = []
        web_results = data.get("web", {}).get("results", [])

        for item in web_results[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "source": item.get("source", ""),
            })

        return results

    async def _search_perplexity(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Search using Perplexity API"""
        api_key = os.environ.get("PERPLexitY_API_key")
        if not api_key:
            raise Valueerror("PERPLexitY_API_key environment variable not set")

        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-type": "application/json",
        }
        payload = {
            "model": "llama-3.1-sonar-small-128k-online",
            "messages": [
                {
                    "role": "system",
                    "content": f"Return the top {num_results} search results. Format each result as: Title, url, Description. Be concise."
                },
                {
                    "role": "user",
                    "content": query,
                }
            ],
            "max_tokens": 2000,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Perplexity API error: {response.status} - {error_text}")

                data = await response.json()

        # Parse Perplexity response into structured results
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Try to parse citations if available
        results = []
        citations = data.get("citations", [])

        if citations:
            for i, citation in enumerate(citations[:num_results]):
                results.append({
                    "title": f"Result {i + 1}",
                    "url": citation,
                    "description": "See citation for details",
                    "source": "perplexity",
                })
        else:
            # Return the content as a single result
            results.append({
                "title": "Search Results",
                "url": "",
                "description": content,
                "source": "perplexity",
            })

        return results

    async def _search_tavily(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Search using Tavily API"""
        api_key = os.environ.get("TAVILY_API_key")
        if not api_key:
            raise Valueerror("TAVILY_API_key environment variable not set")

        url = "https://api.tavily.com/search"
        headers = {
            "Content-type": "application/json",
        }
        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": num_results,
            "include_answer": True,
            "include_raw_content": False,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Tavily API error: {response.status} - {error_text}")

                data = await response.json()

        results = []
        tavily_results = data.get("results", [])

        for item in tavily_results[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("content", ""),
                "source": item.get("source", ""),
                "score": item.get("score"),
            })

        # Include answer if available
        if data.get("answer"):
            results.insert(0, {
                "title": "AI Answer",
                "url": "",
                "description": data["answer"],
                "source": "tavily-ai",
            })

        return results
