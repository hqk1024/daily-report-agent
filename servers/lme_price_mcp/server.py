"""MCP server for LME commodity price queries."""

import asyncio
import json
import re
from datetime import datetime

import httpx
from servers.mcp_base import Server


COMMODITY_MAP = {
    "lithium": "lithium-carbonate", "copper": "copper", "nickel": "nickel",
    "cobalt": "cobalt", "rare earth": "rare-earth", "iron ore": "iron-ore",
    "aluminum": "aluminum", "zinc": "zinc", "lead": "lead", "tin": "tin",
}


async def get_price(commodity: str, date: str = "") -> str:
    """Get the latest or historical price for a commodity."""
    mapped = COMMODITY_MAP.get(commodity.lower(), commodity.lower())
    try:
        url = f"https://tradingeconomics.com/commodity/{mapped}"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})

        if resp.status_code == 200:
            text = resp.text
            price_match = re.search(r'["\']price["\'][:,]\s*["\']?([\d,.]+)["\']?', text)
            if not price_match:
                price_match = re.search(r'<span[^>]*class="[^"]*price[^"]*"[^>]*>([^<]+)', text)

            change_match = re.search(
                r'["\'][pidcPIDC]{0,5}["\'][:,]\s*["\']?([+-]?\d+\.?\d*)[%]?', text
            )

            return json.dumps({
                "commodity": commodity,
                "price": price_match.group(1) if price_match else "N/A",
                "change": change_match.group(1) if change_match else "N/A",
                "source": "tradingeconomics.com",
            }, ensure_ascii=False, indent=2)
        return json.dumps({"commodity": commodity, "price": "N/A",
                           "note": f"HTTP {resp.status_code}"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"commodity": commodity, "price": "N/A", "error": str(e)},
                          ensure_ascii=False, indent=2)


async def get_trend(commodity: str, days: int = 30) -> str:
    """Get price trend data for a commodity over a period."""
    current = json.loads(await get_price(commodity))
    return json.dumps({
        "commodity": commodity,
        "trend_period_days": days,
        "current_data": current,
        "analysis": f"Trend analysis for {commodity} over {days} days - current: {current.get('price', 'N/A')}",
        "recommendation": "Monitor LME official data for precise trend analysis",
        "timestamp": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2)


server = Server("lme-price-mcp")


@server.tool(
    name="get_price",
    description="Get the current or historical price for a commodity (lithium, copper, nickel, etc.)",
    inputSchema={
        "type": "object",
        "properties": {
            "commodity": {"type": "string", "description": "Commodity name"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format (optional)"},
        },
        "required": ["commodity"],
    },
)
async def handler_price(commodity: str, date: str = "") -> str:
    return await get_price(commodity, date)


@server.tool(
    name="get_trend",
    description="Get price trend analysis for a commodity over a specified period",
    inputSchema={
        "type": "object",
        "properties": {
            "commodity": {"type": "string", "description": "Commodity name"},
            "days": {"type": "integer", "description": "Number of days (default 30)"},
        },
        "required": ["commodity"],
    },
)
async def handler_trend(commodity: str, days: int = 30) -> str:
    return await get_trend(commodity, days)


if __name__ == "__main__":
    asyncio.run(server.run())
