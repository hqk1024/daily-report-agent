# Daily Research Report Agent - 启动指南

基于 MCP 协议的智能研报生成系统。3 个 MCP Server + 1 个 ReAct Agent + 1 个 React 前端。

---

## 5 步启动

### 前置条件

- Python 3.12+
- Node.js 20+
- Docker (可选, 用于容器化运行)

### 步骤 1: 安装 Python 依赖

```bash
# 根目录
pip install -r requirements.txt

# Agent 额外依赖
pip install -r agent/requirements.txt
```

### 步骤 2: 启动 Agent API 服务

```bash
# 启动 HTTP API (端口 8000)
python agent/agent.py --api --host 0.0.0.0 --port 8000
```

验证: `curl http://localhost:8000/health`
预期: `{"status": "ok"}`

### 步骤 3: 安装前端依赖并启动

```bash
cd frontend
npm install
npm run dev
```

访问: `http://localhost:5173`

### 步骤 4: 生成报告

在浏览器中输入查询或通过 CLI:

```bash
# 直接生成 CLI 报告
python agent/agent.py "生成一份关于 Pilbara 锂矿的研报"
```

### 步骤 5 (可选): Docker 方式运行

```bash
# 构建并启动所有服务
docker-compose up --build
```

---

## Claude Desktop / Cursor 集成

将 MCP server 添加到 Claude Desktop 或 Cursor 的 MCP 配置中:

1. 打开 Claude Desktop → Settings → Developer → MCP Servers → Edit Config
2. 添加 （请将 `C:/path/to/daily-report-agent` 替换为实际的项目路径）:

```json
{
  "mcpServers": {
    "mining-news-mcp": {
      "command": "python",
      "args": ["servers/mining-news-mcp/server.py"],
      "cwd": "C:/path/to/daily-report-agent"
    },
    "mineral-pdf-mcp": {
      "command": "python",
      "args": ["servers/mineral-pdf-mcp/server.py"],
      "cwd": "C:/path/to/daily-report-agent"
    },
    "lme-price-mcp": {
      "command": "python",
      "args": ["servers/lme-price-mcp/server.py"],
      "cwd": "C:/path/to/daily-report-agent"
    }
  }
}
```

> `cwd` 字段告诉 Claude Desktop 在哪个目录运行命令,让 Python 能正确找到 `mcp_base.py`。务必替换为实际路径。

---

## 项目结构

```
daily-report-agent/
├── servers/
│   ├── mining-news-mcp/server.py   # 新闻搜索 + 文章抓取
│   ├── mineral-pdf-mcp/server.py   # PDF 资源提取 (NI 43-101)
│   └── lme-price-mcp/server.py     # 商品价格查询
├── agent/
│   └── agent.py                     # ReAct Agent (CLI + HTTP API)
├── frontend/
│   ├── src/
│   │   ├── App.jsx                  # React 前端
│   │   └── App.css
│   └── package.json
├── docker-compose.yml               # Docker 编排
├── Dockerfile                        # Agent Docker 镜像
├── mcp-config.json                   # MCP 配置 (Claude Desktop)
├── RUN.md                            # 本文件
└── requirements.txt                  # Python 依赖
```

## MCP Servers 接口说明

| Server | Tool | 说明 |
|--------|------|------|
| mining-news-mcp | `search_news(query, days)` | 搜索矿业新闻 |
| mining-news-mcp | `fetch_article(url)` | 抓取文章全文 |
| mineral-pdf-mcp | `extract_resources(pdf_url)` | 解析 NI 43-101 PDF 资源报告 |
| lme-price-mcp | `get_price(commodity, date)` | 查询商品当前价格 |
| lme-price-mcp | `get_trend(commodity, days)` | 查询价格趋势 |
