---
type: epic
parent: initiative-heagent
covers: []
sources: ["../../../epics/epic-61-Web检索周期/SPEC.md"]
companions: ["../../../docs/frame.md"]
after: []
risk: low
---

# Web 检索工具周期（web_search 内建工具）

> 本信封为 epic 61 的活面（状态唯一写目标见同目录 tickets/tickets.toml）；契约正本 = `sources` 指向的 SPEC（preservation-validated，保持不动）。

## Description

内建工具 26 个中网络类仅 `web_fetch`（拉取已知 URL），模型与用户都无法按主题发现新 URL。本周期交付 web_search 内建工具：Tavily 为默认检索引擎，引擎层可插拔（换引擎只改配置声明，src 零 diff），安全面与 `web_fetch` 同构对齐。

## 裁定记录（2026-11-16，用户裁定）

- **默认引擎 = Tavily**（api.tavily.com 非 Google/DDG 域，本机网络直连可达；POST+JSON 契合 stdlib 零依赖；免费档 1000 次/月）
- **无密钥注册形态 = 工具常在 + 调用显性报错**（复用 `pub/exceptions` 的 TRANSIENT/NON_TRANSIENT 容错面）
- **子代理开放 = 与 web_fetch 同面**（web_search 加入 `pub/roles.py` 中 web_fetch 所在角色的 allowed_tools，至少 dreamer）
- **实现流 = 正式 story 流（票树）**

## Outcome

引擎与密钥齐备时，检索返回非空结构化结果（标题/URL/摘要）且确定性截断（条数/字节预算，零概率模型参与）；缺密钥/引擎不可达/限流显性报错，不静默返回空结果。

## Requirements

- **CAP-1 检索执行**：给定查询返回非空结果且每条含标题+URL；空/超长查询显性报错。
- **CAP-2 引擎可插拔**：配置切到第二引擎后检索正常工作且 src 零 diff（测试替身引擎验证）。
- **CAP-3 安全面对齐**：`web_fetch` 现有 guard/审批/沙箱测试形态在 `web_search` 上同构覆盖。
- **CAP-4 显性失败**：无密钥调用返回显性错误而非空列表。

## Constraints

- 沿用 `web_fetch` 的实现位与 SSRF 纪律，不新开网络层模块。
- 凭据只经 env/config 声明注入，不入库不入日志。
- 期一零第三方依赖：stdlib HTTPS+JSON 直调引擎 API，不用 SDK。
- 跨模块数据用 Pydantic 模型（`pub/types.py`），provider/tool 禁止从 `agent/` 导入。
- 不做浏览器渲染/JS 执行型检索，不做自建索引/爬虫，不做结果缓存/排序优化（期二再议），web/控制台不做检索 UI。

## Done when

- 无头 CI 以替身引擎全链测试通过；配真实密钥的引擎冒烟一次通过（参照 57-4 先例：临时 workspace，不触碰仓库记忆）。
- 全量测试 + ruff + mypy 绿；docs strict 构建通过（若动 docs/）。
