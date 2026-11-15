# HeAgent BMad 开发文档整合总览

> **生成与维护**：2026-08-18 建立，按代码与 `sprint-status.yaml` 持续校正；**2026-11-15 重组为当前状态文档**（周期详解、台账归档与复核记录已迁 [`retrospective-all-cycles.md`](retrospective-all-cycles.md)）。本文只保留当前口径：状态、缺口、路线图、待完成索引与文档地图；活动 deferred 正文以 [`implementation-artifacts/open-items.md`](implementation-artifacts/open-items.md) 为准，周期级闭合条目以各自 `deferred-work.md` 为准。
> **范围**：`_bmad-output/` 全部 **25 个开发周期**（Epic 1-57 + S1-S4）+ 补丁 spec 归档（原 `patches/`）+ engine 增量，整合自各周期 brief / prd / architecture / epics / stories / sprint-status / retrospective / deferred-work 与补丁 spec 共 90+ 份文档。
> **定位**：本文是 BMad 规划产物的**当前状态与导航**——当前状态（§十七）、待完成索引（§17.4）与文档地图（附）。历史、跨周期模式与台账归档见 [`retrospective-all-cycles.md`](retrospective-all-cycles.md)。它**不是当前代码事实**：代码现状以 `docs/frame.md` 为准，规划与实现冲突时以 `src/` 为准。
> **权威状态**：所有 Epic/Story 状态以 `_bmad-output/sprint-status.yaml`（2026-07-23 整合，唯一写目标）为单一权威。

---

## 目录

1. [十七、当前状态与下一步](#十七当前状态与下一步)
2. [附：文档地图速查](#附文档地图速查)
3. [历史记录（周期详解、台账归档、review 闭合索引）→ retrospective-all-cycles.md](retrospective-all-cycles.md)

---
## 十七、当前状态与下一步

### 17.1 当前状态（截至 2026-10-27）

- **规划产物**：**25 个周期**（Epic 1-57 + S1-S4）登记于 `sprint-status.yaml`（2026-10-27 实测 **59 个 epic 键：58 `done` + 1 `in-progress`**——Epic 57 retro 遗留清理在途）；retrospective 仍 `optional` 的 epic 共 **14 个**（均未补做，清单见 §17.4-C）。产物整理：`patches/` 按归属 epic 归档（2026-09-15）、deferred 台账重组（2026-09-17）、story 产物按 Epic 分组。
- **架构优化周期（2026-09-21~22 交付）**：6 阶段全部 done——组合根收敛（`ResolvedRuntimeConfig`）/ loop façade（策略五模块 + `mark_terminal`）/ workflow 解耦（`goal/application.py`，cli_goal 991→680）/ 三域拆分（`tools/sandbox/` 包、MCP `client`+`registry_bridge`+`discovery_failures`、skills 四文件）+ 子进程监督内核统一（`cap_channel`/`reap_subprocess`）+ safe-open 单点（`open_text_under_root`）/ **事件契约 v2**（`RunEvent.duration_ms`/`error_kind`，SCHEMA_VERSION=2 黄金测试锚定 + workflow_step_* 事件）+ benchmark 基建 + 文档收口（`docs/extending.md` / `docs/troubleshooting.md` / `docs/goal-workflow.md` / frame 4.15）。档案：`implementation-artifacts/arch-optimization-cycle/`。
；2026-10-26 起条目改名 gpt→openai、anthropic→claude（`24b0bd1`），HTTP/WS 独立开关 `HTTP_ENABLED` / `WS_ENABLED`（`de8311b`）。
- **测试基线**：**3765 passed / 50 skipped / 28 deselected**（`pytest` 全量，2026-10-23 实测；deselect = integration + benchmark + 本机 WSL2 恒红的 3 条 `test_cli_http_lifecycle` 端口断言）；覆盖率 **92.47%**（gate 87）；`scripts/quality_gate.py` **六门**（goal smoke / 回归+覆盖率 / ruff check / ruff format / mypy / **bandit `-ll`**，与 CI lint job 同参数）；代码量 `src/` 42,277 行（168 个 `.py`）+ `tests/` 54,426 行（159 个 `.py`）。

### 17.2 已知缺口（详见 frame.md 第五章）

- `SafetyGuard` / `path_safety` / engine sandbox 均非真正安全边界——须 OS 级沙箱兜底。
- `ToolExecutor.execute_in_sandbox()` 默认 Passthrough 透传；`FirejailBackend`（Linux，仅 shell 子进程）/ `WinJobBackend`（Windows，Job Objects）可注入但均非完美边界；file/memory 等宿主进程内 I/O 工具不受覆盖。
- MCP annotations 不可信（server 自声明）——`PolicyEngine` 注解闸门仅 defense-in-depth。
- 用户可配置 MCP 注入签名入口（`spec-mcp-user-injection-signatures.md`）**项目级已交付**：`.heagent/injection_signatures.json` 受 workspace 围栏并进程内懒加载；全局/home 级 2026-09-15 **决策关闭（won't do）**。
- Dreaming 的 web_fetch 注入围栏端到端接入**已交付**（2026-08-19，Epic 35；标记透传，非真正边界）。
- 凭证 deny 的**项目级配置入口已交付**（`.heagent/path_deny.json`，2026-09-17）：仅支持收紧或精确豁免、无整体关闭入口、fail-safe 默认仍拒；`shell` 仍可 `cat .env`——非真正边界。
- **MCP stdio server 子进程未接入沙箱**（**2026-09-27 裁定 (c) 不实施**，登记为已知暴露面）：SDK 自行 `anyio.open_process` spawn，不经 `ToolExecutor.execute_in_sandbox`，Firejail / WinJob 对它零覆盖（见 §17.4-A2 → 归档 **Z-D24**）；**env 面已排除**（SDK 只继承 `DEFAULT_INHERITED_ENV_VARS`：win32 12 项 / POSIX 6 项，不继承 `*_API_KEY`）。
- sandbox 无开箱即用安全 profile 库、无人验证 profile 参数合法性、`S4-1` emit 事件仍 `skipped`（沙箱执行轨迹不可追溯）——逐条见 §17.4-C / §17.4-D。
- ~~沙箱**无进程数限额**~~ → **2026-09-18 已闭合**：新增 `SANDBOX_NPROC_LIMIT`（0=关闭），firejail 映射 `--rlimit-nproc`、WinJob 映射 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` + `ActiveProcessLimit`；同时修正 WinJob 常量表（`JOB_OBJECT_LIMIT_PROCESS_TIME` 原误写 `0x8`=ACTIVE_PROCESS 位，正确 `0x2`）。⚠ 两后端语义不对称（firejail 按真实 UID 计数，非 per-sandbox）。

### 17.3 下一步（路线图）

> 完整清单（活动台账项，条数与 ID 以 `implementation-artifacts/open-items.md` 头部为准——当前 7 条）见 **17.4**；本节只列需要排期的路线级事项，正文一律不重复。

- 🔜 **生产化**：PyPI 发布、Docker Hub 镜像、CI release workflow（版本已 `0.8.4`；`.github/workflows` 目前只有 `ci.yml` + `codeql.yml`，**尚无 release workflow**）。
- ⏳ **Epic 57（在途）**：retro 遗留清理（2026-10-26 立项，4 story 已 done）——清空 7 条 open retro items 后收口。
- ✅ **安全纵深（已裁定不做）**：MCP stdio server 子进程接入沙箱 —— 2026-09-27 用户裁定 (c) **不实施**（长命双向管道与既有 `CommandRunner` 形状冲突 + 隔离档属产品取舍 + 仍非边界），登记为已知暴露面（§17.4-A2 → Z-D24）。
- ⏳ **技能资源 TOCTOU 后续**：descriptor-relative open / 目录句柄、可信导入 snapshot、OS sandbox（§17.4-A1）。
- ⏳ **技术债**：benchmark 数据入库（历史趋势）、sandbox 开箱即用 profile 预设、Prompts/slash 结构化注册表（`engine/workflow.py` legacy 相位机归档已于 2026-09-17 `d835bd8` 完成）。

### 17.4 待完成工作（2026-09-24 整理）

> **权威层级**：活动（未闭合）条目以 `implementation-artifacts/open-items.md`（2026-11-15 起为唯一活动台账，从 archive 活动区抽出）为准；Epic/Story 状态以 `sprint-status.yaml` 为准；安全缺口以 `docs/frame.md` 五为准。本节同时登记**已闭环却仍被其他文档列为待办**的条目（B 组），避免下一轮重复勘察。

#### A. 活动台账未闭合条目（7 条——A34/A35/A36/A41/A52/A53/A54，**索引**）

> **2026-11-15 起**：活动项正文（7 条：A34/A35/A36/A41/A52/A53/A54）与触发条件一律以 [`implementation-artifacts/open-items.md`](implementation-artifacts/open-items.md) 为准。
> 已闭合编号索引（26 行表）、B 组修正表与 E 组决策关闭记录已迁 [`retrospective-all-cycles.md`](retrospective-all-cycles.md)（§三/§四）。

#### C. 纪律类产物滞后（非代码，2026-09-24 实测）

- **6 个 story 的 frontmatter 仍为 `status: backlog`**（与实际交付不符）：`36-1`、`36-2`、`36-3`、`37-1`、`38-1`、`39-1`（同 epic 的 `36-4` 已是 `done`）。
- **`45-1` / `45-2` 无 story 文件**（该 epic 目录下只有 `45-3`）；`spec-45-3` / `spec-46-1` 已在归档提交中删除或改名（仅存 git 历史）。
- **14 个 epic 的 retrospective 键值仍为 `optional`**：25-28、38-39、43-46、49、51、55、57（2026-10-27 实测自 `sprint-status.yaml`，均未补做）。已补做：36/37/40/41/42（09-18，键值已归一 `done`）、Epic 48（09-23）、Epic 50（09-27）。Epic 54 / 56 retro 产物在各周期目录。
- **`S4-1` 仍 `skipped`**（executor emit `sandbox_backend` + `sandbox_pid`）——沙箱执行轨迹不可追溯。
- `_bmad-output/README.md` 的导航已统一到当前归档规则：活动项只指向 `implementation-artifacts/open-items.md`（2026-11-15 起），已闭合项按归属 Epic 进入各周期 `deferred-work.md`。

#### D. 技术债与改进候选（低优先，2026-09-18 逐条核实仍在）

> **2026-09-28 证据路径刷新**：下列条目写于 2026-09-26 包化重构之前，旧路径 `cli.py` / `config.py` / `mapping.py` **已不存在**（`cli.py` → `cli/console.py` + `cli/interactive.py`；`config.py` → `config/__init__.py`；`mapping.py` → `tools/mcp/mapping.py`）。债务本身逐条复核**仍成立**，此处只换行号与版本号。

| 项 | 现状证据 |
|----|----------|
| 生产化：PyPI 发布 / CI release workflow / Docker Hub（路线级已列 §17.3） | `.github/workflows` 仅 `ci.yml`、`codeql.yml`；版本 `0.8.4`（2026-10-12 minor bump，2026-10-24 patch bump，2026-10-26 patch bump，2026-10-29 patch bump） |
| ~~`engine/workflow.py` legacy 相位机归档~~ | **已完成**（2026-09-17 `d835bd8` 删除，仅存 state/checkpoint-store） |
| benchmark 数据入库（历史趋势） | 仅本地 autosave `./benchmark-data/`（gitignore）；**阈值入口已建**（Phase 5：`--benchmark-compare-fail=min:50%`，见 `docs/troubleshooting.md`） |
| `model_pricing` 抽独立数据模型 + 校验 | 仍是 JSON 字符串 + `model_pricing_map`（`config/__init__.py:519`） |
| `guard_content` 加 `source` 参数（web 语境文案不精确） | 签名仍是 `guard_content(text)`（`tools/mcp/mapping.py:217`） |
| Hook 事件集不全 | `engine/hooks.py:44-47` 仅 `PreToolUse`/`PostToolUse`/`SessionStart`/`SessionEnd` |
| firejail / WinJob 不可用仅 `logger.warning`，无 CLI banner | `tools/sandbox/winjob.py`（run 内降级 warning）/ `firejail.py`（构造期 warning） |
| readline 在 Windows 静默失效 | `cli/interactive.py:163` 仍为 try-import（无降级方案） |
| sandbox 开箱即用 profile 预设 / cron 常见模板 | 仅有 `SANDBOX_PROFILES` 声明通道，无预设库 |
| Prompts / slash 结构化注册表 | `slash.py` 已是注册表；CLI 入口仍 `startswith("/")`（`cli/interactive.py:276,446`） |
| sandbox profile 参数合法性校验 | 无校验入口（`SANDBOX_PROFILES` 直接透传 firejail 参数） |
| `skill_update` 遇富正文技能拒绝改写 | `SkillStore.update()` 对含自定章节的技能抛 `SkillRewriteError`（元数据可改，`pattern`/`steps` 须手工编辑，改前先备份） |
---

## 附：文档地图速查

| 路径 | 用途 |
|------|------|
| `docs/frame.md` | **架构权威**（活文档，随代码更新） |
| `docs/design.md` | 产品愿景与理念 |
| `docs/iteration.md` | 迭代历程与流程 |
| `_bmad-output/epics/epic-25-28-GUI界面周期/gui-plan.md` | GUI 实现计划 |
| `docs/README.md` | 文档索引 + 当前敏捷工作流维护说明（「Goal 工作流」章节，2026-09-20 自 workflow_intro.md 并入） |
| `_bmad-output/README.md` | 产物地图（按周期） |
| `_bmad-output/consolidated-overview.md` | **本文——当前状态与导航**（周期详解与台账归档已迁 retrospective-all-cycles.md） |
| `_bmad-output/retrospective-all-cycles.md` | **历史记录唯一载体**（2026-11-15 四并二：周期回顾/详解 + deferred 闭合台账 §三 + review 闭合索引 §五） |
| `_bmad-output/sprint-status.yaml` | **sprint 状态单一权威**（全 15 周期） |
| `_bmad-output/epics/epic-01-10-主线规划周期/` | 主线周期原始产物（Epic 1-10） |
| `_bmad-output/epics/epic-11-18-MCP集成周期/` | MCP Client 集成周期（三阶段统一，2026-08-18 合并；含 Epic 11-18） |
| `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/` | Sandbox 硬化（Epic S1-S4） |
| `_bmad-output/epics/epic-19-20-健壮性硬化周期/` | 健壮性硬化（Epic 19-20） |
| `_bmad-output/epics/epic-21-24-质量工程周期/` | 质量工程深化（Epic 21-24） |
| `_bmad-output/epics/epic-25-28-GUI界面周期/` | GUI 周期（Epic 25-28） |
| `_bmad-output/epics/epic-29-35-交互扩展周期/` | 交互与可扩展层周期（Epic 29-35，2026-08-19） |
| `_bmad-output/epics/epic-36-39-文件安全防护周期/` | 文件安全与凭证防护（Epic 36-39，2026-08-24） |
| `_bmad-output/epics/epic-40-沙箱会话化周期/` | 沙箱会话化执行（Epic 40，2026-08-26） |
| `_bmad-output/epics/epic-41-目标驱动开发周期/` | 目标驱动开发 / `/goal`（Epic 41，2026-08-29） |
| `_bmad-output/epics/epic-42-BMad技能包运行时周期/` | BMad 技能包运行时（Epic 42，2026-09-01） |
| `_bmad-output/epics/epic-43-46-目标级工作流周期/` | 目标级工作流（Epic 43-46，2026-09-01） |
| `_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/` | 声明式 BMad 敏捷工作流（Epic 47，2026-09-01 → 09-15） |
| `_bmad-output/epics/epic-48-TCP网络接口周期/` | TCP 网络接口（Epic 48，2026-09-22） |
| `_bmad-output/epics/epic-49-HTTP网页访问周期/` | HTTP 网页入口（Epic 49，2026-09-23） |
| `_bmad-output/epics/epic-50-网页控制台周期/` | 网页控制台（Epic 50，2026-09-23 建立 → 09-24 实现 → 09-27 收口） |
| `_bmad-output/epics/epic-51-goal-workflow优化周期/` | `/goal` 与 workflow 可信交付优化（Epic 51，2026-09-29 建立 → 2026-10-23 收口） |
| `_bmad-output/epics/epic-52-安全并行story执行周期/` | goal 工作流安全并行 Story 执行器（Epic 52，2026-10-09 建立并交付） |
| `_bmad-output/epics/epic-53-容器沙箱档周期/` | 容器沙箱档（Epic 53，2026-10-20 立项，3 story 在 review；期二挂 deferred-work） |
| `_bmad-output/epics/<周期>/[epic-NN-主题/]stories/` | 按 epic 归档的 story 文件（2026-09-26 全深度实测：**102 个**，**28 个** `stories/` 目录） |
| `_bmad-output/epics/<周期>/<epic-NN-主题>/` | 补丁 spec 与 story 同目录（原 `patches/<领域>/` 2026-09-15 解散） |
| `_bmad-output/implementation-artifacts/arch-optimization-cycle/` | **架构优化周期档案**（总方案 + phase0..5 spec，各含执行记录；2026-09-22 归档，原 `docs/test.md` 已删并） |
| `_bmad-output/implementation-artifacts/open-items.md` | 工作流的跨周期 deferred **活动条目**（未完成清单，2026-11-15 起唯一活动台账；条数与 ID 以该文件头部为准） |
| `_bmad-output/implementation-artifacts/spec-business-data-integration.md`（**2026-09-15 已删除**） | 业务数据整合**母规划 spec**——未启动、未衍生实现 spec 或 epic，正文仅存 git 历史（见 `_bmad-output/README.md`「已失效删除」） |
| `_bmad-output/epics/<周期>/deferred-work.md` | 已闭合遗留项按归属 epic 归档（2026-09-24 实测存在 **9 份**：01-10 / 11-18 / S1-S4 / 36-39 / 40 / 41 / 47 / **48** / **50**） |
| `_bmad-output/specs/` | quick-dev 本地工作件（gitignored；Epic 41 goal 契约已归档至 `_bmad-output/epics/epic-41-目标驱动开发周期/spec-goal-command/`） |
