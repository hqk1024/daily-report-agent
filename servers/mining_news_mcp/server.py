"""MCP server for mining news aggregation."""

import asyncio
import json
from datetime import datetime

import httpx
from servers.mcp_base import Server


async def search_news(query: str, days: int = 7) -> str:
    """Search for mining-related news articles."""
    from ddgs import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(f"{query} mining", max_results=10):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })

    return json.dumps(
        {"query": query, "days": days, "results": results, "timestamp": datetime.now().isoformat()},
        ensure_ascii=False, indent=2,
    )


async def fetch_article(url: str) -> str:
    """Fetch and extract text content from a news article URL."""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()

        import re
        text = resp.text
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        return json.dumps({"url": url, "content": text[:8000], "length": len(text)},
                          ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "url": url})


server = Server("mining-news-mcp")


@server.tool(
    name="search_news",
    description="Search for mining industry news articles by keyword and time range",
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keyword, e.g. lithium, Pilbara, copper"},
            "days": {"type": "integer", "description": "Lookback period in days (default 7)"},
        },
        "required": ["query"],
    },
)
async def handler_search_news(query: str, days: int = 7) -> str:
    return await search_news(query, days)


@server.tool(
    name="fetch_article",
    description="Fetch and extract the full text content of a news article from its URL",
    inputSchema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL of the article to fetch"},
        },
        "required": ["url"],
    },
)
async def handler_fetch_article(url: str) -> str:
    return await fetch_article(url)


if __name__ == "__main__":
    asyncio.run(server.run())
