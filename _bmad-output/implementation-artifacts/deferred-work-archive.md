# Deferred Work Archive

> 跨周期 deferred 的唯一总账；当前活动项为 9 条（A34 / A35 / A36 / A40–A44 / A49）。
> **四态语义（2026-10-26 S-6 起）**：`active`（有触发条件、未排期）／`scheduled`（已挂到 story 或 sprint）／
> `frozen`（挂起待裁定，**必须带裁定指针**）／`retired`（显式退役，5 字段齐备）。
> 条目正文只在本文件；`deferred-work.md` 只保留入口与索引（同一 ID 不得同时出现在两个文件）。

## 活动（未闭合）条目

| ID | 主题 | 状态 | 说明 |
| --- | --- | --- | --- |
| A34 | 会话文件并发写残余：不可安全判定形态回退时丢对方一侧 | `frozen` | 主害已闭合（Z-D21，commit `9860a17`）。残余形态：共享前缀被改写 / 磁盘比基线短 / 基线对不上 / 文件不可解析 ⇒ 回退时丢对方一侧（WARNING 点名原因，不静默）。候选加固 = 把不可判形态的对方侧隔离进 sidecar 而非丢弃。**裁定指针：OQ-5 未裁定（「隔离 vs 丢弃」语义）**，故本轮只补确定性并发写回归测试（S-8），不改语义。触发条件 = 出现真实触发案例或用户裁定升级 |
| A35 | HTTP 入口会话/事件持久化（在途 run 与 SSE 缓冲重启即丢） | `active` | 会话历史已落盘（SessionStore，CLI 与网页共用），重启只丢在途 run 与 SSE 事件缓冲（重连有 `resync_required`→快照兜底）。最小收敛路径 = 复用既有钩子 `EVENTS_ROLLOUT_ENABLED`（per-run `rollout.jsonl`，默认关）做重连回放，不新做投影持久化架构。触发条件 = 重启丢在途 run 实际困扰 ≥2 次，或长 run（>10min）常态化 |
| A36 | 全局级 MCP 注入签名配置入口 | `active` | 项目级 `.heagent/injection_signatures.json` 已接入并进程内缓存；2026-10-20 查证项目级与全局级文件均不存在（零使用）⇒ 现在加全局入口属 YAGNI。触发条件 = 实际开始写自定义签名且需跨项目共享。注意：签名围栏非真正安全边界，加码不改变「须 OS 沙箱兜底」立场 |
| A40 | 审计基线已脏文件检测盲区（`cli/goal.py:434`） | `frozen` | 宿主 Git 审计以「会话前后路径差集」为增量语义：before 集已脏的集外 tracked 文件被本 Story 再改时检测不到。AD-18 定义即路径级增量。**裁定指针：根治在 AD-20 worktree 物理隔离层，OQ-4 未裁（本轮继续挂账）**。触发条件：并行批启动时工作区已有未提交集外改动 |
| A41 | 兄弟 Story 越集写互相误归因（`cli/goal.py:440-444`） | `frozen` | 共享工作区审计无法按写者归属，兄弟 Story 越集写会落入本 Story 的 Δ 判负（连带置闩）。**裁定指针：AD-20（OQ-4 未裁）**；短期靠围栏预防层降低概率 |
| A42 | 违规写无补救语义（`workflow_runner.py:633`） | `frozen` | 判负只置 FAILED + 闩，越集文件留工作区；闩后串行重跑新基线已含旧违规，审计对其失明。需人工清理指引或回滚工具；与基线盲区同族（**裁定指针：AD-20 族，OQ-4 未裁**） |
| A43 | `_host_artifact_relpath` 参照系（`cli/goal.py:454-457`） | `active` | `resolve` + `relative_to` 大小写敏感（Windows 大小写漂移 → 静默 `""`），`workspace≠repo root` 时跨参照系比较。当前部署两者相等；失败方向是误判非漏判。触发条件：workspace 与 repo root 分离部署 |
| A44 | 交互 REPL 不挂事件 rollout sink | `active` | 2026-10-26 Epic 57-4 冒烟附带发现：`JsonlSink` 唯一 subscribe 在单次模式路径（`interactive.py:182`），交互 REPL 从不订阅 ⇒ `EVENTS_ROLLOUT_ENABLED` 在交互模式不生效（audit 只剩 checkpoint/快照/租约）。触发条件：需要交互会话事件回放或审计留档；根治指向 REPL 启动路径按 settings 挂 sink（rollout 含工具原始输出，默认关闭是有意设计） |
| A49 | `EmbeddedHttpService.failure` 传播路径缺直接测试 | `active` | 来源 Epic 56-1 triage#3（low）：双 serve 循环之一意外死亡时 `failure` 属性的传播缺直接测试。现有覆盖 = fake 单循环死亡的 lifecycle 测试（打桩层）+ 真实双 server 干净启停；真实双 listener 故障注入未落地。触发条件：下一次改 HTTP/WS 双 server 装配时一并补测 |

## 已按 Epic 归档

| ID | 主题 | 状态 | 正文 |
| --- | --- | --- | --- |
| Z-D10 / Z-D11 / Z-D18 / Z-D20 | Epic 48 TCP 入口与日志审查 | 已闭合 / OBSOLETE | [`epic-48.../deferred-work.md`](../archive/epics/epic-48-TCP网络接口周期/deferred-work.md) |
| Z-D13 / Z-D14 / Z-D15 / Z-D19 / Z-D21 / Z-D22 / Z-D23 / A8 / A9 / A10 / A12 / A15 / A16 / A17 / A18 / A19 / A23 | Epic 50 网页控制台审查 | 已闭合或裁定维持现状 | [`epic-50.../deferred-work.md`](../epics/epic-50-网页控制台周期/deferred-work.md) |
| Z-D24 / A2 | Epic S1-S4 沙箱裁定 | 已闭合（裁定不实施） | [`epic-S1-S4.../deferred-work.md`](../archive/epics/epic-S1-S4-沙箱硬化周期/deferred-work.md) |
| A25 / A26 / A27 / A28 / A33 / A37 / A38 / A39 | Epic 51 Goal/workflow 收口优化 | 已闭合 | [`epic-51.../deferred-work.md`](../epics/epic-51-goal-workflow优化周期/deferred-work.md) |

## 本轮闭合（2026-10-26，S-6 归一；证据齐备，**不是**退役）

> 这些条目原先散在 `deferred-work.md` 的「仍需维护的观察」与 Epic 52 review 段里。S-6 归一时逐条核对代码，
> 确认已被既有实现或本轮 E1 闭合。与「退役」的区别：这里有可复跑的判据，不是「不做」。

| ID | 主题 | 闭合证据 |
| --- | --- | --- |
| A45 | `KeyboardInterrupt` / `SystemExit` 与 `CancelledError` 的中断语义不完全一致 | 语义已于 2026-10-23 裁定（A39）；本轮 S-3 把「三分支 → `cancelled`、其余 → `executor_failed`」固化成 `docs/frame.md` 的矩阵表，由 `tests/test_workflow_transition_reason.py::test_interrupt_matrix_matches_absorb_semantics` 与 `::test_interrupt_matrix_covers_vocabulary` 双向钉住 |
| A46 | 异常处理中的 `transition()` 理论上可能覆盖原始异常 | `src/heagent/engine/workflow_transition.py:41` 的 `raise … from exc` 保留 cause 链；`tests/test_workflow_transition_reason.py::test_transition_failure_preserves_cause_chain` 断言 `__cause__` 为 `KeyError`；`scripts/mutation/mutate_state_invariants.py` 的 M5（去掉 `from exc`）会把它打红 |
| A47 | `reason: str(exc)` 可无上限写入 `next_action` / `blocked_reason` | `src/heagent/engine/workflow_runner.py:41` `_MAX_REASON_CHARS = 2000` + `:53-57` `_bounded_reason`（A37 已落）；`tests/test_workflow_transition_reason.py::test_bounded_reason_caps_without_raising` 与 `::test_oversized_reason_is_truncated_on_write` 钉住 |
| A48 | `workflow_step_failed` 未记录驱动转换的事件类型；checkpoint 缺 `last_event` / `transition_reason` | `last_event` 已由 A38 落地（`workflow_runner.py:149`、`checkpoint.py`）；`transition_reason` 由本轮 S-1 补齐（字段 + 唯一写点 + 双向往返）；`workflow_step_failed` 的 `transition_event` 在 `:408` / `:700` 两处发射 |

- **52-3 AC1（端到端围栏贯通冒烟）**：已闭合（2026-10-26，Epic 57-3）——真实注册表 `file_write` handler 经
  `policy.evaluate_tool_call → executor.execute` 全链贯通：集内写真实落盘、越集写围栏 BLOCKED 且 handler 零触达。
  贯通首跑暴露一处真实缝隙：真实 handler 从运行时绑定（`bind_workspace_root`）解析根而非 RunContext，测试已按主链路
  `_runtime_scope` 同形态绑定。证据 `tests/test_write_allowlist.py::test_e2e_chain_*`（2 例）。
  **附带发现（不另行立项）**：围栏（policy 用 RunContext 根）与工具（handler 用运行时绑定根）在二者不一致时可出现
  「围栏判 A 根、工具写 B 根」的错位窗口——当前主链路两者恒同源（loop 每 run 绑定 `run_context.workspace_root`），
  错位不可达；登记供未来改 run 上下文装配时复核。

## 显式退役（`retired`）

> 语义：**已裁定不再修**（区别于「已修复归档」）。混进归档段会让后人二次调查同一问题。
> 每条必须齐备 5 字段：`retired_reason`（退役理由）／`replaced_by`（替代守卫，`file:line` 或 story id）／
> `decision_ref`（裁定出处：日期 + 记录位置）／`retired_on`（退役日期，须实测系统日期）／
> `recheck_condition`（复活条件）。

| ID | retired_reason | replaced_by | decision_ref | retired_on | recheck_condition |
| --- | --- | --- | --- | --- | --- |
| （当前 0 条） | — | — | — | — | — |

**为什么本轮 0 条**：退役需要「已裁定不修」的前提，而本轮已批决策只覆盖「继续挂起 / 继续挂账」（OQ-3 / OQ-4 / OQ-5），
没有任何一条被裁定为「永不修」。缺裁定指针却填满 5 字段等于伪造决策，故留空表 + 结构就位。

## 跨周期勘察与裁定索引

以下条目没有唯一 Epic 归属，保留在总账中作为历史索引；详细当前边界以 `docs/frame.md`、`docs/goal-workflow.md` 和源码为准。

| ID | 主题 | 结论 |
| --- | --- | --- |
| Z-D1 / Z-D2 / Z-D4 / Z-D5 / Z-D6 / Z-D7 / Z-D8 / Z-D9 / Z-D12 / Z-D16 / Z-D17 | 架构、解析、日志、沙箱和会话存储勘察 | 已闭合或裁定维持现状 |
| Z-D3 | provider 回退骨架是否统一 | 评估结论为不收敛：chain、key_rotation、switchable、router 的回退条件、粘性和索引语义有意不同；补充互指注释，行为不变 | `providers/{chain,key_rotation,switchable,router,retry}.py`；`tests/test_retry.py::TestPoolFallbackPolicy`；提交 `beea1a2` |
| A3 / A4 / A5 / A11 / A24 | 入口、GUI、观测与运行姿态 | 已闭合，正文留在相关周期记录或提交证据中 |
| A1 / A6 | 技能资源与路径级审批前置裁定 | 裁定维持现状或维持条件性；边界见 `docs/frame.md` 五 |
| A29 / A30 / A31 / A32 | 2026-10-07 架构简化与层次收敛 | 已闭合；证据见提交记录、源码和测试 |
| 技能资源 TOCTOU 残余竞态专项评估 | 已评估（2026-10-20）。事实：单一安全内核 `path_safety.read_bytes_under_root`（围栏 resolve → 加固 open → fstat 普通文件校验 → 持 fd 读满）双通道——POSIX 逐组件 openat（2026-09-27 硬化）收窄至组件级竞态，Windows 无 dir_fd 走整路径回退（窗口与硬化前同宽，本机实际通道）；importer 落地为 verify-before-land（temp 复制后复核逐文件摘要，通过才 `os.replace`，检查期哈希→落地拷贝的窗口已闭合）；包读侧另有钉定摘要校验。裁决：check 与 use 同进程同权限，TOCTOU 不跨越信任域——能赢下任一窗口的攻击者无需竞态即可直写技能根或经 shell 直读凭证（frame.md 既有登记面），无新增可提升暴露面 ⇒ **不另立收窄周期**，维持 OS 沙箱兜底立场。附带确证：manifest.csv / `_hash` 直读为 load-bearing 例外（csv raw newline 语义 / 任意位置临时树哈希，围栏不适用）；`skill_meta.load_meta` 在 src 内零调用方（死代码路径，非活窗口）；`SkillStore._read_text` 实例锁已覆盖 Windows 读写互斥。边界：`tools/path_safety.py`、`skills/{skill_store,skill_packages,skill_importer}.py` |

## 维护规则

- 新增未闭合项先登记 ID、**状态（active / scheduled / frozen / retired）**、触发条件、裁定与验收证据，再开始实施。
- `frozen` 必须带**裁定指针**（哪个 OQ / 哪份记录）；没有指针的「挂起」不是状态，是遗忘。
- 显式退役必须齐备 5 字段，缺一项即无效；退役 ≠ 删除，正文一律保留。
- 已闭合项按 Epic 归档正文；不要在本文件复制完整 review 报告。
- `blocked` 需要产品或架构裁定，不能由实现者静默关闭。
- **单向收敛**：条目正文只在本文件；`deferred-work.md` 只保留入口与索引（同一 ID 不得同时出现在两个文件）。
