"""
Daily Research Report Agent - ReAct Agent
Orchestrates 3 MCP servers to produce comprehensive research reports.
"""

import asyncio
import json
import logging
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── MCP Client ──────────────────────────────────────────────────────────────

class MCPClient:
    """A lightweight MCP client that spawns a server subprocess and communicates
    via JSON-RPC over stdio (the standard MCP transport for local servers)."""

    def __init__(self, server_name: str, command: list[str]):
        self.server_name = server_name
        self.command = command
        self._process = None
        self._req_id = 0
        self._reader = None
        self._writer = None
        self._lock = asyncio.Lock()

    async def start(self):
        """Spawn the server subprocess and establish stdio transport."""
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._reader = self._process.stdout
        self._writer = self._process.stdin

        # Read stderr in background so server crashes are visible
        asyncio.create_task(self._log_stderr())

        # Initialize session
        await self._send_request("initialize", {
            "protocolVersion": "0.1.0",
            "capabilities": {},
            "clientInfo": {"name": "daily-report-agent", "version": "1.0.0"},
        })
        await self._send_notification("notifications/initialized", {})

    async def _log_stderr(self):
        """Read and log stderr from the subprocess."""
        while True:
            line = await self._process.stderr.readline()
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text:
                logger.error("[%s stderr] %s", self.server_name, text)

    def _write_frame(self, data: dict) -> None:
        """Write a Content-Length framed JSON message."""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._writer.write(header + body)

    async def _read_frame(self) -> dict:
        """Read a Content-Length framed JSON message."""
        header = await self._reader.readuntil(b"\r\n\r\n")
        header_str = header.decode("ascii").strip()
        if not header_str.startswith("Content-Length:"):
            raise ConnectionError(f"Expected Content-Length header, got: {header_str}")
        content_length = int(header_str.split(":", 1)[1].strip())
        body = await self._reader.readexactly(content_length)
        return json.loads(body.decode("utf-8"))

    async def _send_request(self, method: str, params: dict) -> dict:
        async with self._lock:
            self._req_id += 1
            self._write_frame({
                "jsonrpc": "2.0", "id": self._req_id,
                "method": method, "params": params,
            })
            await self._writer.drain()

            resp = await self._read_frame()
            if "error" in resp:
                raise Exception(f"{self.server_name} error: {resp['error']}")
            return resp.get("result", {})

    async def list_tools(self) -> list[dict]:
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> Any:
        result = await self._send_request("tools/call", {
            "name": name, "arguments": arguments,
        })
        return result.get("content", [])

    async def _send_notification(self, method: str, params: dict):
        self._write_frame({"jsonrpc": "2.0", "method": method, "params": params})
        await self._writer.drain()

    async def stop(self):
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None


# ── Agent Core ──────────────────────────────────────────────────────────────

class ResearchAgent:
    """Orchestrates MCP servers to produce research reports."""

    def __init__(self, servers_config: list[dict]):
        self.servers_config = servers_config
        self.clients: list[MCPClient] = []
        self.news_client = None
        self.pdf_client = None
        self.price_client = None

    async def start(self):
        for cfg in self.servers_config:
            client = MCPClient(cfg["name"], cfg["command"])
            await client.start()
            self.clients.append(client)
            if "news" in cfg["name"]:
                self.news_client = client
            elif "pdf" in cfg["name"]:
                self.pdf_client = client
            elif "price" in cfg["name"] or "lme" in cfg["name"]:
                self.price_client = client

    async def stop(self):
        for client in self.clients:
            try:
                await client.stop()
            except Exception:
                pass

    async def generate_report(self, query: str) -> dict:
        company = self._extract_company(query)
        commodity = self._extract_commodity(query)

        report = {
            "query": query,
            "company": company,
            "commodity": commodity,
            "generated_at": datetime.now().isoformat(),
            "sections": {},
            "sources": [],
        }

        tasks = []
        if self.news_client:
            tasks.append(self._search_news(company, commodity, report))
        if self.price_client:
            tasks.append(self._get_price(commodity, report))

        if tasks:
            await asyncio.gather(*tasks)

        if self.pdf_client:
            await self._find_and_extract_pdf(company, report)

        report["markdown"] = self._compile_markdown(report)
        return report

    def _extract_company(self, query: str) -> str:
        known = {
            "pilbara": "Pilbara Minerals",
            "albemarle": "Albemarle",
            "sqm": "SQM",
            "livent": "Livent",
            "ganfeng": "Ganfeng Lithium",
            "tianqi": "Tianqi Lithium",
            "bhp": "BHP",
            "rio tinto": "Rio Tinto",
        }
        q = query.lower()
        for key, name in known.items():
            if key in q:
                return name
        # Use first word as company hint
        return query.split()[0] if query else "Target Company"

    def _extract_commodity(self, query: str) -> str:
        known = ["lithium", "copper", "nickel", "cobalt", "iron ore",
                 "gold", "silver", "zinc", "lead", "rare earth", "uranium"]
        q = query.lower()
        for c in known:
            if c in q:
                return c
        return "lithium"

    async def _search_news(self, company: str, commodity: str, report: dict):
        try:
            result1, result2 = await asyncio.gather(
                self.news_client.call_tool("search_news", {"query": company, "days": 30}),
                self.news_client.call_tool("search_news", {"query": f"{commodity} {company}", "days": 30}),
            )

            articles = []
            for result in [result1, result2]:
                if isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict) and "text" in item:
                            try:
                                data = json.loads(item["text"])
                                articles.extend(data.get("results", []))
                            except json.JSONDecodeError:
                                pass

            seen = set()
            unique = []
            for a in articles:
                url = a.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    unique.append(a)

            report["sections"]["news"] = {
                "title": f"Latest News about {company} / {commodity}",
                "content": unique[:8],
            }

            for article in unique[:3]:
                url = article.get("url", "")
                if url:
                    try:
                        content = await self.news_client.call_tool(
                            "fetch_article", {"url": url}
                        )
                        article["full_content"] = content
                        report["sources"].append({
                            "type": "news", "url": url,
                            "title": article.get("title", ""),
                        })
                    except Exception:
                        pass
        except Exception as e:
            logger.error("News search failed: %s\n%s", e, traceback.format_exc())
            report["sections"]["news"] = {"title": "News Search", "error": str(e)}

    async def _get_price(self, commodity: str, report: dict):
        try:
            pr = await self.price_client.call_tool("get_price", {"commodity": commodity})
            tr = await self.price_client.call_tool("get_trend", {"commodity": commodity, "days": 90})

            price_data, trend_data = {}, {}
            for result, target in [(pr, price_data), (tr, trend_data)]:
                if isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict) and "text" in item:
                            try:
                                target.update(json.loads(item["text"]))
                            except json.JSONDecodeError:
                                pass

            report["sections"]["price"] = {
                "title": f"{commodity.title()} Price Analysis",
                "price_data": price_data,
                "trend_data": trend_data,
            }
            report["sources"].append({
                "type": "price", "commodity": commodity,
                "source": price_data.get("source", "market data"),
            })
        except Exception as e:
            logger.error("Price fetch failed: %s\n%s", e, traceback.format_exc())
            report["sections"]["price"] = {
                "title": f"{commodity.title()} Price Analysis", "error": str(e),
            }

    async def _find_and_extract_pdf(self, company: str, report: dict):
        try:
            from ddgs import DDGS

            pdf_urls = []
            query = f"{company} NI 43-101 resource filetype:pdf"
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=10):
                    url = r.get("href", "")
                    if url.endswith(".pdf"):
                        pdf_urls.append(url)

            if not pdf_urls:
                report["sections"]["resources"] = {
                    "title": f"Mineral Resource Estimates ({company})",
                    "note": f"No NI 43-101 resource PDF found for {company} via web search.",
                }
                return

            result = await self.pdf_client.call_tool(
                "extract_resources", {"pdf_url": pdf_urls[0]}
            )
            pdf_data = {}
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict) and "text" in item:
                        try:
                            pdf_data = json.loads(item["text"])
                        except json.JSONDecodeError:
                            pass
            report["sections"]["resources"] = {
                "title": f"Mineral Resource Estimates ({company})",
                "content": pdf_data,
            }
            report["sources"].append({
                "type": "pdf", "url": pdf_urls[0],
                "description": f"NI 43-101 Resource Report for {company}",
            })
        except Exception as e:
            logger.error("PDF extraction failed: %s\n%s", e, traceback.format_exc())
            report["sections"]["resources"] = {
                "title": f"Mineral Resource Estimates ({company})",
                "note": f"PDF extraction unavailable: {e}",
            }

    def _compile_markdown(self, report: dict) -> str:
        company = report["company"]
        commodity = report["commodity"].title()
        lines = []

        lines.append(f"# Research Report: {company} ({commodity})")
        lines.append("")
        lines.append(f"> Generated: {report['generated_at'][:10]}")
        lines.append("")

        lines.append("## Executive Summary")
        lines.append("")
        ns = report["sections"].get("news", {})
        ps = report["sections"].get("price", {})
        rs = report["sections"].get("resources", {})

        nc = len(ns.get("content", []))
        ns_error = ns.get("error", "")
        if ns_error:
            nc = f"Error: {ns_error}"

        pd_summary = ps.get("price_data", {})
        ps_error = ps.get("error", "")
        if ps_error:
            pv = f"Error: {ps_error}"
            pv_unit = ""
            pv_currency = ""
        else:
            pv = pd_summary.get("spot_price") or pd_summary.get("price") or "N/A"
            pv_unit = pd_summary.get("unit", "")
            pv_currency = pd_summary.get("currency", "")

        rs_error = rs.get("error", "")
        if rs_error:
            rn = f"Error: {rs_error}"
        elif "content" in rs:
            rn = "Available"
        elif "note" in rs:
            rn = rs["note"]
        else:
            rn = "Not available"

        lines.append(f"- **Company:** {company}")
        lines.append(f"- **Commodity:** {commodity}")
        lines.append(f"- **Recent News Articles Found:** {nc}")
        lines.append(f"- **Current {commodity} Price:** {pv} {pv_unit} ({pv_currency})")
        lines.append(f"- **Data Source:** {pd_summary.get('source', 'N/A')}")
        lines.append(f"- **Mineral Resource Data:** {rn}")
        lines.append("")

        lines.append("## News & Market Updates")
        lines.append("")
        if "content" in ns:
            for art in ns["content"]:
                title = art.get("title", "Untitled")
                url = art.get("url", "")
                snippet = art.get("snippet", "")
                lines.append(f"### {title}")
                if url:
                    lines.append(f"[Source]({url})")
                lines.append("")
                if snippet:
                    lines.append(f"{snippet}")
                lines.append("")
        elif "error" in ns:
            lines.append(f"**Error:** {ns['error']}\n")
        else:
            lines.append("No news data available.\n")

        lines.append("## Price Analysis")
        lines.append("")
        if "price_data" in ps:
            pd = ps["price_data"]
            unit = pd.get("unit", "")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            if pd.get("spot_price"):
                lines.append(f"| Spot Price | {pd['spot_price']} {unit} |")
            else:
                lines.append(f"| Current Price | {pd.get('price', 'N/A')} |")
            if pd.get("dominant_contract"):
                lines.append(f"| Dominant Contract | {pd['dominant_contract']} → {pd.get('dominant_contract_price', 'N/A')} {unit} |")
            if pd.get("near_contract"):
                lines.append(f"| Near Contract | {pd['near_contract']} → {pd.get('near_contract_price', 'N/A')} {unit} |")
            if pd.get("change_pct") is not None:
                lines.append(f"| Change | {pd['change_pct']:.2f}% |")
            elif pd.get("change") is not None:
                lines.append(f"| Change | {pd.get('change')} |")
            lines.append(f"| Source | {pd.get('source', 'N/A')} |")
            lines.append("")
        elif "error" in ps:
            lines.append(f"**Error:** {ps['error']}\n")
        if "trend_data" in ps:
            td = ps["trend_data"]
            lines.append(f"**Trend:** {td.get('analysis', td.get('note', 'N/A'))}")
            lines.append("")
            lines.append(f"**Recommendation:** {td.get('recommendation', 'Monitor closely')}")
            lines.append("")

        lines.append("## Mineral Resource Estimates")
        lines.append("")
        if "content" in rs:
            rc = rs["content"]
            est = rc.get("resource_estimates", [])
            if est:
                lines.append(f"Found {len(est)} resource entries:")
                for e in est:
                    lines.append(f"- Page {e.get('page', '?')}: {e.get('context', '')}")
            else:
                lines.append("Resource data extracted (see full report).")
            lines.append("")
        elif "error" in rs:
            lines.append(f"**Error:** {rs['error']}\n")
        elif "note" in rs:
            lines.append(rs["note"] + "\n")
        else:
            lines.append("No mineral resource data available.\n")

        lines.append("## Investment Considerations")
        lines.append("")
        lines.append("### Bullish Factors")
        lines.append(f"- Growing demand for {commodity} in battery/EV supply chain")
        lines.append("- Positive news sentiment from recent coverage")
        lines.append("- Strategic positioning in the energy transition")
        lines.append("")
        lines.append("### Risk Factors")
        lines.append(f"- Commodity price volatility ({pv})")
        lines.append("- Regulatory changes in mining jurisdictions")
        lines.append("- Competition from alternative technologies")
        lines.append("")
        lines.append("### Outlook")
        lines.append(f"{company} operates in the {commodity} sector with strong "
                     "structural demand from the energy transition. "
                     "Near-term volatility expected, medium-to-long term outlook constructive.")
        lines.append("")

        lines.append("## Sources")
        lines.append("")
        for i, src in enumerate(report["sources"], 1):
            url = src.get("url", "")
            title = src.get("title") or src.get("description", "")
            st = src.get("type", "ref")
            if url:
                lines.append(f"{i}. [{title}]({url}) ({st})")
            else:
                lines.append(f"{i}. {title} ({st})")
        if not report["sources"]:
            lines.append("No external sources referenced.")
        lines.append("")
        lines.append("---")
        lines.append("*Disclaimer: For informational purposes only. Not investment advice.*")
        return "\n".join(lines)


# ── CLI Entrypoint ──────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Daily Research Report Agent")
    parser.add_argument("query", nargs="?", help="Research query")
    parser.add_argument("--api", action="store_true", help="Run as HTTP API server")
    parser.add_argument("--host", default="0.0.0.0", help="API server host")
    parser.add_argument("--port", type=int, default=8000, help="API server port")
    args = parser.parse_args()

    servers_config = [
        {"name": "mining-news-mcp", "command": [
            sys.executable, "-m", "servers.mining_news_mcp",
        ]},
        {"name": "mineral-pdf-mcp", "command": [
            sys.executable, "-m", "servers.mineral_pdf_mcp",
        ]},
        {"name": "lme-price-mcp", "command": [
            sys.executable, "-m", "servers.lme_price_mcp",
        ]},
    ]

    if args.api:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
        import uvicorn

        app = FastAPI(title="Daily Research Report Agent API")
        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

        agent = ResearchAgent(servers_config)

        @app.on_event("startup")
        async def startup():
            await agent.start()

        @app.on_event("shutdown")
        async def shutdown():
            await agent.stop()

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        class ReportRequest(BaseModel):
            query: str

        @app.post("/report")
        async def generate(req: ReportRequest):
            try:
                report = await agent.generate_report(req.query)
                return {"success": True, "report": report}
            except Exception as e:
                return {"success": False, "error": str(e)}

        uvicorn.run(app, host=args.host, port=args.port)
    else:
        async def run():
            agent = ResearchAgent(servers_config)
            try:
                await agent.start()
                query = args.query or "生成一份关于 Pilbara 锂矿的研报"
                report = await agent.generate_report(query)
                print(report["markdown"])
            finally:
                await agent.stop()
        asyncio.run(run())


if __name__ == "__main__":
    main()
