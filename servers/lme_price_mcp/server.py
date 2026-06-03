"""MCP server for commodity price queries via Yahoo Finance."""

import asyncio
import json
import time
from datetime import datetime, timedelta

import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from servers.mcp_base import Server


TICKER_MAP = {
    "copper": "HG=F",
    "aluminum": "ALI=F",
    "nickel": "NI=F",
    "zinc": "ZINC=F",
    "lead": "LEAD=F",
    "tin": "TIN=F",
    "iron ore": "TIO=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "platinum": "PL=F",
    "palladium": "PA=F",
    "lithium": "LIT",
    "cobalt": "COB=F",
    "rare earth": "REMX",
}


def _fetch_fast_info(ticker_symbol: str, retries: int = 3) -> dict:
    """Fetch yfinance fast_info with retry on rate limit.

    fast_info is lazy — network calls happen when accessing individual
    fields, not when creating the Ticker. Rate limit errors surface
    during field access, so the entire fetch + field extraction must
    be retried as a unit.
    """
    last_error = None
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(ticker_symbol)
            fast = ticker.fast_info
            data = {}
            for k in fast.keys():
                data[k] = getattr(fast, k, None)
            return data
        except YFRateLimitError:
            last_error = "Rate limited by Yahoo Finance"
            time.sleep((attempt + 1) * 5)
            continue
        except Exception as e:
            last_error = str(e)
            time.sleep((attempt + 1) * 3)
            continue
    return {"_error": last_error or "Unknown error after retries"}


def _get_ticker_info(commodity: str) -> dict:
    """Fetch ticker data for a commodity."""
    ticker_symbol = TICKER_MAP.get(commodity.lower(), commodity.upper())
    fast_data = _fetch_fast_info(ticker_symbol)
    if "_error" in fast_data:
        return {"commodity": commodity, "ticker": ticker_symbol, "error": fast_data["_error"]}

    info = {
        "commodity": commodity,
        "ticker": ticker_symbol,
        "price": fast_data.get("lastPrice"),
        "previous_close": fast_data.get("previousClose"),
        "day_high": fast_data.get("dayHigh"),
        "day_low": fast_data.get("dayLow"),
        "year_high": fast_data.get("yearHigh"),
        "year_low": fast_data.get("yearLow"),
        "currency": str(fast_data.get("currency", "USD")),
        "change_pct": None,
    }
    if info["price"] and info["previous_close"]:
        change = info["price"] - info["previous_close"]
        info["change"] = round(change, 4)
        info["change_pct"] = round((change / info["previous_close"]) * 100, 2)
    return info


async def get_price(commodity: str, date: str = "") -> str:
    """Get the latest price for a commodity."""
    info = _get_ticker_info(commodity)
    info["source"] = "Yahoo Finance"
    info["timestamp"] = datetime.now().isoformat()
    info["date"] = date if date else datetime.now().strftime("%Y-%m-%d")
    return json.dumps(info, ensure_ascii=False, indent=2)


async def get_trend(commodity: str, days: int = 30) -> str:
    """Get price trend for a commodity over a period."""
    ticker_symbol = TICKER_MAP.get(commodity.lower(), commodity.upper())
    try:
        end = datetime.now()
        start = end - timedelta(days=days)
        ticker = yf.Ticker(ticker_symbol)

        for attempt in range(3):
            try:
                hist = ticker.history(start=start, end=end, interval="1d")
                break
            except YFRateLimitError:
                time.sleep((attempt + 1) * 5)
                continue

        if hist is None or hist.empty:
            return json.dumps({
                "commodity": commodity, "ticker": ticker_symbol,
                "trend_period_days": days,
                "error": "No historical data available",
            }, ensure_ascii=False, indent=2)

        prices = []
        for idx, row in hist.iterrows():
            prices.append({
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(row["Open"], 4),
                "high": round(row["High"], 4),
                "low": round(row["Low"], 4),
                "close": round(row["Close"], 4),
                "volume": int(row["Volume"]),
            })

        current = _get_ticker_info(commodity)
        first_close = prices[0]["close"] if prices else 0
        last_close = prices[-1]["close"] if prices else 0
        change_pct = round(((last_close - first_close) / first_close) * 100, 2) if first_close else 0

        return json.dumps({
            "commodity": commodity, "ticker": ticker_symbol,
            "trend_period_days": days,
            "current": current, "change_period_pct": change_pct,
            "prices": prices,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "commodity": commodity, "trend_period_days": days, "error": str(e),
        }, ensure_ascii=False, indent=2)


server = Server("lme-price-mcp")


@server.tool(
    name="get_price",
    description="Get the current price for a commodity (copper, aluminum, nickel, zinc, lead, tin, iron ore, gold, silver, platinum, palladium, lithium, cobalt, rare earth)",
    inputSchema={
        "type": "object",
        "properties": {
            "commodity": {"type": "string", "description": "Commodity name, e.g. copper, lithium, nickel"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format (optional)"},
        },
        "required": ["commodity"],
    },
)
async def handler_price(commodity: str, date: str = "") -> str:
    return await get_price(commodity, date)


@server.tool(
    name="get_trend",
    description="Get price trend chart data for a commodity over a specified period",
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
