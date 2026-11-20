---
title: "Story 61.3 web_search 配置面与文档收口"
type: feature
ticket: 3
created: "2026-11-16"
status: done
baseline_revision: "1877250"
risk: low
context:
  - "_bmad-output/epics/epic-61-Web检索周期/SPEC.md"
  - "docs/frame.md"
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 引擎/工具/安全面（61.1/61.2）已交付，缺文档收口与真实引擎链路冒烟。

**Approach:** `docs/frame.md` 四处对齐（Web 工具表补 web_search 行、目录树补 web_search_engine.py、dreaming 安全立场与联网注入围栏两行扩 web_fetch/web_search 并列）；`mkdocs build --strict` 过文档门；真实密钥冒烟一次（用户向 .env 提供 WEB_SEARCH_API_KEY，临时 workspace，不触碰仓库记忆，参照 57-4 先例）。配置面本身已在 61.1 交付（字段/.env.example/catalog），本 story 只做核对不重做。

**Never:** 冒烟不改产品代码；key 不入 transcript、不入库、不入日志。

</frozen-after-approval>

## Tasks & Acceptance

- [x] docs/frame.md 四处收口
- [x] mkdocs strict 构建通过（2026-11-16 本地 strict 构建零 WARNING）
- [ ] 真实 Tavily 冒烟一次通过（web_search 工具链全链：config 解析→引擎调用→截断→围栏）——2026-11-16 用户裁定跳过，挂账 open-items A55
- [x] 门禁复绿 + epic 收尾（61.1/61.2/61.3 mark done；冒烟除外全验收）
