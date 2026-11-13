---
id: SPEC-epic-61-web-search
companions:
  - ../../../docs/frame.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Epic 61 · Web 检索工具周期（web_search 内建工具）

## Why

pain 与 opportunity 交织：内建工具 26 个中网络类仅 `web_fetch`（拉取**已知** URL），模型与用户都无法按主题发现新 URL，Web 任务只能靠人工喂链接；检索是通用 agent 的标配能力，对标缺口在 2026-11-13 功能复盘中确认，用户裁定立项。受影响方：交互会话用户、子代理（task_delegate）、cron/goal 长任务。

## Capabilities

- **CAP-1 检索执行**
  - **intent:** 用户或模型可发起 Web 检索并获得结构化结果列表（标题/URL/摘要）。
  - **success:** 引擎与密钥齐备时，给定查询返回非空结果且每条含标题+URL；空/超长查询显性报错。
- **CAP-2 引擎可插拔**
  - **intent:** 更换检索引擎只需改配置声明，无需改代码。
  - **success:** 配置切到第二引擎后检索正常工作且 src 零 diff（以测试替身引擎验证）。
- **CAP-3 安全面对齐**
  - **intent:** 检索链路与 `web_fetch` 同级安全纪律（SafetyGuard/审批/容器沙箱覆盖）。
  - **success:** `web_fetch` 现有 guard/审批/沙箱测试形态在 `web_search` 上同构覆盖。
- **CAP-4 显性失败**
  - **intent:** 缺密钥/引擎不可达/限流时显性报错，不静默返回空结果。
  - **success:** 无密钥调用返回显性错误而非空列表；错误分类复用 `pub/exceptions` 的 TRANSIENT/NON_TRANSIENT 容错面。

## Constraints

- 沿用 `web_fetch` 的实现位与 SSRF 纪律，不新开网络层模块。
- 凭据只经 env/config 声明注入，不入库不入日志。
- 检索结果注入上下文前确定性截断（条数/字节预算，零概率模型参与）。

## Non-goals

- 不做浏览器渲染/JS 执行型检索，不做自建索引/爬虫（延续 `web_fetch` 无头 HTTP 立场）。
- 不做结果缓存/排序优化（期二再议）。
- web/控制台入口不做检索 UI。

## Success signal

无头 CI 以替身引擎全链测试通过；配真实密钥的引擎冒烟一次通过（参照 57-4 先例：临时 workspace，不触碰仓库记忆）。

## Assumptions

- 期一零第三方依赖：stdlib HTTPS+JSON 直调引擎 API，不用 SDK。

## Open Questions

- 默认引擎选型（候选：Brave / Tavily / Serper / DuckDuckGo 免 key 档）——需用户裁定。
- 无密钥时注册形态（倾向：工具常在 + 调用显性报错）；检索结果是否对子代理开放（task_delegate 工具面）。
