---
title: 'Story 67.3 实现敏感操作留痕'
type: feature
ticket: 3
created: '2026-11-18'
status: done
baseline_revision: '0b1b156'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/pub/audit.py'
  - 'src/heagent/context/session.py'
  - 'tests/test_sensitive_trace.py'
---

## Intent

敏感操作（会话删除、技能删除/归档、配置写入）目前只有配置写入有审计（`config/write.py` →
`console/audit.jsonl`，键名+哈希+长度），会话/技能删除无痕。

**Approach：** 复用 67.2 的审计写入原语，为敏感操作记 `operation` / `operator` / `target` /
`before` / `after`（敏感值为哈希或摘要），并用**前序行哈希链**（每行带 `prev` 摘要）使篡改可检出；
提供 `heagent audit verify` 校验链完整性。

## Verify

- 会话删除、技能删除、配置写入三类操作各落一条带 before/after 的记录；
- 篡改任一行后 `audit verify` 报出首个断链行号；
- 链校验与导出复用 67.2 的读取面，不另建第二套存储格式。

## Boundaries

- 哈希链是「篡改可检出」而非密码学不可篡改（不加外部密钥管理）。
- 不改 `config/write.py` 既有审计文件格式（保持向后兼容，新增统一审计文件）。

## Implementation（实测）

- 落点：`pub/audit.py` 的 `record_operation` + `prev`/`digest` 哈希链与 `verify_chain`；接入会话删除
  （`context/session.py`）、技能删除/归档（`skills/skill_store.py`）、配置写入（`cli/http_console.py` 写入通道返回处）。
- 敏感值只存 `fingerprint_file` / `fingerprint_dir` 摘要；`heagent audit verify` 报首个断链行（含行号与原因）。
- 实测：`pytest tests/test_sensitive_trace.py -q` → 9 例全绿（三类操作各一条记录、篡改后断链定位、导出格式）。
