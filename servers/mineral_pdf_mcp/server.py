"""MCP server for mineral resource PDF extraction (NI 43-101 compliant)."""

import asyncio
import json
from datetime import datetime
from io import BytesIO

import httpx
from servers.mcp_base import Server


async def extract_resources(pdf_url: str) -> str:
    """Download a PDF from URL and extract mineral resource tables/data."""
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()

        import fitz

        doc = fitz.open(stream=BytesIO(resp.content), filetype="pdf")

        extracted = {
            "source_url": pdf_url,
            "pages": len(doc),
            "resource_estimates": [],
        }

        full_text = ""
        for page_num, page in enumerate(doc):
            text = page.get_text()
            full_text += text + "\n"

            lines = text.split("\n")
            for i, line in enumerate(lines):
                if any(kw in line.lower() for kw in [
                    "indicated", "inferred", "measured", "resource",
                    "reserve", "grade", "tonnage", "ni 43-101", "mineral resource",
                ]):
                    context = lines[max(0, i - 2):i + 5]
                    extracted["resource_estimates"].append({
                        "page": page_num + 1,
                        "context": " | ".join(c.strip() for c in context if c.strip()),
                    })

        seen = set()
        unique_estimates = []
        for est in extracted["resource_estimates"]:
            key = est["context"]
            if key not in seen:
                seen.add(key)
                unique_estimates.append(est)
        extracted["resource_estimates"] = unique_estimates[:50]

        extracted["text_content"] = full_text[:2000]
        extracted["tables_found"] = len(extracted["resource_estimates"]) > 0
        doc.close()
        return json.dumps(extracted, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "source_url": pdf_url})


server = Server("mineral-pdf-mcp")


@server.tool(
    name="extract_resources",
    description="Download and extract mineral resource data (NI 43-101) from a PDF report URL",
    inputSchema={
        "type": "object",
        "properties": {
            "pdf_url": {"type": "string", "description": "URL of the PDF mineral report to analyze"},
        },
        "required": ["pdf_url"],
    },
)
async def handler_extract(pdf_url: str) -> str:
    return await extract_resources(pdf_url)


if __name__ == "__main__":
    asyncio.run(server.run())
