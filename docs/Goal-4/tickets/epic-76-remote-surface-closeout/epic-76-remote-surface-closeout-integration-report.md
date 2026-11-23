---
type: integration-report
code: E76-INT
epic: epic-76-remote-surface-closeout
generated_at: 2026-11-23
step: step-08-system-integration-test
head: f42ab032
---

# E76 集成报告 · 并发隔离与远程面收口（Step 08）

## 集成场景（跨 story）

| # | 场景目标 | 验证的 Done when / 不变量 | 判据命令 | 观察结果 |
|---|---|---|---|---|
| 1 | 两项目并发不串味：`run_id` 交叉计数 0、ack 指向正确 run | R1 + Done when 2 | `pytest tests/network/test_ws_project_admission.py tests/network/test_ws_remote_flow.py -q` | passed |
| 2 | 名额双层且两码可分辨（项目内 vs 全局） | R2 + AD-6 | `pytest tests/network/test_ws_project_admission.py -q` | passed |
| 3 | 被拒提交不触达端口（不占名额） | §6.3 第 4 条 | 同上 | passed |
| 4 | 续流无空洞：首帧 ≤ last+1、其后连续到终态 | R3 + AD-5(b) | `pytest tests/network/test_ws_resume.py -q` | passed |
| 5 | 窗口不足必响：`resync_required` 先于任何 event | R4 + AD-5(c) | 同上 | passed |
| 6 | run 已被清理 ⇒ 具名错误帧、不回空流 | R4 + Q3 | 同上 | passed |
| 7 | 远程可见面不扩张：命令集 5 值封闭 + 词根守卫（含阳性控制与具名豁免出口） | R5 + AD-8 | `pytest tests/network/test_ws_protocol.py tests/test_architecture_contracts.py -q` | passed |
| 8 | 启动告警族：`external` / `lan` 各自恰 1 条、`docker` 档 0 条、不改启动成败 | R6 + D9 + Done when 4 | `pytest tests/test_cli_http_lifecycle.py -q` | passed |
| 9 | 契约快照与文档收口（五份基线零漂移 + 客户端对接口径） | R7 + Done when 5 | `python scripts/contract_snapshot.py --check` + `mkdocs build --strict` | 五份 `[OK]` / 0 warning |
| 10 | ADR-005 五步在**真 listener** 上串通 | Done when（收口补强） | `pytest tests/network/test_ws_remote_flow_live.py -q` | passed（4 例：五步真链路 / 真 AgentLoop 落会话 / 错误帧无路径 / 名额共享） |

- 合并命令：`pytest tests/network/test_ws_remote_flow_live.py tests/network/test_ws_remote_flow.py tests/network/test_ws_resume.py tests/test_cli_http_lifecycle.py -q` = **31 passed in 7.19s**。

## 质量门禁

- `python scripts/quality_gate.py`：**all gates passed**（contract snapshot / smoke / regression+coverage / ruff / format / mypy / bandit）。
- 覆盖率 93.50%（阈值 87%）；`mkdocs build --strict` 0 warning；`bandit -r src/ -ll` No issues。

## 系统集成结论

**通过**。E76 的六条 entry 把 ADR-005 验收基线落到可复跑判据上：并发隔离、cursor 续流、可见面封闭集、启动告警族、契约与文档收口；「两项目交叉计数」与「五步真链路」分属两条判据（替身 / 真 listener），两者都在本轮跑过，无未决 Critical。
