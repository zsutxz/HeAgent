---
id: 52-1
title: 写集围栏原语——policy 层 per-run write allowlist
status: done
parent_epic: E52
priority: P1
depends_on: []
blocks: [52-2, 52-3]
created: '2026-10-09'
---

# Story 52-1：写集围栏原语——policy 层 per-run write allowlist

## 用户故事

作为库用户，我希望单次 run 能声明一个写路径白名单，`file_write` / `file_edit` 越集写入在治理链内被
结构化 BLOCKED；不声明则行为与现状逐字节一致。

## 引擎面（主要交付物；声明层表达不了的证明）

write allowlist 是**运行态授权**（随每次 run 注入、由宿主从 story 声明派生），不是声明词汇本身——
story 文档的 `write_set` 在 51-8 已存在；把它变成"工具执行期的路径裁决"必须进 PolicyEngine
（与 `approved_tools` / `sandboxed_tools` 同族的运行时词汇）。声明层表达不了工具调用瞬间的路径裁决。

- `src/heagent/engine/policy.py`：
  - 新增 `_WRITE_ALLOW_TOOLS = frozenset({"file_write", "file_edit"})`；
  - `_validate_paths` 增写集检查：`context.metadata["write_allowlist"]` 为非空列表时，
    写路径经 `resolve_under_root` 后必须 ∈ allowlist（条目同样 resolve；目录条目放行子树
    `is_relative_to`）；越界 → `BLOCKED`，reason 形如
    `write outside the declared write set: <path>`，来源标记 `source="write_allowlist"`；
  - allowlist 缺失 / 空列表 / 其他工具 → 现状放行（零回归面）。
- `src/heagent/agent/sub.py`：`SubAgent.__init__` 增 `write_allowlist: Sequence[str] | None = None`；
  `run()` 在过滤后的 metadata 上注入 `metadata["write_allowlist"]`，并把该键加入 reserved 集
  （防用户 metadata 伪造授权）。

## 验收标准

1. `file_write` / `file_edit` 目标 ∉ allowlist → `BLOCKED`，reason 点名路径与写集，
   断言走 `PolicyEngine.evaluate` 链（verdict.source）——零旁路。
2. 目录条目放行子树；相对/绝对路径按 `resolve_under_root` 语义裁决；符号链接逃逸按既有围栏语义。
3. 无 allowlist（None / 空）时既有 policy 测试全绿（零回归）。
4. SubAgent 传参后 RunContext.metadata 可见；用户 metadata 同名键被 reserved 过滤。
5. 老包 / 老回调零改动；`tests/test_architecture_contracts.py` 同步后全绿。

## 任务

- [x] TDD：先写 `tests/test_write_allowlist.py`（RED：6 failed / 9 passed——9 个放行锚点
      在实现前即绿，锁定零回归基线）。
- [x] 实现 policy 层检查 + SubAgent 参数（GREEN：15/15）。
- [x] 架构契约同步检查（无新增跨模块依赖，30/30 全绿，`FORBIDDEN_RUNTIME_IMPORTS` 无需改动）。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_write_allowlist.py tests/test_policy_engine.py -q   # 后者不存在：policy 既有覆盖在
                                                                      # test_engine_p0 / test_credential_guard /
                                                                      # test_sandbox / test_runtime_config /
                                                                      # test_workspace_paths，全量跑内均通过
pytest tests/test_architecture_contracts.py -q
pytest
ruff check src tests
mypy src
```

## 实测证据（2026-10-09，本机亲跑）

```text
pytest tests/test_write_allowlist.py -q → 15 passed（TDD RED 6 failed → GREEN 15 passed）
pytest tests/test_architecture_contracts.py -q → 30 passed
ruff check src tests → All checks passed!
ruff format --check src tests → 314 files already formatted
mypy src → Success: no issues found in 164 source files
pytest -q（全量）→ 3618 passed, 22 failed, 14 skipped, 18 deselected
```

**全量 22 failed 的归因（如实记录）**：环境性失败，与本 story 改动无关——

- 失败全部集中在 goal 域（test_goal_decisions / test_goal_declarative_workflow /
  test_goal_status_view），错误为 `goal.lock` 文件锁获取超时或锁文件 `PermissionError`；
- 根因：测试期间本机有 `heagent.exe`（PID 33324）与 `codex.exe` 进程并发持锁；
- **stash 基线验证**：撤掉本 story 的 src 改动后同一用例仍失败（`1 failed in 6.60s`），
  证明失败先于改动存在；
- 数字对账：3618 passed = 51-8 收口基线 3603 + 本 story 新增 15 测试，分毫不差；
- 处置（用户拍板 2026-10-09）：本 story 以域内验证为准，进程空闲后可随时补全量干净基线。
