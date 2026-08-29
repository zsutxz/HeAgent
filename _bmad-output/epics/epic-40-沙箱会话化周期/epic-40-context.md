# Epic 40 Context: 沙箱会话化执行（hermes 式后端抽象）

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

把 Agent 的 shell 命令执行从「无状态逐命令透传」升级为「per-task 会话化沙箱执行」：每个任务（run）获得持久 workspace、cwd 跨命令保持、teardown 清理；策略与执行路径可感知沙箱后端强度分级（`passthrough < job < firejail < container`，container 档仅预留）；弱于 container 的后端不得触发审批降级；敏感环境变量剥离支持声明式豁免。框架使用者在 Windows/Linux 均获得会话级沙箱工作流，且所有新能力在文档中明示 defense-in-depth 性质（非真边界，须 OS 级沙箱兜底）。

> 注：本周期无独立 PRD/architecture/UX 规划产物——周期目录仅含 epics.md；本 context 编译自 epics.md（含其 frontmatter 记录的规划输入：会话范围评估、CLAUDE.md、docs/frame.md、源码勘察）与架构权威文档（CLAUDE.md、docs/frame.md 4.4/4.12/五）。

## Stories

- Story 40.1: 沙箱会话目录管理（FR-1）
- Story 40.2: 沙箱后端强度分级（FR-2）
- Story 40.3: 声明式环境变量豁免（FR-3）
- Story 40.4: SandboxSession 会话生命周期（FR-4）

## Requirements & Constraints

- **会话目录约定**：任意 run_id 幂等获得统一规范的沙箱 workspace 目录（如 `.heagent/sandboxes/<run_id>/`），不依赖执行器状态；Firejail 将其作为 `--private` 根，WinJob 将其作为命令 cwd（目录约定，无文件系统隔离——代码注释与文档明示）。未启用会话目录时行为与现状完全一致；后端不可用时维持既有 warn + Passthrough 降级，不因目录管理引入新失败路径。
- **后端强度分级**：各后端正确声明档位（Passthrough→`passthrough`、WinJob→`job`、Firejail→`firejail`；`container` 存在于枚举、无实现后端）；`SANDBOX_REQUIRED` 执行路径查询到的档位须以 Pydantic 模型传递（如经 RunContext.metadata 或 verdict），无裸值。弱于 container 的后端一律维持原审批要求——需测试锁定，不得触发审批降级。
- **env 豁免**：allowlist 命中的环境变量传入 shell 子进程，其余命中剥离规则的变量仍被剥离；allowlist 未配置时行为与现状逐字节一致（默认全剥离）；配置入口为 `Settings` 字段 + `.env` 覆盖（配置文档同步更新）。豁免仅作用于 env 剥离，不影响 `path_safety` 凭证文件读写 deny 与 `SafetyGuard` 凭证路径拦截。
- **会话生命周期**：同一 run 的连续命令复用同一 SandboxSession（同一 workspace；Firejail 下同一 `--private` 视图）；cwd 跨命令保持（`cd sub && touch a` 后 `pwd && ls` 可见）；run 结束（正常/异常/取消）按配置清理会话目录（保留/删除），无孤儿进程（复用既有 killpg / KILL_ON_JOB_CLOSE）；`SANDBOX_REQUIRED` 但未注入 runner 时既有 fail-safe 报错语义不变。
- **非功能约束**：所有新增能力明示为 defense-in-depth 非真边界（Windows 路径明确标注零文件系统/网络隔离）；Windows 主力平台（WinJob + Passthrough）全路径可用，Linux firejail 保持优雅降级惯例；跨模块数据一律 Pydantic 模型；库代码全异步；新逻辑配意图级 pytest 断言。
- **兼容与文档义务**：既有配置入口 `SANDBOX_BACKEND` env / `--sandbox` CLI 只扩展不破坏；`docs/frame.md`（4.4/4.12/五）与 `CLAUDE.md` 已知缺口随代码交付同步更新。

## Technical Decisions

- **增量基线（现状锚点）**：`FirejailBackend` 已有 profile→args 映射、`--private`、`os.killpg`；`WinJobBackend` 已有 Job Objects、`KILL_ON_JOB_CLOSE`；`engine/executor.py` 的 `execute_in_sandbox` 现为无状态逐命令路径；`scrub_sensitive_env` 已存在（Epic 36-39 交付）。本周期全部为在此基线上的增量。
- **Firejail 复用既有映射**：会话目录经现有 `workspace_root` → `--private` 路径生效，不新增参数通道。
- **注入与依赖方向不变**：沙箱后端注入仍经 `EngineContainer`（`command_runner=`），`AgentLoop` 零改动；`engine/` 依赖 `types`/`exceptions`/`tools.safety` 不变；工具执行链固定为 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler，SandboxSession 重构不得改变该链路形态。
- **升级路径预留**：Linux bubblewrap/nsjail、Windows AppContainer 将来作为新 Backend 落入 container/更强档位，分级框架须使其免重构接入。

## Cross-Story Dependencies

- 内部实施顺序：P1 = Story 40.1/40.2/40.3（纯增量，不动主干）先行；P2 = Story 40.4（重构 `execute_in_sandbox` 主干，需完整回归既有 sandbox 测试）。
- 规划判定 epic 内 story 间无前向依赖，Epic 40 自身独立成立（不含 FR-5 也完整）。
- FR-5（execute_code RPC 沙箱工具）deferred 至未来独立周期，本周期不建 story，不得顺手实现。
