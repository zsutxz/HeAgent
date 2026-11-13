# Deferred Work Archive

> 跨周期 deferred 的唯一总账；当前活动项为 6 条（A34 / A35 / A36 / A41 / A52 / A53）。
> **四态语义（2026-10-26 S-6 起）**：`active`（有触发条件、未排期）／`scheduled`（已挂到 story 或 sprint）／
> `frozen`（挂起待裁定，**必须带裁定指针**）／`retired`（显式退役，5 字段齐备）。
> 条目正文只在本文件；`deferred-work.md` 只保留入口与索引（同一 ID 不得同时出现在两个文件）。

## 活动（未闭合）条目

| ID | 主题 | 状态 | 说明 |
| --- | --- | --- | --- |
| A34 | 会话文件并发写残余：不可安全判定形态回退时丢对方一侧 | `frozen` | 主害已闭合（Z-D21，commit `9860a17`）。残余形态：共享前缀被改写 / 磁盘比基线短 / 基线对不上 / 文件不可解析 ⇒ 回退时丢对方一侧（WARNING 点名原因，不静默）。候选加固 = 把不可判形态的对方侧隔离进 sidecar 而非丢弃。**裁定指针：OQ-5 未裁定（「隔离 vs 丢弃」语义）**，故本轮只补确定性并发写回归测试（S-8），不改语义。触发条件 = 出现真实触发案例或用户裁定升级 |
| A35 | HTTP 入口会话/事件持久化（在途 run 与 SSE 缓冲重启即丢） | `active` | 会话历史已落盘（SessionStore，CLI 与网页共用），重启只丢在途 run 与 SSE 事件缓冲（重连有 `resync_required`→快照兜底）。**2026-11-05 前置缺口已闭合**：网页 handler 自建 engine 却从不订阅事件接收器 ⇒ `EVENTS_ROLLOUT_ENABLED` 在网页入口是死键（与 A44 闭合前的 REPL 同款）；现按**项目根**订阅（`_build_event_sink(root=…)`，多项目控制台下 cwd ≠ 项目根）。判据 `tests/test_http_events_rollout.py`（2 例成对：默认关零文件 / 开关开落项目根且以 `run_completed` 收尾）+ 变异 3/3 全红（`scripts/mutation/mutate_http_rollout_sink.py`）。**残余 = 读侧回放**：重启后仍未从 `.heagent/runs/<run_id>/rollout.jsonl` 重放（复用既有 `read_rollout`，不新做投影持久化架构）。触发条件不变 = 重启丢在途 run 实际困扰 ≥2 次，或长 run（>10min）常态化。**2026-11-05 用户裁定：不做**（读侧回放继续挂账，状态维持 `active`；理由 = 它要动 SSE/WS 重连语义，而触发条件尚未到） |
| A36 | 全局级 MCP 注入签名配置入口 | `active` | **2026-11-05 复核仍零使用**：项目级与全局级 `.heagent/injection_signatures.json` 均不存在 ⇒ 加全局入口属 YAGNI（跨项目共享的现成成本 = 复制一个 JSON 文件）。本轮收窄「静默失效」：项目级缺失时若全局文件存在，加载器显式 WARNING 说明它被忽略（不加载、不静默），判据 `tests/test_mcp_mapping.py::test_global_signature_file_is_ignored_with_warning`（另有零噪声对照）+ 变异 2/2 全红（`scripts/mutation/mutate_mcp_signature_hint.py`）。触发条件 = 实际开始写自定义签名且需跨项目共享。注意：签名围栏非真正安全边界，加码不改变「须 OS 沙箱兜底」立场。**2026-11-05 用户裁定：保留**（维持 `active` + 显式告警口径，不转 `retired`） |
| A41 | 兄弟 Story 越集写互相误归因（`goal/write_audit.py:146-157`） | `frozen` | 共享工作区审计无法按写者归属，兄弟 Story 越集写会落入本 Story 的 Δ 判负（连带置闩）。**裁定指针：AD-20（OQ-4 未裁）**；短期靠围栏预防层降低概率。**2026-11-05 收窄（用户裁定：一并处理至可行边界）**：判负消息与 `workflow_write_audit` 事件如实披露「写者无法归属到本 Story」（`shared_workspace` + `a sibling may be the author`），不再默认归因到本 Story；判负语义（FAILED + 撤闩）不变——写集并集对批内每个成员同形，越集写同样会被**写者自己**的审计判负，故误伤面 = 「无辜兄弟也失败 + 闩」，根因仍需 AD-20 物理隔离（判据 `tests/test_story_write_audit.py::test_violation_discloses_shared_workspace_attribution` / `::test_solo_batch_violation_has_no_attribution_caveat` + 变异 `scripts/mutation/mutate_write_audit_content_delta.py` M4） |
| A52 | 坏 `hooks.json` 静默跳过（engine/hooks.py load） | `active` | `HookManager.load` 对文件不存在/JSON 损坏/单条非法一律跳过 + WARNING——与「显性失败、缺失宁可显性报错」项目准则相悖。**2026-11-13 用户裁定：撤销 Epic 63 立项，残差转台账**；修正 = fail-fast（启动期坏配置显性报错指明条目；文件不存在保持合法空载）。触发条件 = 下一个进入实现的周期顺带执行（quick-dev 一发子弹即可，无需独立立项） |
| A53 | PostToolUse hook stdout 不进对话上下文 | `active` | 现状 = PostToolUse 钩子 fire-and-forget（stdout 仅日志）；Claude Code 语义会把非阻断 stdout 注入 transcript。**2026-11-13 用户裁定：撤销 Epic 63 立项，残差转台账**；候选增强 = 非阻断 hook stdout 注入对话（需定预算与截断口径）。触发条件 = 出现把 hook 输出喂回模型的真实需求（当前零使用） |

## 已按 Epic 归档

| ID | 主题 | 状态 | 正文 |
| --- | --- | --- | --- |
| Z-D10 / Z-D11 / Z-D18 / Z-D20 | Epic 48 TCP 入口与日志审查 | 已闭合 / OBSOLETE | [`epic-48.../deferred-work.md`](../archive/epics/epic-48-TCP网络接口周期/deferred-work.md) |
| Z-D13 / Z-D14 / Z-D15 / Z-D19 / Z-D21 / Z-D22 / Z-D23 / A8 / A9 / A10 / A12 / A15 / A16 / A17 / A18 / A19 / A23 | Epic 50 网页控制台审查 | 已闭合或裁定维持现状 | [`epic-50.../deferred-work.md`](../epics/epic-50-网页控制台周期/deferred-work.md) |
| Z-D24 / A2 | Epic S1-S4 沙箱裁定 | 已闭合（裁定不实施） | [`epic-S1-S4.../deferred-work.md`](../archive/epics/epic-S1-S4-沙箱硬化周期/deferred-work.md) |
| A25 / A26 / A27 / A28 / A33 / A37 / A38 / A39 | Epic 51 Goal/workflow 收口优化 | 已闭合 | [`epic-51.../deferred-work.md`](../epics/epic-51-goal-workflow优化周期/deferred-work.md) |

## 本轮闭合（2026-10-26 S-6 归一 + 2026-11-02 小步清债 + 2026-11-05 审计语义收窄；证据齐备，**不是**退役）

> 这些条目原先散在 `deferred-work.md` 的「仍需维护的观察」与 Epic 52 review 段里。S-6 归一时逐条核对代码，
> 确认已被既有实现或本轮 E1 闭合。与「退役」的区别：这里有可复跑的判据，不是「不做」。

| ID | 主题 | 闭合证据 |
| --- | --- | --- |
| A45 | `KeyboardInterrupt` / `SystemExit` 与 `CancelledError` 的中断语义不完全一致 | 语义已于 2026-10-23 裁定（A39）；本轮 S-3 把「三分支 → `cancelled`、其余 → `executor_failed`」固化成 `docs/frame.md` 的矩阵表，由 `tests/test_workflow_transition_reason.py::test_interrupt_matrix_matches_absorb_semantics` 与 `::test_interrupt_matrix_covers_vocabulary` 双向钉住 |
| A46 | 异常处理中的 `transition()` 理论上可能覆盖原始异常 | `src/heagent/engine/workflow_transition.py:41` 的 `raise … from exc` 保留 cause 链；`tests/test_workflow_transition_reason.py::test_transition_failure_preserves_cause_chain` 断言 `__cause__` 为 `KeyError`；`scripts/mutation/mutate_state_invariants.py` 的 M5（去掉 `from exc`）会把它打红 |
| A47 | `reason: str(exc)` 可无上限写入 `next_action` / `blocked_reason` | `src/heagent/engine/workflow_runner.py:41` `_MAX_REASON_CHARS = 2000` + `:53-57` `_bounded_reason`（A37 已落）；`tests/test_workflow_transition_reason.py::test_bounded_reason_caps_without_raising` 与 `::test_oversized_reason_is_truncated_on_write` 钉住 |
| A48 | `workflow_step_failed` 未记录驱动转换的事件类型；checkpoint 缺 `last_event` / `transition_reason` | `last_event` 已由 A38 落地（`workflow_runner.py:149`、`checkpoint.py`）；`transition_reason` 由本轮 S-1 补齐（字段 + 唯一写点 + 双向往返）；`workflow_step_failed` 的 `transition_event` 在 `:408` / `:700` 两处发射 |
| A50 | `auto_archive._append_archive` 无锁 read-modify-write（origin=新增，2026-10-29 epic-59 审查落账；2026-11-02 闭合） | `src/heagent/memory/auto_archive.py` 的 `_append_archive` 改走 `atomic_update_text`（归档文件自身 `.lock` 内读改写，与 `memory/compact.py::_append_archive_section` 同款）。判据 `tests/memory/test_auto_archive.py::TestArchiveAppendSerialization`（2 例：① 机制——归档路径必须出现在 `atomic_update_text` 调用里；② 行为——两写者并发追加两段小节都在）。判据强度已用组件副本变异验证（2/2 变红）：把 `_append_archive` 退回裸读写即打红。`docs/frame.md` §4.6 补「归档文件自身的追加也在自身 `.lock` 内读改写」一句，判据条数 14 → 16 例 |
| A49 | `EmbeddedHttpService.failure` 传播路径缺直接测试（2026-11-02 闭合） | 真实双 listener 故障注入已落地：`tests/test_cli_http_lifecycle.py::test_one_listener_dying_is_surfaced_while_the_others_keep_serving`——真 HTTP server + 两个真 WS listener（真 socket / 真端口），在 **uvicorn 自己的 poll 循环**里注入（`Config.callback_notify` 抛错 ⇒ `Server.main_loop` 在 tick 中抛出，不替换 HeAgent 的 `serve_forever`），断言 `failure` 拿到该异常且不被后续抖动覆盖、兄弟 listener 仍应答（裸 HTTP 状态行）、HTTP 健康端点仍 200、`close()` 后历史失败不被清空。判据强度已用组件副本变异验证（去掉 `_failure = error` 即打红）。`docs/frame.md` §4.17「默认 CLI 自启动」行补该传播链与判据落点 |
| A44 | 交互 REPL 不挂事件 rollout sink（2026-11-02 闭合） | `src/heagent/cli/interactive.py::_run_chat` 在引擎构造后与单次模式同口径订阅 `_build_event_sink(settings, json_output=False)`（默认关闭不变，rollout 含工具原始输出；REPL 无 `--json` ⇒ sink 恒不含 stdout 流）。判据 `tests/test_cli_events_rollout.py`（2 例成对：① 开关关闭 ⇒ 一轮跑完后零 rollout 文件，且先断言 provider 真被调 1 次；② 开关打开 ⇒ `<rollout_dir>/<run_id>/rollout.jsonl` 落盘，kinds 含 `run_started` 且以 `run_completed` 收尾）。判据强度已用组件副本变异验证（去掉订阅 ⇒ 「开关打开」用例变红，「关闭」用例保持绿）。`docs/frame.md` §4.12 补「订阅点」一段 |
| A40 | 审计基线已脏文件检测盲区（2026-11-05 闭合） | Δ 由「after 路径集 \\ before 路径集」改为**内容指纹**比较：会话前采集 `_WriteAuditBaseline`（Git 证据 + 已脏 tracked 路径的流式 sha256），会话后用自己的指纹表逐路径比对（`_content_fingerprints` / `_fingerprint_paths`，仓库根相对解析同 A43）。既有脏文件被本 Story 再改 ⇒ 指纹变化 ⇒ 判负；未改动的既有脏文件不误报。判据 `tests/test_story_write_audit.py::test_dirty_baseline_file_touched_again_is_flagged` / `::test_dirty_baseline_file_untouched_is_not_flagged`；判据强度 `scripts/mutation/mutate_write_audit_content_delta.py` M1（退回路径差集即红）。残余：文件读不到（权限 / 中途消失）记空串 ⇒ 与「基线不存在」同向（多判负、不漏判）；把既有脏改动**还原成 HEAD 内容**会让该路径离开变更集、无法捕获（净效果为零，方向仍是多判负）。`docs/frame.md` §4.13 审计段同步 |
| A42 | 违规写无补救语义（2026-11-05 闭合） | 条目原文要求「人工清理指引**或**回滚工具」，本轮交付指引面：判负时把越集路径 + 基线 revision 写进 `workflow_write_audit` 事件留档（闩后串行重跑的新基线已含旧违规 ⇒ 该事件是唯一持久记录），reason 内给 `git diff <base> -- <path>` / `git restore --source=<base> -- <path>`（新建路径改为删除）。判据 `::test_violation_event_records_paths_base_and_remediation` + 变异 M2 / M3。残余 = 自动回滚未做（需会话前快照，属 AD-20 层，非本条目要求） |
| A43 | `_host_artifact_relpath` 参照系（2026-11-05 闭合） | 旧记载的两条前提经实测**否证**：`Path.relative_to` 在 Windows flavour 大小写不敏感、唯一调用点 `_goal_verify_workspace` 已 `.resolve()`。真实残量 = 三源参照系不同（`git diff --name-only` = 仓库根相对、`git ls-files --others` = cwd 相对、产物 = 工作区相对）；收窄 = `_git_toplevel` + `_repo_relpath` 把产物换算成仓库根相对后并入 tracked 豁免，untracked 侧维持 cwd 相对（同根部署为恒等变换）。判据 `::test_repo_relpath_reference_system_branches` / `::test_subdir_workspace_excludes_host_artifact` / `::test_subdir_workspace_untracked_artifact_not_warned` + `scripts/mutation/mutate_write_audit_reference.py` 4/4 红。**2026-11-05 用户裁定：残余可读作已足够**（`GIT_DIR` 重定向 / 走不到 `.git` 时退回旧语义，方向是多判负、不漏判）⇒ 本轮闭合，不另立收窄周期 |
| A51 | 发布缺口：无 CHANGELOG 载体、无「版本号 ↔ git tag」守卫（origin=新增，2026-11-11 S-14 落账） | `CHANGELOG.md` 建立（Keep a Changelog 形态：`## [Unreleased]` 常驻 + `## [0.9.0] - 2026-11-11` 首节，并写明 0.9.0 之前的历史未逐条回填及追溯命令）。版本真源守卫 = `tests/test_release_workflow_contract.py` 共 6 例：两处真源相等（ast 取 `__version__` + tomllib 取 `project.version`）/ 版本纯 `X.Y.Z` / HEAD 带 `v*` tag 时 tag == 版本 / CHANGELOG 有 `Unreleased` 段 / CHANGELOG 有当前版本节且带日期 / CHANGELOG 标题格式合法且 `Unreleased` 不带日期。变异 **6/6 红**（改 pyproject 单侧 / 写成 `0.9` / 副本打 `v1.0.0` / 删 `Unreleased` / 版本节改名 / `Unreleased` 带日期）。`pyproject.toml` 的 `[project.urls]` 增 `Changelog` 指向 CHANGELOG.md。2026-11-11 闭合 |

- **52-3 AC1（端到端围栏贯通冒烟）**：已闭合（2026-10-26，Epic 57-3）——真实注册表 `file_write` handler 经
  `policy.evaluate_tool_call → executor.execute` 全链贯通：集内写真实落盘、越集写围栏 BLOCKED 且 handler 零触达。
  贯通首跑暴露一处真实缝隙：真实 handler 从运行时绑定（`bind_workspace_root`）解析根而非 RunContext，测试已按主链路
  `_runtime_scope` 同形态绑定。证据 `tests/test_write_allowlist.py::test_e2e_chain_*`（2 例）。
  **附带发现（不另行立项）**：围栏（policy 用 RunContext 根）与工具（handler 用运行时绑定根）在二者不一致时可出现
  「围栏判 A 根、工具写 B 根」的错位窗口——当前主链路两者恒同源（loop 每 run 绑定 `run_context.workspace_root`），
  错位不可达；登记供未来改 run 上下文装配时复核。

## 本轮非目标（heagent-improvement-plan，2026-11-11）

> 来源：`_he-output/works/heagent-improvement-plan/step-04-define-product-scope/report.md` 的「非目标」段（11 条）。
> 这些是**本轮明确不做**的项，不进活动表（不是 A 号待办），故不参与活动计数；`NG-` 前缀与 A 号体系隔离。

| ID | 非目标 | 触发条件（何时重新评估） | 严重度 |
| --- | --- | --- | --- |
| NG-1 | 不从零建 CI、不新增 CI job（`ci.yml` 已有 8 job） | 勘差表（S-6）举证某 FR 缺口无法由现有 job 关闭 | Low |
| NG-2 | 不启用 merge 自动发 PyPI beta（Q2） | 发布频率 ≥ 每月 1 次，且已配置 Trusted Publisher | Medium |
| NG-3 | 不做 auto-bump（FR12.3） | 手工改版本号导致 ≥2 次发布事故 | Medium |
| NG-4 | 不做 CHANGELOG 自动生成（FR12.4） | 用户/下游要求按版本查看变更，或发版频率 ≥ 每月 1 次 | Low |
| NG-5 | 不做 devcontainer（FR13.1 残余） | 新贡献者环境搭建受阻 ≥2 次，或 CI 矩阵不足以复现问题 | Low |
| NG-6 | 不在拆分期下调覆盖率门（Q3） | 不得触发；下调即违反 INV-6 | High |
| NG-7 | 不一轮拆多个文件（RQ-4） | 不得触发；违反则三证据无法归因 | High |
| NG-8 | 不删除既有架构守卫、不缩减 `FORBIDDEN_RUNTIME_IMPORTS`（RQ-5） | 不得触发；违反即 INV-4 失效 | High |
| NG-9 | 不改 `network/` 既有 4xx/5xx 键名/语义/状态码，不把错误码做成对外 ABI（Q5 / RQ-8） | 有外部使用者明确要求，且愿意接受 breaking 版本 | High |
| NG-10 | 不在传输层载荷携带文档链接（Q6 / RQ-9） | 有外部客户端明确要求从错误体取文档链接 | Low |
| NG-11 | 不把 `pip-audit` 转硬门（OQ-3） | 出现高危 CVE 且现有软门未及时暴露 | Medium |
| NG-12 | 不为文档引入新运行时依赖（`network/` 受 stdlib + pydantic + pub.safe_logging 约束） | 不得触发；违反即破 INV-4 | High |

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
| Z-D3 | provider 回退骨架是否统一 | 评估结论为不收敛：chain、key_rotation、switchable、router 的回退条件、粘性和索引语义有意不同；补充互指注释，行为不变（证据：`providers/{chain,key_rotation,switchable,router,retry}.py`、`tests/test_retry.py::TestPoolFallbackPolicy`、提交 `beea1a2`） |
| A3 / A4 / A5 / A11 / A24 | 入口、GUI、观测与运行姿态 | 已闭合，正文留在相关周期记录或提交证据中 |
| A1 / A6 | 技能资源与路径级审批前置裁定 | 裁定维持现状或维持条件性；边界见 `docs/frame.md` 五 |
| A29 / A30 / A31 / A32 | 2026-10-07 架构简化与层次收敛 | 已闭合；证据见提交记录、源码和测试 |
| 技能资源 TOCTOU 残余竞态专项评估 | 已评估（2026-10-20）。事实：单一安全内核 `path_safety.read_bytes_under_root`（围栏 resolve → 加固 open → fstat 普通文件校验 → 持 fd 读满）双通道——POSIX 逐组件 openat（2026-09-27 硬化）收窄至组件级竞态，Windows 无 dir_fd 走整路径回退（窗口与硬化前同宽，本机实际通道）；importer 落地为 verify-before-land（temp 复制后复核逐文件摘要，通过才 `os.replace`，检查期哈希→落地拷贝的窗口已闭合）；包读侧另有钉定摘要校验。裁决：check 与 use 同进程同权限，TOCTOU 不跨越信任域——能赢下任一窗口的攻击者无需竞态即可直写技能根或经 shell 直读凭证（frame.md 既有登记面），无新增可提升暴露面 ⇒ **不另立收窄周期**，维持 OS 沙箱兜底立场。附带确证：manifest.csv / `_hash` 直读为 load-bearing 例外（csv raw newline 语义 / 任意位置临时树哈希，围栏不适用）；`skill_meta.load_meta` 在 src 内零调用方（死代码路径，非活窗口）；`SkillStore._read_text` 实例锁已覆盖 Windows 读写互斥。边界：`tools/path_safety.py`、`skills/{skill_store,skill_packages,skill_importer}.py` |
| 架构简化再勘验（2026-11-06） | 已裁定（2026-11-06，方案 news/simplify_plan.md）。2026-11-03 遗留 4 候选逐一按符号重测：A1 `_execute` 终态五分支净≈0（共享尾缀仅 append+close 2 行×5）；A2 串行/批失败合并净−4~6 但两路闩置位刻意不对称（动 AD-18 闩序，中险不对价）；A3 `_serve_web`⊕EmbeddedHttpService 净−10~15 但公告文案两路刻意不同+9 处 setattr patch 缝（维持高风险裁定）；A4 `skill_meta.load_meta` 复核仍 test-only（默认保留）。**全部裁定不做，代码精简批准=0**；简化杠杆转架构级：B1 统一执行世界 seam（shell.py session 静默忽略 command_runner + session.py:191 内部又读 slot，双面并存仅运行期 WARNING）待 BMAD 立项；B2 文档纪律三件已落 frame.md §4.15/§8.4/§4.6；B4 SKILL.md 双开关已落 `83b2f22`（2026-11-06）。勿对 catalog.py 再提无净行数预估的去重 | `memory/dream.py`、`network/http_server.py`、`engine/workflow_runner.py`、`cli/http.py`、`skills/skill_meta.py`；边界=frame.md §4.6/§4.15/§8.4 |
| 架构简化从零再勘 v2（2026-11-06） | 已执行（方案 news/simplify_plan_v2.md，git 忽略）。批次 5/6/7 已提交（`7edd546`/`a703d7c`/`75118f7`，生产码净负、测试面 +42 系钉策略代价）；批次 8（C6 流事件映射统一）执行期裁定不做（四轴契约面刻意不同）；批次 3=B4 双开关已落 `83b2f22`；批次 9 卡 A housekeeping 迁回顶层已落 `3dec905`（spec 在 `epics/epic-60-结构精简周期/`）；卡 B provider 装配规则迁 providers/composition.py 已落 `89ff596`（同目录 spec，呈现薄壳保缝、+2 契约钉测试）；**卡 C+D（goal 文档持久化迁 document.py / 写审计 12 符号迁 write_audit.py，emit 注入 + 变异脚本随迁）与卡 E（runner 构造期参数化 + 双 runner 构造期判定 + 三钉）已实施**（同日完成，spec 均在 `epics/epic-60-结构精简周期/`；批次 9 全收口） | 边界=frame.md §4.6/§4.15/§8.4 |
| fact_compact 崩溃窗口定向审查 | 已审查（2026-11-06，dsh 对标 #3），**无缺口、无代码改动**。窗口=「留底已写（archive 小节带 `fact_compact` 标记）→ MEMORY.md 比较后写前」崩溃：残留为留底与现行**并存的可检测重复态**——留底小节即崩溃遗留的合成痕迹；无静默丢失路径（归档并发覆盖已由 A50 闭合；比较后写防并发吞写，冲突放弃本批、留底保留）；同批 merge 可原样重放恢复（source 精确匹配仍唯一在场），失败方向与「宁重复不丢失」一致，不引入锁文件语义。崩溃窗口口径已落 frame.md §4.6 语义压缩段 | `memory/compact.py`（compact_facts/_append_archive_section）；边界=frame.md §4.6 |

## 维护规则

- 新增未闭合项先登记 ID、**状态（active / scheduled / frozen / retired）**、触发条件、裁定与验收证据，再开始实施。
- `frozen` 必须带**裁定指针**（哪个 OQ / 哪份记录）；没有指针的「挂起」不是状态，是遗忘。
- 显式退役必须齐备 5 字段，缺一项即无效；退役 ≠ 删除，正文一律保留。
- 已闭合项按 Epic 归档正文；不要在本文件复制完整 review 报告。
- `blocked` 需要产品或架构裁定，不能由实现者静默关闭。
- **单向收敛**：条目正文只在本文件；`deferred-work.md` 只保留入口与索引（同一 ID 不得同时出现在两个文件）。
