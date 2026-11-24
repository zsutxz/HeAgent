---
ticket: 3
ref: 77.3
code: E77-S03
epic: epic-77-remote-contract-hardening
risk: low
hitl: false
covers: ["R3"]
status: done
---

# E77-S03 · 只读能力面与延期项收口：AD-8 措辞对齐代码、三条裁决回写需求真源

## Intent

<frozen-after-approval>

H-2 裁决 = 维持零能力面（只读 listener 无入口层配置键、生产不存在该档位，不加端点）。要做的只是
把「文档说允许、代码不可达」这条矛盾消掉，并把三条裁决回写需求真源，让下一轮读 `brief.md` 的人
不再看到「待裁决」。

</frozen-after-approval>

## Boundaries & Constraints

**Always**

- AD-8 的 `Binds`/`Rule` 措辞改成与实现一致：只读 listener **不注册**集合级端点 ⇒ `projects` 不可达；
  并把原「被拒替代 (a)」标注为「即采用」。
- `brief.md` 延期项三条改写成「裁决日期 + 结论 + 落点」，保留原来源信息。
- `progress.md` 决策日志追加（追加式，不改历史条目）；E77 行与 status / 交接块同步。
- 契约快照重生成应零漂移（本轮不改协议面结构，只改错误码 —— 那是 S02 的 diff）。

**Never**

- 不在 `docs/framework.md` 改 WS 帧面语义（本轮无帧面变更，除 S01 的 `request_id` 由 S03 只补一行说明）。
- 不改冻结段（`brief.md` 的「原始需求」、E74/E75/E76 的 Requirements）。
- 不删除 `WsServerConfig.readonly` 字段（有既有只读用例依赖）。

## Code Map

- `docs/Goal-4/architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md:129`
  AD-8「只读 listener 上 `projects` 帧**允许**」→ 与实现一致的措辞 + 落点补 `ws_host.build_ws_app`。
- `docs/framework.md:1411` 只读旁观行：补「`projects` 同样不可达（集合级端点未注册）」。
- `docs/framework.md:1404` 提交 run 行：补 S01 的 `request_id` 一句。
- `docs/Goal-4/brief.md:93-94` 延期项三条。
- `docs/Goal-4/progress.md`：状态行、E77 行、决策日志、交接块。

## Tasks & Acceptance

- [x] AD-8 措辞对齐 + 被拒替代标注。
- [x] `docs/framework.md` 两行补充（只读旁观 / 提交 run 的 `request_id`）。
- [x] `brief.md` 三条延期项改写（含 M-4 的 60s 内存窗口与「失败不缓存」口径、M-7 的新码名、
      H-2 的零能力面结论）。
- [x] `progress.md`：`状态` 改 `in-progress（2026-11-24 重开：E77 三处延迟裁决）`、Epic 表加 E77、
      决策日志三条、交接块重写。
- [x] 五份快照 `--check` 全 `[OK]`，`mkdocs build --strict` 0 warning。

## Verification

| 命令 | 期望 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_docs_links.py tests/test_deferred_id_registry.py tests/test_deferred_ledger.py -q` | 全绿 |
| `.heagent/tmp/py311-venv-linux/bin/python -m mkdocs build --strict` | 退出 0、WARNING 计数 0 |
| `grep -c "待裁决" docs/Goal-4/brief.md` | 0 |
| `grep -n "只读 listener 上 \`projects\` 帧\*\*允许\*\*" docs/Goal-4/architecture-ws-remote-project-channel/*.md` | 零命中（E75 epic Notes 与 E77 票面里的同句引用是历史证据，不删） |
| `.heagent/tmp/py311-venv-linux/bin/python scripts/contract_snapshot.py --check` | 五份 `[OK]` |

## 实测结果（2026-11-24）

| 命令 | 结果 |
|---|---|
| `pytest tests/test_docs_links.py tests/test_deferred_id_registry.py tests/test_deferred_ledger.py -q` | **20 passed** |
| `mkdocs build --strict` | 退出 0、WARNING/ERROR 计数 **0** |
| `grep -c "待裁决" docs/Goal-4/brief.md` | **0**（历史句改成「当时只剩下面两条未裁决」） |
| `grep -n "只读 listener 上 \`projects\` 帧\*\*允许\*\*" docs/Goal-4/architecture-…/*.md` | 零命中 |
| `python scripts/contract_snapshot.py --check` | 五份全 `[OK]`（S03 自身零漂移） |
| `pytest`（全量，带 node） | **5893 passed / 17 skipped / 30 deselected / 1 xfailed / 0 failed**（318s） |
| `bandit -r src/ -ll` | `No issues identified`（4 处既有 nosec 噪声，与基线同谱） |

## Implementation Notes

- **判据口径修正（`bad_spec`）**：票面原写「`grep -rn "只读 listener 上 `projects` 帧" docs/` 零命中」——
  历史证据不会被清掉：E75 epic 的 Notes 与 E77 自己的票面/plan 都**引用**过那句话。判据改成只锚
  「架构 spine 里那句决策原文」，历史引用保留（它们正是「为什么会有这条矛盾」的溯源）。
- **顺手改对的落点名**：AD-8 的落点原写 `_warn_external_without_sandbox`，E76 落地时已按 external / lan
  两档拆成 `_warn_remote_without_sandbox`；本次一并更正，避免下一个人按旧名找函数。
- **`brief.md` 历史句**：2026-11-23 的「只剩下面两条待用户裁决」改成「当时只剩下面两条未裁决」，语义不变
  但不再制造「仍有待裁决」的 grep 假阳性。
