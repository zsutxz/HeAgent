---
ticket: 3
ref: 78.3
code: E78-S03
epic: epic-78-open-items-followthrough
risk: low
hitl: false
covers: ["R3"]
status: built
---

# E78-S03 · 三条活动项的操作卡：命令原文 + 期望输出 + 回填位置

## Intent

<frozen-after-approval>

A55 / A67 / A76 三条都停「等外部触发」，但闭合动作散在长句里：谁在哪台机器上跑什么、看到什么算过、
结果回填到哪里。本 entry 把这三件写进台账正文各自条目（**单源**，不另建操作文档）。

</frozen-after-approval>

## Boundaries & Constraints

**Always**

- 只改 `_bmad-output/open-items.md` 三条的正文；活动条数仍 4、ID 集合仍 `A55 A65 A67 A76`。
- A65 不动（`frozen`，用户裁定暂停）。
- 每条给：命令原文（可复制）、期望输出（判据形态）、回填位置（哪个文件哪一节）。

**Never**

- 不新建 `open-items-ops.md` 之类的第二份真相。
- 不改速读节 ID 集合、不改 `epic-overview.md` 的活动计数。

## Code Map

- `_bmad-output/open-items.md`：A55 / A67 / A76 三行正文追加操作卡。

## Tasks & Acceptance

- [x] A55：脚本用法 + 通过判据（四段全 OK / exit 0）+ key 禁令。
- [x] A67：`time devcontainer up` 计时口径 + 回填位置（README 该行）+ 偏差 >2 倍改文案。
- [x] A76：宿主 `netstat -ano | findstr :9201` + 期望输出 + 客户端三处对账清单。

## Verification

| 命令 | 期望 |
|---|---|
| `pytest tests/test_deferred_id_registry.py -q` | 全绿（计数 4 与速读节集合不变） |
| `pytest tests/test_docs_links.py -q` | 全绿 |
