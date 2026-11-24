---
ticket: 2
ref: 79.2
code: E79-S02
epic: epic-79-a76-attest-tool
risk: low
hitl: false
covers: ["R2"]
status: done
---

# E79-S02 · A76 操作卡收成一条命令 + 工具链指针

## Intent

<frozen-after-approval>

A76 的台账操作卡目前是三条手工命令（宿主 `netstat`、`heagent tls fingerprint --format pin` 人眼比对、
无 token 403 手测）。本 entry 把服务端侧那两条换成 E79-S01 的一条命令 + 期望输出，`netstat` 降为可选补证，
并让客户端交付只剩「拿到三格式 pin + 三处对账」两件。

同批修工具链指针：`AGENTS.md` 的 WS/TLS 工具链序列补 `ws_tls_attest.py`（排在 `heagent tls` 之后、
`ws_manual_probe.py` 之前——一个是签发入口，一个是机器判据，一个是手工交互）。

</frozen-after-approval>

## Boundaries & Constraints

**Always**

- 只改 `_bmad-output/open-items.md` 的 A76 正文与 `AGENTS.md` 工具链那一行；活动条数与 ID 集合不变
  （仍 4 条 / `A55 A65 A67 A76`），速读节集合不变，A65 仍 `frozen`。
- 台账单元格里的 `netstat -ano` 过滤写法必须避开竖线（表格会被 `|` 拆单元格）——写「再用 `findstr` 过滤」。
- `docs/tls-connect-guide.md` 被 `.gitignore` 排除（ADR-0004：客户端本地资料）⇒ 该页的漂移（引退役 A75、
  写「生产姿态未切换」）只做本地落改，**不入库**、不写进本 entry 的 write_set。

**Never**

- 不闭合 A76（客户端 pin 与设备三处对账在 `aihome-client` 仓）。
- 不新登 A 号、不改 `tests/test_deferred_id_registry.py` 里的任何断言。

## Plan

1. A76 操作卡改写：① 一条命令 + 三行关键期望输出 ② `netstat` 标可选补证并给出容器侧等价证据来源
   ③ 客户端三处对账原样保留（`X509TrustManager` pin / 不校主机名 / 三错误码）。
2. `AGENTS.md` 工具链补 `ws_tls_attest.py` 一句（四段承兑 + `--self-check` + A76 服务端侧闭合工具）。
3. 守卫复跑：`tests/test_deferred_id_registry.py`（计数逐处严格比对 + 速读节集合）、`tests/test_docs_links.py`。

## Verification

- `pytest tests/test_deferred_id_registry.py tests/test_docs_links.py -q` → 全绿。
- `grep -c 'ws_tls_attest.py' _bmad-output/open-items.md AGENTS.md` → 各 ≥ 1。
- `grep -c '操作卡' _bmad-output/open-items.md` → 3（A55 / A67 / A76 各一）。
- `mkdocs build --strict` → 0 warning（`docs/` 未新增页面，仅 `AGENTS.md` 一行改动）。
