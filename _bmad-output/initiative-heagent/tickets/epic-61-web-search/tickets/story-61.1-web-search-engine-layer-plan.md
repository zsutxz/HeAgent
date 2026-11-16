---
title: "Story 61.1 web_search 引擎抽象层"
type: feature
ticket: 1
created: "2026-11-16"
status: built
baseline_revision: "792b5d3"
risk: low
context:
  - "_bmad-output/epics/epic-61-Web检索周期/SPEC.md"
  - "_bmad-output/initiative-heagent/tickets/epic-61-web-search/epic-61-web-search.md"
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 内建工具网络类仅 web_fetch（拉已知 URL），无法按主题发现新 URL。

**Approach:** 引擎抽象层先行（工具面在 61.2）：`tools/builtins/web_search_engine.py` 交付 SearchEngine 协议 + Tavily 引擎（默认，stdlib 语义 httpx 直调、Bearer header、trust_env=False）+ 名称→工厂 registry（换引擎只改 `web_search_engine` 配置声明，src 零 diff）；未配密钥构造成功、调用显性报错（工具常在契约的引擎侧）；错误分类复用 providers/retry 的 classify_error（包 ProviderError 走标准入口），引擎不自动重试。

**Decision (2026-11-16 用户裁定):** 默认引擎 Tavily；无密钥工具常在+显性报错；子代理与 web_fetch 同面开放（61.2 落地）；正式 story 流。

</frozen-after-approval>

## Code Map

- `src/heagent/tools/builtins/web_search_engine.py` — 新引擎模块：SearchResult（Pydantic）/ SearchEngineError（ToolError 子类，携 status_code+category）/ SearchEngine 协议 / TavilyEngine（POST JSON + Bearer、trust_env=False、无密钥调用显性报错、查询 ≤400 字符 fail-fast）/ `register_engine`+`create_engine`（未知名 fail-loud）
- `src/heagent/config/__init__.py` — 新字段：`web_search_engine`（default "tavily"）/ `web_search_api_key`（default ""）
- `src/heagent/config/catalog/groups.py` — `WEB_SEARCH_ENGINE` 入 outbound 显式键组（出站与端点）；`WEB_SEARCH_API_KEY` 经 `*_API_KEY` 凭证排除规则（不可写、永不回传）
- `.env.example` — 新增 Web 检索文档段（两键）
- `tests/test_web_search_engine.py` — 15 用例：请求形态/解析/无密钥零 HTTP/空查询/超长查询/max_results 钳位/4 状态码分类/超时 TRANSIENT/非 JSON/registry 可插拔（CAP-2）/未知名 fail-loud
- `tests/contract_baselines/exception_types.json` — SearchEngineError 登记（--write 再生）
- `tests/test_config_catalog.py` — TestSecrets 钉集补 WEB_SEARCH_API_KEY

## Tasks & Acceptance

- [x] 引擎协议 + TavilyEngine + registry（create_engine 未知名 fail-loud）
- [x] config 字段 `web_search_engine`/`web_search_api_key` + .env.example 文档 + catalog outbound 组 + TestSecrets 钉集 + 契约基线再生
- [x] 15 引擎测试全绿（请求形态/解析/无密钥/空查询/钳位/四类分类/registry 可插拔）
- [x] 门禁：全量 pytest（5 环境红已定性 environmental）+ ruff + format + mypy 全绿

## Review

待独立 review 代理结论。
