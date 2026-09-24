---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
status: final
inputDocuments:
  - _bmad-output/epics/epic-50-网页控制台周期/brief.md
  - _bmad-output/epics/epic-50-网页控制台周期/ARCHITECTURE-SPINE.md
  - docs/frame.md
  - docs/design.md
  - src/heagent/network/http_server.py
  - src/heagent/cli_http.py
  - src/heagent/config.py
  - src/heagent/tools/path_safety.py
---

# HeAgent - Epic Breakdown（Epic 50：网页控制台）

## Overview

本文件按 BMad 方法把 brief.md 的「网页控制台」方案拆解为可执行的 Epic 与 Story。产品输入为本目录
`brief.md`；技术输入为本目录 `ARCHITECTURE-SPINE.md`（本周期冻结的不变量）。Epic 49 交付的是
「一个进程 = 一个目录 = 一次性聊天页」的 HTTP MVP；本 Epic 交付的是把网页入口升级为**本机控制台**：
多项目、会话持久化、配置可视化与受闸门约束的配置编辑。

**前置校验结论（step-01 实测，非推断）**：brief 第 3 节的三条规划依据全部证实，并额外查出一处
必须顺手闭合的缺口。

| brief 断言 | 证据（本次核实） |
|---|---|
| HTTP 入口一个进程固定一个工作区 | `cli_http.py:197` 与 `cli.py:263` 各硬编码一次 `os.getcwd()`；`HttpServerConfig`（`http_server.py:138-155`）、`http-server` 的 15 个 CLI 选项（`cli_http.py:357-420`）、`HttpAgentHandler.__init__`（`cli_http.py:180-190`）**均无** workspace 字段 |
| `.heagent/*` 全部是 cwd / home 相对 | 8 个 store 的默认值是**相对字面量**（`context/session.py:83`、`memory/skill_store.py:47`、`memory/facts.py:41`、`memory/profile.py:21`、`cron/jobs.py:36`、`engine/store.py:91`、`engine/ledger.py:122`、`engine/checkpoint.py:85`）；`EngineContainer.default()`（`engine/container.py:173-182`）**不暴露** base_dir ⇒ `run_store`/`ledger` 是唯一无注入面的状态根 |
| 网页运行不写会话文件 | `http_server.py` 模块内零文件写；`new_loop()` 传 `session=None`（`cli_http.py:207-214`）；`session_id` 是进程内 `uuid4`（`http_server.py:341`） |
| （新查出）内部状态读拒集合不全 | `build_internal_state_dirs()`（`tools/path_safety.py:248-261`）硬编码 `Path.cwd()`+`Path.home()` 与 5 个子目录 `("sessions","ledger","runs","memory","skills")`；`user/USER.md`、`cron/jobs.json`、`checkpoints/`、`tmp/edit-snapshots`、`sandboxes/<run_id>`、`_he-output/goals/**` **均不在** deny 集合内，工作区围栏（只挡工作区之外）对其零保护 |

配置面关键事实：`Settings` 共 **110 字段、零 alias**（`config.py:45-57`）⇒ env 键名 = 字段名大写，
纯机械映射；**不存在**来源追踪（`types.py:15-20` 的 `"settings"|"override"` 只服务快照，且仅测试消费，
`config.py:566-576`）；逐层来源求解**已实测可行**（显式构造 1×`EnvSettingsSource` + 2×`DotEnvSettingsSource`
自下而上 diff，输出 39 键全部落 `project_env`）；项目 `.env` 实测 **77 行 / 全 CRLF / 无 BOM / 40 KV /
1 个重复键 / 10 处行内注释**，`.env.example` 为 **LF / 345 行 / 覆盖全部 110 字段**（`tests/test_config.py:573`
有断言）；唯一 `.env` 写入者是 `heagent init`（`cli_init.py:116-143`，写**全局**、`write_text` 非原子、
不保留既有内容、无锁无校验）；可复用原语已存在：`persist.atomic_write_text`（`persist.py:313`）、
`persist.atomic_update_text`（`persist.py:368`）、`tools/edits.read_text_file`/`write_text_file`（`tools/edits.py:63-99`）。

## Requirements Inventory

### Functional Requirements

FR-1: 工作区一等化 —— 以 `workspace_root` 作为项目身份，按项目构造 engine 与记忆/技能/会话/运行状态存储；
同一服务进程可服务多个项目，运行按项目绑定围栏、沙箱会话目录与状态根。

FR-2: 项目注册表 —— 提供项目列表（含最近打开）、登记已有目录、切换、重命名显示名、移除登记（**不删目录**）；
路径规范化，明确重复登记、目录失效与非目录路径的处理。

FR-3: 会话持久化与侧栏数据面 —— 项目内多会话（新建 / 切换 / 重命名 / 删除 / 继续），复用既有 `SessionStore`
落到**该项目**的 `.heagent/sessions/`；运行绑定会话，消息顺序与工具调用/结果配对完整。

FR-4: 配置读取 —— 分类列出可配置项的**有效值 + 来源 + 是否可写**；被系统环境变量覆盖的项标记为只读。

FR-5: 配置写入 —— 经 pydantic 校验后**保真原子写**项目 `.env`，写前备份、检测外部修改冲突、写后回读校验，
记录审计日志（**不含值**）；生效语义 = 下一次 run。

FR-6: 网页 UI —— ChatGPT 式两栏布局（项目/会话侧栏 + 对话区 + 独立设置面板），危险项二次确认、来源徽标。

FR-7: 安全与验收 —— 写通道的防线、凭证零回传测试、非安全边界声明、验收清单（含「跨项目不串味」）。

### Non-Functional Requirements

NFR-1（依赖方向）: 新增能力若落在顶层模块，不得反向依赖 `engine/` / `agent/` / 入口层；`network/` 不得新增
对 `config`（除既有延迟导入）、`agent`、`engine`、`tools` 的依赖；项目/会话/配置能力经**入口层注入的协议**进入网络层。

NFR-2（工作区单一来源）: 状态根路径只能有一个来源（`WorkspacePaths`）；除入口层兜底外，禁止新增
`os.getcwd()` 直取与重复的路径字符串常量。

NFR-3（快照语义）: 配置写入只对**下一次 run** 生效；面板展示口径与运行解析口径由**同一来源求解器**产出，
不得出现「面板说旧值、状态行显示新值」。

NFR-4（凭证零回传）: 任何响应、错误信封、日志、审计记录都不含明文密钥；掩码不得因长度差暴露短密钥全文。

NFR-5（写通道 fail-closed）: 开关关闭、未知键、非白名单键、非法值、外部修改冲突、非回环来源一律显式失败
**且不改动文件**。

NFR-6（保真写）: 写入保持原文件 EOL、BOM、注释、空行与未被修改行逐字节不变。

NFR-7（原子性与可恢复）: 写前备份、写后回读校验；保存失败必须显式报告并保证原配置可恢复。

NFR-8（并发与无状态）: 同一会话的并发写入显式拒绝而非静默覆盖；项目切换**不修改**进程 cwd 与进程环境变量。

NFR-9（安全立场）: 写通道额外要求本机回环来源；UI 与文档必须显示「无认证、无 TLS、非安全边界」。

NFR-10（无回归）: 现有 CLI / GUI / TCP / HTTP 端点行为不变；开关关闭（默认）时新增面**只读**。

NFR-11（有界）: 项目数、会话列表、审计与备份条目、配置响应体均有上限。

NFR-12（测试与文档同步）: `.env.example` 覆盖全部 `Settings` 字段的既有断言保持通过；`docs/frame.md` 新增
4.18「网页控制台」小节与 `HTTP_CONSOLE_*` 配置行。

### Additional Requirements

- 工作区提升必须**同时**修正 `build_internal_state_dirs()`：deny 集合从同一 `WorkspacePaths` 派生，
  覆盖全部运行态子目录（含 `user/`、`cron/`、`checkpoints/`、`tmp/edit-snapshots`、`sandboxes/`、`console/`）；
  这是行为收紧，必须带负向验证。
- `EngineContainer.default()` 的 `workspace_root` 必须接到 `RunStore`/`ExecutionLedger` 的 base_dir
  （它们已是 `init=True` 字段，改造面小；**校正 C1**：形参本身早已存在）。
- 写白名单与排除表必须是**完整划分**（白名单 ∪ 排除 = 全部 `Settings` 字段，无未分类残留），
  且优先级明确（显式白名单 > 模式排除）。原表遗漏 12 键并含 1 处模式冲突（**校正 C2/C3**，详见
  `ARCHITECTURE-SPINE.md` §8 与 §14）。
  **裁定结果（2026-09-24，D2/D3）**：划分 = **46 白名单 + 64 排除、残留 0**；其中 `SANDBOX_DIR_RETENTION_DAYS`
  按 D2 可写，原 12 个未分类键按 D3 拆为「8 键开放 / 4 个 dream 参数键只读」，5 个弱校验键须补字段级守卫。
  完整决策见 `ARCHITECTURE-SPINE.md` §15。
- 项目切换用**每请求参数 + 服务端项目路由**，不依赖服务端「当前项目」可变状态；`HttpRunService` 实例按项目池化。
- **并发语义（D9 裁定，2026-09-24，原评审 F4）**：`HttpRunService` 按项目池化 ⇒ 在途运行上限 =
  **项目数 × `HTTP_MAX_INFLIGHT_RUNS`**（默认最多 **32**）；多项目**并行**是有意能力，每项目内部的
  单运行 / 会话在途保护不变；**无全局并发上限**（已知缺口，见脊柱 §6）。原 brief §5
  「多项目切换不等于并行运行」已作废（brief 同处已标注）。
- 配置写入通道只改**项目 `.env`**；全局 `~/.heagent/.env` 只读（brief §7 D1）。
- 写白名单从 `Settings.model_fields` 取**显式允许子集**（fail-closed），排除凭证、监听面、沙箱/执行后端、
  进程拉起开关、路径类与服务端自身开关。
- 候选配置必须能被 `Settings(_env_file=<候选临时文件>)` 成功构造，否则拒绝写入（把「写坏 = 进程起不来」
  的风险前移到校验期）。
- 新增配置键 `HTTP_CONSOLE_WRITE_ENABLED`（默认 `False`）与 `HTTP_CONSOLE_PROJECTS_FILE`
  （默认 `<服务启动工作区>/.heagent/console/projects.json`，**不写用户 home**——**校正 C8**，现以
  `ARCHITECTURE-SPINE.md` §4 为准；需要机器级共享时由用户显式配成 `~/.heagent/projects.json`）；
  两者都进入 `ResolvedRuntimeConfig` 快照且**不可由网页自行开启**。
- 会话并发冲突检测为**增量**：`SessionStore.save` 增加可选「期望版本」参数，Web 侧传入并在不匹配时 409；
  CLI 侧不传（行为不变）。

### UX Design Requirements

UX-DR1: 两栏布局 —— 左栏项目与项目内会话列表（新建/切换/重命名/删除/最近排序），右栏对话区，设置入口独立面板。
UX-DR2: 来源徽标 —— 每个配置项显示来源（系统环境变量 / 项目 `.env` / 全局 `.env` / 字段默认）与可写性。
UX-DR3: 危险项二次确认 —— 删除会话、移除项目登记、写入高危类键必须显式确认，且文案说明影响范围。
UX-DR4: 生效时机表达 —— 保存成功后 UI 明确显示「下一次运行生效」，不得声称立即生效。
UX-DR5: 只读原因可见 —— 被环境变量覆盖、被白名单排除、开关关闭的项必须显示**原因**而非静默禁用。
UX-DR6: 安全声明常驻 —— 页面固定显示「无认证 / 无 TLS / 任何能连上该端口的人都能改配置」。
UX-DR7: 无回归的既有体验 —— 流式回答、工具活动、停止、断线重连、错误反馈维持 Epic 49 行为。

### FR Coverage Map

FR-1: Story 50.1 —— 工作区一等化与状态根单一来源。
FR-2: Story 50.2 —— 项目注册表与项目 API。
FR-3: Story 50.3 —— 会话持久化、会话 API 与运行绑定。
FR-4: Story 50.4 —— 配置来源求解与只读配置 API。
FR-5: Story 50.5 —— 配置写入通道（白名单 / 保真写 / 备份 / 冲突 / 审计）。
FR-6: Story 50.6 —— 网页控制台 UI。
FR-7: Story 50.7 —— 安全收口、端到端验收与文档同步。

## Epic List

### Epic 50: 本机网页控制台

用户在本机浏览器里拥有一个控制台：可以登记并切换多个项目（项目 = 一个目录，其 `.heagent/` 是状态根），
在每个项目里新建、切换、重命名、删除并延续持久化会话；可以查看每项配置的有效值、来源与可写性，
并在显式开启的闸门与安全防线之下保存项目级非凭证配置；保存后明确知道「下一次运行生效」。
该 Epic 不引入多用户、账号、TLS、反向代理或公网暴露；网页入口依旧**不是安全边界**。

**FRs covered:** FR-1–FR-7
**NFRs:** NFR-1–NFR-12 贯穿全部 stories
**UX-DRs:** UX-DR1–UX-DR7 贯穿 UI 与 API 验收
**阶段映射（brief §8）:** Phase A → 50.1；Phase B → 50.2 + 50.3；Phase C → 50.4；Phase D → 50.5；
Phase E → 50.6 + 50.7

## Story 50.1: 工作区一等化与状态根单一来源

作为 HeAgent 维护者，我希望「工作区」成为一等参数且所有运行态路径从它派生，以便同一个服务进程能安全地
服务多个项目而不串味。

**Acceptance Criteria:**

**Given** 一个显式工作区 `W`，**When** 用 `W` 组装 engine 与各 store，**Then** 运行态根（sessions / skills /
memory / user / cron / runs / ledger / checkpoints / sandboxes / edit-snapshots / console）**全部**位于 `W/.heagent/`
之下，且没有任何路径落在进程 cwd 下。

**Given** 同一进程先后装配 `W1` 与 `W2`，**When** 分别写入技能 / 事实 / 会话 / 运行快照，**Then** 两侧文件互不出现，
且 `W1` 的 `SkillStore` 看不到 `W2` 的技能。

**Given** 已绑定的工作区 `W`，**When** 进程执行 `os.chdir(其它目录)`，**Then** 围栏基址、上下文发现目录与状态根
**仍然一致**（不出现 brief 侦察发现的「围栏冻结 vs `context_dir` 每 run 重读」分叉）。

**Given** 工作区 `W`，**When** 通过文件工具读取 `W/.heagent/{user,cron,checkpoints,tmp/edit-snapshots,sandboxes,console}`
中的任一文件，**Then** 被内部状态读拒拦下；而 `W` 内普通文件仍可读（不误伤）。

**Given** 未显式传入工作区的既有调用方（CLI / GUI / TCP），**When** 装配运行，**Then** 行为与改造前一致
（回退到进程 cwd），既有测试无回归。

**Definition of Done:**

- 新增 `WorkspacePaths`（Pydantic，单一来源）并新增顶层模块承载它；`path_safety.build_internal_state_dirs()`
  改为从同一来源派生（含新增子目录）。
- `EngineContainer.default()` **已**接受 `workspace_root=`（校正 C1）；改造点是把该根接到
  `RunStore` / `ExecutionLedger`（二者现由 `field(default_factory=…)` 无参构造 ⇒ cwd 相对）。
- `SessionStore` / `SkillStore` / `FactStore` / `ProfileStore` / `JobStore` 的装配点全部改为传派生路径。
- 架构契约测试新增断言：禁止新增裸 `os.getcwd()` 装配点、`WorkspacePaths` 为路径字符串唯一来源。
- 定向验证：`pytest tests/test_workspace_paths.py tests/test_credential_guard.py tests/test_engine_p0.py -q`；
  跨工作区隔离新增测试；负向验证（回退 `build_internal_state_dirs()` 收紧项 → 新测试精确变红）。
- `ruff check src tests` 与 `mypy src` / `mypy src --platform linux` 干净。

**Requirement Traceability:** FR-1; NFR-1, NFR-2, NFR-8, NFR-10; brief §3 硬结论 (a)、§6.7、§6.6。

## Story 50.2: 项目注册表与项目 API

作为控制台用户，我希望在网页里登记并切换已有目录，以便一个服务进程服务我本机的多个项目。

**Acceptance Criteria:**

**Given** 控制台已启动，**When** 客户端 `GET /api/projects`，**Then** 返回项目列表（id、显示名、规范化绝对路径、
最近打开时间、是否存在），按最近打开降序，且**不含**任何凭证或非项目目录内容。

**Given** 一个存在的目录路径，**When** 客户端 `POST /api/projects`，**Then** 登记成功并返回项目 id；路径经
规范化（`resolve`、去尾分隔符、`expanduser`）。

**Given** 同一路径以不同写法（大小写 / 尾分隔符 / 相对路径 / 符号链接）再次登记，**When** 执行登记，
**Then** 服务识别为**已存在**并返回既有项目而非新建（Windows 大小写不敏感）。

**Given** 一个不存在或不是目录的路径，**When** 执行登记，**Then** 返回稳定的 `invalid_project_path` 错误，
**不创建目录**、不写任何文件。

**Given** 已登记项目，**When** 客户端 `PATCH` 重命名显示名，**Then** 只改注册表里的名称，磁盘目录不变。

**Given** 已登记项目，**When** 客户端 `DELETE /api/projects/{id}`，**Then** 仅移除登记；项目目录与其
`.heagent/` 数据**逐字节保留**，且有运行在途时拒绝移除。

**Given** 已登记项目的目录被外部删除，**When** 客户端列出项目，**Then** 该项标记为「目录失效」而不是从列表消失，
对其发起运行得到显式错误。

**Given** 注册表文件损坏（非法 JSON），**When** 服务启动，**Then** 记录 WARNING 并以空注册表继续（fail-soft），
不阻断 HTTP 服务。

**Definition of Done:**

- 注册表模型与 CRUD 以 Pydantic 表达，落盘位置固定为 `HTTP_CONSOLE_PROJECTS_FILE`，写入走 `persist.atomic_update_text`（跨进程锁）。
- 注册表条目数有上限，超限拒绝登记并给出稳定错误。
- 项目 id 生成规则与显示名默认值（目录 basename）有测试。
- 覆盖：登记 / 重复登记 / 非目录 / 失效目录 / 重命名 / 移除保留数据 / 损坏注册表 / 上限。
- `pytest tests/network -q` 与新增测试通过；`ruff check` / `mypy` 干净。

**Requirement Traceability:** FR-2; NFR-5, NFR-8, NFR-11; UX-DR3, UX-DR5; brief §4 FR-2、§6.4、§7 D3。

## Story 50.3: 会话持久化、会话 API 与运行绑定

作为控制台用户，我希望刷新浏览器或重启服务后仍能列出、打开并继续我已保存的对话。

**Acceptance Criteria:**

**Given** 项目 `P`，**When** 客户端 `GET /api/projects/{id}/sessions`，**Then** 返回 `P/.heagent/sessions/` 下的会话
（id、标题、消息数、更新时间），按时间降序，与 CLI 在该目录看到的是**同一批文件**。

**Given** 客户端新建会话并提交提示词，**When** 运行结束，**Then** 会话文件落在 `P/.heagent/sessions/{session_id}.json`，
内容格式与 CLI 一致（`session_id`/`version`/`timestamp`/`messages`），工具调用与结果配对完整。

**Given** 浏览器刷新或服务重启，**When** 再次打开该会话，**Then** 消息按序完整恢复，且运行绑定该会话
（后续提交继续写入同一文件）。

**Given** 同一会话文件已被 CLI 或另一进程写入（磁盘 version 与客户端持有的版本不一致），**When** 网页提交写入，
**Then** 返回稳定的 `session_conflict` 冲突错误，**不覆盖**对方内容，并提示重新加载。

**Given** 一个会话正在被运行写入，**When** 客户端请求删除该会话，**Then** 拒绝删除并给出稳定冲突错误。

**Given** 客户端删除会话，**When** 请求缺少确认标记，**Then** 拒绝执行（危险操作需显式确认）。

**Given** 会话 id 含路径遍历字符（`../`、绝对路径、超长），**When** 客户端传入，**Then** 被拒绝且不触碰文件系统。

**Definition of Done:**

- `SessionStore` 增加可选「期望版本」冲突检测（CLI 侧不传 ⇒ 行为不变），并保持既有原子写与跨进程锁。
- 会话标题派生规则明确（首条用户消息截断），重命名的落点明确（写回会话文件的可选字段或独立索引，二选一并写测试）。
- 删除会话与移除项目登记都受「在途运行」约束。
- 覆盖：列表 / 新建 / 继续 / 恢复 / 冲突 / 在途删除拒绝 / 确认缺失 / 非法 id。
- `pytest tests/test_session.py tests/network -q` 与新增测试通过；`ruff check` / `mypy` 干净。

**Requirement Traceability:** FR-3; NFR-6, NFR-7, NFR-8, NFR-10; UX-DR3, UX-DR4; brief §4 FR-3、§6.8、§7 D5。

## Story 50.4: 配置来源求解与只读配置 API

作为控制台用户，我希望看到每项配置的**有效值 + 来源 + 可写性**，以便理解实际生效的配置从哪来。

**Acceptance Criteria:**

**Given** 项目 `P` 存在系统环境变量覆盖、项目 `.env` 覆盖与全局 `~/.heagent/.env` 覆盖各若干项，
**When** 客户端 `GET /api/projects/{id}/config`，**Then** 每项返回 `key`、`value`、`source`
（`system_env` / `project_env` / `global_env` / `default`）、`writable`、`read_only_reason`。

**Given** 某键被系统环境变量提供，**When** 查询该项，**Then** `source=system_env` 且 `writable=false`、
原因标明「被系统环境变量覆盖」。

**Given** 某键只在项目 `.env` 出现，**When** 移除该行后再次查询，**Then** 该项回落到 `global_env` 或 `default`
并如实标注新来源。

**Given** 任一凭证键（`DEEPSEEK_API_KEY`、`OPENAI_API_KEYS`、`OLLAMA_API_KEY` 等全部 `*_API_KEY` / `*_API_KEYS`），
**When** 查询配置，**Then** 只返回 `configured: true/false` 与**掩码**（固定位数，不反映真实长度），**永不**返回明文；
短密钥（长度 ≤ 掩码位数）也不得因展示而暴露全文。

**Given** 项目 `.env` 中存在未知键或拼错的键，**When** 查询配置，**Then** 该键在响应中被标记为「未知键（不生效）」，
**不并入**有效值列表。

**Given** 项目 `.env` 不存在或不可读，**When** 查询配置，**Then** 返回全部字段的 `default` / `global_env` 来源，
并明确标注项目配置文件路径与「不存在」状态，不报 500。

**Given** 配置项的值来源于 `Settings` 快照与来源求解器，**When** 客户端同时查询面板与观察运行行为，
**Then** 两者对同一键的口径一致（同一求解器，非第二套解析）。

**Definition of Done:**

- 新增来源求解器（顶层模块），显式构造 4 层来源并逐层覆盖，处理已知 6 个坑：原始串 vs 强转值、
  未知键可见性、文件缺失静默跳过、相对路径按进程 CWD 解析、重复键后者胜、行内注释剥离。
- 分类分组与可写性判定表由**声明式常量**驱动（与 50.5 的写白名单同一处定义）。
- 结构定义使用 Pydantic；响应体有上限（键数有界 = `Settings.model_fields`）。
- 覆盖：四层来源各一例、系统环境变量只读、未知键、缺失文件、凭证掩码（含短密钥与多密钥负向）。
- `pytest tests/test_config.py -q` 与新增测试通过；`ruff check` / `mypy` 干净。

**Requirement Traceability:** FR-4; NFR-3, NFR-4, NFR-5; UX-DR2, UX-DR5; brief §4 FR-4、§6.2、§6.9。

## Story 50.5: 配置写入通道（白名单 / 保真写 / 备份 / 冲突 / 审计）

作为控制台用户，我希望在闸门控制下保存项目级非凭证配置，失败时可恢复，且明确知道它何时生效。

**Acceptance Criteria:**

**Given** `HTTP_CONSOLE_WRITE_ENABLED` 未开启（默认），**When** 客户端提交任何配置写入，**Then** 返回稳定的
`write_disabled` 错误，文件不变，且**网页无法通过任何请求开启该开关**。

**Given** 开关已由服务启动配置开启，**When** 客户端提交白名单内的键与新值，**Then** 值经 pydantic 校验后
**保真原子写**入项目 `.env`：只有目标行被替换，其余行、行尾（CRLF/LF）、BOM 状态、注释与空行逐字节不变。

**Given** 待写入的键在项目 `.env` 中不存在，**When** 保存成功，**Then** 该键以既有文件的 EOL 风格追加，
不改动任何既有行。

**Given** 请求包含凭证键、监听面键（`HTTP_*`/`TCP_*`）、沙箱与执行后端键、进程拉起开关、路径类键、
`HTTP_CONSOLE_*` 自身开关或任何未知键，**When** 提交，**Then** 返回 `field_not_writable` 并指明原因，文件不变。

**Given** 值非法（类型不符、越界、非 JSON 的 list 字段、非法 JSON 的 `ROUTING_POOLS`），**When** 提交，
**Then** 返回 `invalid_value` 与字段级原因，文件不变；校验通过 `Settings(_env_file=<候选临时文件>)` 复验。

**Given** 客户端持有的文件指纹与服务端当前文件不一致（外部编辑器改了 `.env`），**When** 提交，
**Then** 返回 `config_conflict`，**不覆盖**对方的修改，并提示重新加载。

**Given** 一次成功写入，**When** 检查磁盘，**Then** 存在写前备份（落在项目状态根内、按敏感配置处理、
不提供网页下载、有条数与保留期上限）与一条审计记录（含时间、来源、键名、旧/新值哈希与长度，
**不含**值本身与任何凭证）。

**Given** 写入过程中磁盘失败或回读校验不匹配，**When** 错误发生，**Then** 自动恢复原文件内容并向客户端显式报告失败。

**Given** 一次成功保存，**When** 当前正在运行的任务继续执行，**Then** 它仍使用旧快照；
下一次运行解析到新值，UI 明确显示「下一次运行生效」。

**Definition of Done:**

- 新增 `.env` 行级保真读写（顶层模块）：键定位、值替换/追加、EOL 与 BOM 保真、原子替换（复用 `persist` 原语），
  不解析整份文件重写。
- 写白名单以显式允许子集定义（fail-closed），并有测试断言「白名单 ⊆ `Settings.model_fields`」与
  「凭证/监听/沙箱/未知键均不在白名单」。
- 备份与审计的落点、上限、保留期写入 `WorkspacePaths`；两目录进入内部状态读拒集合。
- 写通道额外要求本机回环来源；非回环来源的写入被拒。
- 覆盖：开关关闭 / 白名单成功 / 新增键 / 9 类拒绝 / 非法值 / 冲突 / 备份与审计内容 / 回读失败恢复 /
  「当前 run 用旧值、下一次用新值」端到端。
- 负向验证：去掉白名单过滤、去掉指纹校验、去掉备份、把备份目录移出 deny 集合 —— 对应测试逐条必须变红。
- `pytest tests/test_config.py tests/network -q` 与新增测试通过；`ruff check` / `mypy` 干净。

**Requirement Traceability:** FR-5; NFR-4–NFR-9, NFR-11; UX-DR3, UX-DR4; brief §4 FR-5、§6.1–6.3、§6.6、§7 D1/D4。

## Story 50.6: 网页控制台 UI

作为控制台用户，我希望界面像 ChatGPT 一样直观：左栏项目与会话，右栏对话，设置独立成面板。

**Acceptance Criteria:**

**Given** 用户打开控制台首页，**When** 页面加载，**Then** 显示两栏布局（项目/会话侧栏 + 对话区）、设置入口，
以及常驻的「无认证 / 无 TLS / 非安全边界」声明。

**Given** 项目列表已加载，**When** 用户切换项目，**Then** 侧栏刷新为该项目会话，对话区清空到该项目的当前会话，
且**不修改**任何进程级状态；切换期间既有运行保持原项目绑定。

**Given** 用户提交提示词，**When** SSE 推送文本与工具事件，**Then** 对话区按序更新，工具显示名称/目标/结果，
终态显示成功/失败/取消，行为与 Epic 49 一致（无回归）。

**Given** 用户打开项目设置，**When** 面板加载，**Then** 每项显示有效值、来源徽标、可写性；只读项显示**原因**；
凭证项只显示「已配置/未配置 + 掩码」。

**Given** 写入闸门关闭，**When** 用户查看设置面板，**Then** 所有可写项显示为不可编辑并说明「服务启动时未开启配置写入」，
**不提供**任何开启入口。

**Given** 用户保存一项配置，**When** 保存成功，**Then** 面板显示保存结果与「下一次运行生效」，并刷新该项的来源徽标。

**Given** 用户删除会话或移除项目登记，**When** 点击操作，**Then** 出现二次确认，文案说明影响范围
（删除会话 = 删文件；移除登记 = 保留目录数据）。

**Given** 请求失败（非法值 / 冲突 / 只读 / 目录失效 / 冲突运行），**When** 错误返回，
**Then** UI 显示可理解的稳定文案，不渲染不可信 HTML，不加载第三方脚本。

**Definition of Done:**

- 静态资源仍经包内白名单加载（`read_web_asset`），无第三方脚本，文本按纯文本渲染。
- 新增 UI 状态（项目切换中、会话冲突、配置写入结果、只读原因）都有可见反馈。
- 源码运行与 wheel 安装两条路径的静态资源加载均有验证。
- 浏览器手工验收清单（页面 → 步骤 → 期望）写入 story 产物并记录执行结果。
- `pytest tests/network -q` 与 UI 相关测试通过；`ruff check` / `mypy` 干净。

**Requirement Traceability:** FR-6; NFR-9, NFR-10; UX-DR1–UX-DR7; brief §4 FR-6、§2 场景表。

## Story 50.7: 安全收口、端到端验收与文档同步

作为 HeAgent 维护者，我希望本 Epic 的安全立场、生效语义与验收证据完整可查，以便它可被信任地使用与维护。

**Acceptance Criteria:**

**Given** 服务绑定非回环地址，**When** 控制台启动，**Then** 沿用 `network.exposure` 的无认证/无 TLS/非安全边界告警，
且 UI 与文档同样声明。

**Given** 写通道被非回环来源访问，**When** 提交配置写入或项目登记，**Then** 被拒绝且不产生副作用。

**Given** 客户端遍历所有 API（含错误路径、SSE、配置查询与写入响应），**When** 执行凭证零回传检查，
**Then** 响应、错误信封、日志与审计中均不出现任何密钥明文（覆盖短密钥、多密钥、备份访问）。

**Given** 两个项目 A/B 交替操作，**When** 提交、切换、运行、删除，**Then** 会话、项目级记忆与运行状态归属正确，
用 A 的请求无法读取或修改 B 的会话与配置（跨项目不串味验收）。

**Given** Epic 49 的既有能力（流式、工具活动、停止、重连、来源校验、会话快照），**When** 运行回归，
**Then** 无行为回归；`HTTP_CONSOLE_WRITE_ENABLED` 默认关闭时新增面只读。

**Given** 文档与配置示例，**When** 检查 `docs/frame.md`、`.env.example`、README 索引，
**Then** 4.18 小节与 `HTTP_CONSOLE_*` 键已同步，`.env.example` 覆盖全部 `Settings` 字段的既有断言通过。

**Definition of Done:**

- 端到端验收脚本/清单覆盖 brief §9 的 9 条验收标准，逐条给出实测证据（命令 + 结果）。
- 依赖方向与安全契约断言加入 `tests/test_architecture_contracts.py`。
- 全量质量门：`pytest`、`ruff check src tests`、`ruff format --check src tests`、`mypy src`、
  `mypy src --platform linux`。
- 已知缺口（不是安全边界、全局文件只读、无重启热生效等）写入 frame.md 与 story 产物，不留「以为安全」的错觉。

**Requirement Traceability:** FR-7; NFR-4, NFR-9, NFR-10, NFR-12; brief §9、§6.1、§10。

## Story 产物（本周期，2026-09-23 细分）

7 条 story 的开发者就绪产物已建立，文件名与 `sprint-status.yaml` 的 key 一一对应：

| story | 文件 | 阶段 | 依赖 |
|---|---|---|---|
| 50-1 | `stories/50-1-workspace-first-class.md` | A 工作区基础 | — |
| 50-2 | `stories/50-2-project-registry-api.md` | B 项目与会话闭环 | 50-1 |
| 50-3 | `stories/50-3-session-persistence-api.md` | B 项目与会话闭环 | 50-1, 50-2 |
| 50-4 | `stories/50-4-config-sources-readonly-api.md` | C 配置可见 | 50-1..50-3 |
| 50-5 | `stories/50-5-config-write-channel.md` | D 配置可编辑 | 50-1..50-4 |
| 50-6 | `stories/50-6-console-ui.md` | E 整体验收 | 50-2..50-5 |
| 50-7 | `stories/50-7-security-acceptance-docs.md` | E 整体验收 | 50-1..50-6 |

每份产物含：用户故事 / 范围 / 边界与约束（Always-Never）/ 任务清单 / 验收标准 / Definition of Done
（含可复现命令与负向验证）/ 代码地图 / 风险与未决 / 需求追溯，以及**实测**的侦察证据表
（行号、字节级度量、探针结论）。

> **本文件原拆分中的 8 处不准确/冲突已在细分阶段校正**（含 1 处不存在的测试文件、1 处配置默认值互相矛盾、
> 12 个未分类配置键、1 处白名单与排除模式冲突等），逐条证据与处置见
> `ARCHITECTURE-SPINE.md` §14「侦察校正」。实现请以 story 产物 + 校正后的脊柱为准。

<!-- Subsequent BMad steps append implementation evidence per story. -->
