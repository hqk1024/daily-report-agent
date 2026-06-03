"""MCP server for commodity price queries via akshare (primary) + yfinance fallback."""

import asyncio
import json
import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
from servers.mcp_base import Server


SHFE_SYMBOL = {
    "copper": "CU",
    "aluminum": "AL",
    "zinc": "ZN",
    "nickel": "NI",
    "tin": "SN",
    "lead": "PB",
    "gold": "AU",
    "silver": "AG",
    "lithium": "LC",
    "lithium carbonate": "LC",
    "silicon": "SI",
}

YF_TICKER = {
    "cobalt": "COB=F",
    "rare earth": "REMX",
    "iron ore": "TIO=F",
    "platinum": "PL=F",
    "palladium": "PA=F",
}

COMMODITY_CN = {
    "copper": "铜", "aluminum": "铝", "zinc": "锌", "nickel": "镍",
    "tin": "锡", "lead": "铅", "gold": "金", "silver": "银",
    "lithium": "碳酸锂", "lithium carbonate": "碳酸锂", "silicon": "工业硅",
}


def _get_shfe_price(commodity: str) -> dict | None:
    """Get spot price from Shanghai Futures Exchange via akshare."""
    symbol = SHFE_SYMBOL.get(commodity.lower())
    if not symbol:
        return None
    try:
        date_str = datetime.now().strftime("%Y%m%d")
        df = ak.futures_spot_price(date=date_str, vars_list=[symbol])
        if df.empty:
            return None
        row = df.iloc[0]
        return {
            "commodity": commodity,
            "symbol": symbol,
            "spot_price": float(row["spot_price"]),
            "near_contract": str(row["near_contract"]),
            "near_contract_price": float(row["near_contract_price"]),
            "dominant_contract": str(row["dominant_contract"]),
            "dominant_contract_price": float(row["dominant_contract_price"]),
            "near_basis": float(row["near_basis"]),
            "change_pct": float(row.get("near_basis_rate", 0)) * 100,
            "currency": "CNY",
            "source": "上海期货交易所 (SHFE)",
            "unit": _get_unit(commodity),
        }
    except Exception:
        return None


def _get_yf_price(commodity: str) -> dict | None:
    """Get ETF/futures price from Yahoo Finance (fallback for non-SHFE metals)."""
    ticker_symbol = YF_TICKER.get(commodity.lower())
    if not ticker_symbol:
        return None
    try:
        import yfinance as yf
        from yfinance.exceptions import YFRateLimitError
        for attempt in range(2):
            try:
                ticker = yf.Ticker(ticker_symbol)
                fast = ticker.fast_info
                return {
                    "commodity": commodity,
                    "ticker": ticker_symbol,
                    "price": getattr(fast, "lastPrice", None),
                    "previous_close": getattr(fast, "previousClose", None),
                    "currency": str(getattr(fast, "currency", "USD")),
                    "source": "Yahoo Finance",
                }
            except YFRateLimitError:
                time.sleep((attempt + 1) * 5)
                continue
    except Exception:
        pass
    return None


def _get_unit(commodity: str) -> str:
    units = {
        "copper": "元/吨", "aluminum": "元/吨", "zinc": "元/吨",
        "nickel": "元/吨", "tin": "元/吨", "lead": "元/吨",
        "gold": "元/克", "silver": "元/千克",
        "lithium": "元/吨", "lithium carbonate": "元/吨", "silicon": "元/吨",
    }
    return units.get(commodity.lower(), "")


def _get_ticker_info(commodity: str) -> dict:
    """Fetch price data — SHFE first, Yahoo Finance fallback."""
    name = commodity.lower()

    shfe_data = _get_shfe_price(name)
    if shfe_data:
        return shfe_data

    yf_data = _get_yf_price(name)
    if yf_data:
        return yf_data

    return {
        "commodity": commodity,
        "error": f"No data source available for '{commodity}'. "
                 f"Supported SHFE metals: {', '.join(SHFE_SYMBOL.keys())}. "
                 f"Supported via Yahoo: {', '.join(YF_TICKER.keys())}.",
    }


async def get_price(commodity: str, date: str = "") -> str:
    """Get the latest price for a commodity."""
    info = _get_ticker_info(commodity)
    info["timestamp"] = datetime.now().isoformat()
    info["date"] = date if date else datetime.now().strftime("%Y-%m-%d")
    return json.dumps(info, ensure_ascii=False, indent=2)


async def get_trend(commodity: str, days: int = 30) -> str:
    """Get price trend for a commodity."""
    name = commodity.lower()
    symbol = SHFE_SYMBOL.get(name)

    if symbol:
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            df = ak.futures_spot_price(
                date=end,
                vars_list=[symbol],
            )
            current = _get_ticker_info(commodity)
            return json.dumps({
                "commodity": commodity,
                "symbol": symbol,
                "market": "上海期货交易所 (SHFE)",
                "trend_period_days": days,
                "current": current,
                "note": "Historical price data available via SHFE official website.",
                "timestamp": datetime.now().isoformat(),
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({
                "commodity": commodity, "trend_period_days": days, "error": str(e),
            }, ensure_ascii=False, indent=2)

    ticker_symbol = YF_TICKER.get(name)
    if ticker_symbol:
        try:
            import yfinance as yf
            from yfinance.exceptions import YFRateLimitError
            end = datetime.now()
            start = end - timedelta(days=days)
            ticker = yf.Ticker(ticker_symbol)

            hist = None
            for attempt in range(2):
                try:
                    hist = ticker.history(start=start, end=end, interval="1d")
                    break
                except YFRateLimitError:
                    time.sleep((attempt + 1) * 5)

            if hist is not None and not hist.empty:
                prices = [
                    {
                        "date": idx.strftime("%Y-%m-%d"),
                        "close": round(row["Close"], 4),
                    }
                    for idx, row in hist.iterrows()
                ]
                current = _get_ticker_info(commodity)
                return json.dumps({
                    "commodity": commodity, "ticker": ticker_symbol,
                    "trend_period_days": days, "current": current,
                    "prices": prices,
                    "timestamp": datetime.now().isoformat(),
                }, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return json.dumps({
        "commodity": commodity, "trend_period_days": days,
        "error": "Historical data unavailable for this commodity.",
    }, ensure_ascii=False, indent=2)


server = Server("lme-price-mcp")


@server.tool(
    name="get_price",
    description="Get the current price for a commodity (copper, aluminum, nickel, zinc, lead, tin, gold, silver from SHFE; lithium, cobalt, rare earth, iron ore, platinum, palladium from Yahoo Finance)",
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
    description="Get price trend data for a commodity over a specified period",
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
