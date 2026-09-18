# 沙箱会话化周期 · Retrospective（Epic 40）

> 日期：2026-09-18（**补做**：原 `_bmad-output/sprint-status.yaml:398` 标记 `epic-40-retrospective: optional`）
> 范围：`_bmad-output/epics/epic-40-沙箱会话化周期/`（Epic 40，4 个 story：`40-1-session-workspace-directory`、`40-2-backend-strength-tiering`、`40-3-env-scrub-allowlist`、`40-4-sandbox-session-lifecycle`）
> 动机：把 Agent 的 shell 执行从「无状态逐命令透传」升级为 per-task 会话化沙箱执行（`epics.md` Epic 40 段）

## 一、做了什么

| Story/交付项 | 核心交付 |
|------|----------|
| 40-1（FR-1）· commit `72f8105` | per-run 会话目录（`.heagent/sandboxes/<run_id>/`）；Firejail 复用既有 `--private` 通道、WinJob 仅作子进程 cwd（14 files，+923/−17） |
| 40-2（FR-2）· commit `26cda4b` | `SandboxTier`（`passthrough < job < firejail < container`）+ `can_relax_approval` 仅 container 为真（`src/heagent/tools/sandbox.py:50,70`） |
| 40-3（FR-3）· commit `fb932d1` | `SANDBOX_ENV_ALLOWLIST` 声明式 env 豁免（`.env.example:242`），未配置时行为不变 |
| 40-4（FR-4）· commit `e44b9df` | `SandboxSession` 会话生命周期 + 尾捕获 marker（`tools/sandbox.py:644` `_MARKER = "HEAGENT_CWD"`） |
| 版本与登记 | `10a478f` 周期登记 + bump 0.4.0（2026-08-26）；`4d20a7c` 版本 0.4.0 → 0.5.0（周期收尾） |
| E40-D1..D4 补齐 · commit `adfc716` | 孤儿目录 GC、`<shell-workspace>` 可见性、WinJob cwd 可测缝、CLI/GUI 三态平权（22 files，+898/−95，2026-09-15） |
| 补丁 spec · commit `f08ebe5` | shell 输出上限：`_MAX_CHANNEL_BYTES = 512 * 1024` + `[truncated]`（`tools/sandbox.py:89,90`；`_format_result` 在 `:130`） |

## 二、做对的

1. **「有目录」不等于「有隔离」的诚实门**——`<shell-workspace>` 块只在目录真正生效时注入（要求存在真实后端，而非仅开关打开）；依据 `deferred-work.md` E40-D2 段与 `CLAUDE.md` 非真边界立场。
2. **弱后端不降审批用代码 + 测试双重锁死**——`SandboxTier.can_relax_approval`（`tools/sandbox.py:70`）仅 container 为真，`epics.md` FR-2 的验收明确要求「测试锁定」。
3. **创建方与回收方共用同一表达式**——`sandbox_sessions_root`（`tools/sandbox.py:577`）被创建方（`engine/container.py:309,312`）与回收方（`housekeeping.py:39,172`）共用，消除两处约定漂移；E40-D1 段写明此设计理由。
4. **交付后补齐逐项带独立测试**——E40-D1..D4 分别有 `tests/test_housekeeping.py`、`tests/test_agent_loop.py`、`tests/test_winjob_backend.py`、`tests/test_engine_p0.py` 承接，不靠手工验证。

## 三、可改进的

1. **FR-5 至今既无实现也无 story**——`epics.md` 记「FR-5: （deferred，未映射）execute_code RPC 沙箱工具」，本回顾未核实任何后续排期记录。
2. **4 条遗留项挤进一个大提交**——`adfc716` 一个提交内含 GC / 可见性 / 可测缝 / CLI 平权 + 文档（22 files，+898/−95），回滚与二分定位粒度粗（证据：`git show --stat adfc716`）。
3. **`spec-shell-output-limit.md` 正文编码有损**——该文件中文在 `file_read` 与 shell `type` 两次独立读取中一致呈乱码（title 行末字符显示为「璁?」），而同目录其余 md 读取正常，机器解析困难。
4. **交付期已识别的缺口仍留在活动台账**——沙箱进程数限额（原 §17.4-A6，低，**2026-09-18 已闭合**）、`RoleSpec.sandbox_profile` 死字段（原 §17.4-A5，低，**2026-09-18 已删除字段闭合**）、MCP stdio 子进程不经沙箱（§17.4-A2，中-高，仍开）。

## 四、教训

1. **「目录约定」必须逐处标注非隔离**——把 WinJob 的子进程 cwd 说成文件系统隔离会制造安全错觉，故 `--private` 的语义需要专门修正（E40-C1）并与文档同步。
2. **输出管道共用带来尾部耦合**——cwd/rc marker 与用户 stdout 走同一管道，因此截断必须保留尾部、退出码必须回填（`f08ebe5` 截断 + `69607dc` 修 SandboxSession 退出码）。
3. **交付时就该给「回收方」建 story**——E40-D1 的 crash 孤儿目录 GC 在交付期缺位，靠一个星期后的遗留项补齐；会话目录若只创建不回收，内部状态会无界增长。
4. **诚实门值得复制到其他「能力已开但未生效」的场景**——宁可少报一个路径，也不给出与真实 cwd 不一致的提示。

## 五、遗留项状态

- 已闭合：E40-D1 / E40-D2 / E40-D3 / E40-D4 / E40-C1 全部 Closed（`deferred-work.md` 状态总览表）；D1..D4 闭合者 = `adfc716`（2026-09-15），C1 = 文档修正。
- 仍开（跨周期活动项）：仅 MCP stdio 子进程不经沙箱（中-高，§17.4-A2）——指向 `_bmad-output/implementation-artifacts/deferred-work-archive.md`。原列于此的沙箱进程数限额与 `RoleSpec.sandbox_profile` 死字段已于 2026-09-18 闭合（Z-D9 / Z-D8）。
- 未建 story：FR-5 `execute_code` RPC 沙箱工具（`epics.md` deferred 段）。
- story 文件状态：`stories/40-1..40-4` 四份 frontmatter 均为 `status: 'done'`（各文件第 5 行）。

## 六、结论

Epic 40 把 shell 执行做成了会话级工作流，并且把「非真边界」这条立场同时落进了代码（诚实门）与文档（`--private` 语义修正），这是本周期最扎实的部分。短板不在实现而在收口节奏：FR-5 从未建 story、4 条遗留项与文档混在同一个大提交、规格文件编码损坏——下一轮同类周期应把「回收方」与「可见性」在交付期就纳入 story，并把补丁提交按条目拆分。
