# HeAgent

> **实验性 Agent 框架。** HeAgent 用可读的 Python 代码拆解自主 Agent 的关键机制，适合学习、原型验证和按需扩展；它不是产品，也不是安全边界。

HeAgent 是一个单进程、异步的 Python Agent 运行时，同时提供 CLI 和可嵌入的库接口。它把多 Provider 调用、工具执行、策略裁决、会话与记忆、MCP、子 Agent 委派和声明式 `/goal` 工作流组合在一起。

如果目标是稳定完成日常编码任务，请优先使用 [Codex](https://github.com/openai/codex) 等产品级代理；如果目标是理解、替换或组合 Agent 的内部机制，HeAgent 提供了一套可直接阅读和改造的参考实现。

## 适用范围

| HeAgent 是 | HeAgent 不是 |
| --- | --- |
| 单进程异步 Python 库、CLI 和可选 Textual 终端 UI | HTTP 服务、多租户产品或稳定 SDK |
| 可阅读、可替换的 Agent 参考实现 | 无人值守地操作真实环境的安全方案 |
| 多 Provider、工具治理、记忆和工作流的实验场 | 生产就绪承诺、SLA 或大规模模型评测结果 |

## 快速开始

要求 Python 3.11+。

### 1. 安装

```bash
pip install -e ".[dev]"
```

只使用 CLI 或库时可安装发布包：

```bash
pip install heagent
```

### 2. 配置 Provider

复制配置模板后，至少填写一个 Provider 凭据。配置优先级是：系统环境变量 > 项目 `.env` > 用户 `~/.heagent/.env` > 默认值。

```bash
cp .env.example .env
```

```powershell
Copy-Item .env.example .env
```

```dotenv
DEEPSEEK_API_KEY=sk-...
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=...
```

本地 Ollama 不需要 API Key，但必须显式启用并指定模型：

```dotenv
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen3:8b
# OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
```

本地模型的上下文窗口通常远小于默认 `MAX_CONTEXT_TOKENS=512000`；请按实际 `num_ctx` 下调该值。

### 3. 运行

```bash
# 单次执行
heagent "用 Python 写一个快速排序"

# 交互模式
heagent

# 显式子命令
heagent run --model deepseek-flash --system "你是 Python 专家" "写一个二分查找"

# 初始化用户级配置；--project 额外创建 .heagent/CONTEXT.md 模板
heagent init --project
```

## 核心能力

- **Provider**：DeepSeek、Kimi、GLM、OpenAI Chat Completions、OpenAI Responses、Anthropic 和显式启用的 Ollama；支持重试、密钥轮换、故障转移、手动切换与声明式路由池。
- **工具与治理**：`@tool` 注册、内置 shell／文件／搜索／记忆／技能／Cron／子 Agent／Web／Git 工具、MCP 桥接，以及 `PolicyEngine → ToolExecutor → SafetyGuard → handler` 执行链。
- **上下文与记忆**：会话持久化、分层上下文文件、token 计量、压缩或窗口重置；技能、事实记忆、用户画像和 `SOUL.md` 人格均可文件化管理。
- **工作流与审计**：Markdown 声明的 `/goal`、checkpoint、独立 SubAgent 步骤、事件总线、JSONL 输出、rollout 落盘和回放。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `heagent [PROMPT]` | 直接执行 prompt；无 prompt 时进入交互模式 |
| `heagent run [PROMPT]` | 显式运行入口 |
| `heagent init [--project]` | 初始化用户配置；可选创建项目上下文模板 |
| `heagent gui` | 启动终端 UI，需要 `pip install -e ".[gui]"` |
| `heagent replay FILE` | 回放 JSONL rollout 或事件文件 |

常用 `run` 选项：

| 选项 | 说明 |
| --- | --- |
| `--model NAME` | 覆盖当前 Provider 的模型；已启用路由池时请用 `/route` 选档 |
| `--system TEXT` | 设置本次运行的 system prompt |
| `--max-iterations N` | 主 Agent 最大迭代数 |
| `--continue` / `--resume ID` | 继续最近或指定会话 |
| `--plan` | 只读规划模式，禁止 shell 和写入类工具 |
| `--sandbox auto\|passthrough\|firejail\|winjob` | 选择 shell 执行后端 |
| `--json` | 单次执行时将 JSONL 事件流输出到 stdout |

交互模式支持 `/model`、`/route`、`/goal`、`/clear` 和 `/help`。自定义命令放在 `.heagent/commands/*.md`，自定义角色放在 `.heagent/agents/*.md`。

## Goal 工作流

`/goal` 是声明式的目标驱动开发工作流，Markdown 定义步骤、产物和门禁，Python 负责解析、checkpoint、状态迁移和 SubAgent 调度。可执行契约的唯一来源是项目内的 [`.heagent/skills/he-workflow/workflow.md`](.heagent/skills/he-workflow/workflow.md)；本节是面向维护者的导航和边界说明，不复制那份契约。

`.heagent/skills/he-workflow/` 本身是一个**技能包**（其 `SKILL.md` 声明 `canonical_id: he-workflow`），CLI 按包 id 解析它。包内除 `workflow.md` 外还可提供 `templates/prompt-template.md`（步骤提示词模板）与 `templates/gate-template.md`（门禁提示块模板）：改工作流行为应改包，而不是改 Python。

### 权威关系

| 内容 | 唯一权威 | 代码职责 |
| --- | --- | --- |
| 工作流步骤、角色、输入输出、检查点 | `.heagent/skills/he-workflow/workflow.md` | 读取、解析、校验并按声明执行 |
| 步骤方法论 | 每个步骤均由 `role:` 指向 `.heagent/skills/*/SKILL.md` | 把声明和上下文交给 SubAgent |
| 步骤提示词与门禁文案 | 包内 `templates/prompt-template.md`、`templates/gate-template.md`（**运行时依赖**） | 替换占位符渲染 prompt；资源缺失时静默回退 `cli_goal.py` 内置兜底 |
| 运行策略参数（`max_rounds`、`auto_schedule`、未决问题文案） | `workflow.md` 的 frontmatter | 读取声明；代码只保留兜底默认值 |
| Goal 身份与工作流产物 | `_he-output/goals/<goal-id>/` | 创建目录、保存输出、恢复 checkpoint |
| Goal/Epic/Story 结构契约 | `src/heagent/engine/artifacts.py` 与 `.heagent/skills/he-workflow/templates/` | 解析和校验结构 |
| 运行时进度与恢复 | `<goal-dir>/checkpoints/` 下的 `workflow.json` | 保存状态，不取代规划看板 |
| 全仓库 Epic/Story 状态 | `_bmad-output/sprint-status.yaml` | 规划历史的状态记录；不是 `/goal` 运行时状态 |

**`sprint-status.yaml` 的写权限**：`_bmad-output/sprint-status.yaml` 是规划历史的状态记录，仓库内**只读**。`/goal` 的步骤 06 在正文与 `Never` 列表里明令不得写入；`bmad-build`（显式调用时）本会经 `sync-sprint-status.md` 推进 Story 状态（`in-progress` → `review`）并把父 Epic 从 `backlog` 抬起，本项目已在 `_bmad/custom/bmad-build.toml` 用一条 `persistent_facts` 覆盖该子步骤，使它同样跳过写入（删除该文件即可恢复 bmad-build 的同步行为）。`src/` 下没有任何代码读写该文件；`validate_sprint_status_path()` 只做「状态校验必须指向这一个权威文件」的校验。

代码不应重新实现一套 Epic/Story 方法论。新增阶段、角色、产物或验收规则时，优先修改 `workflow.md` 或对应 Skill；只有新增确定性执行机制时才修改 Python。

### 当前步骤

项目默认工作流目前包含八步：

1. `market-research`：由 `bmad-agent-analyst` 产出市场、竞品、替代方案与用户证据摘要，以及决策驱动和证据缺口（只读、headless）；它是**唯一写入 goal 需求文档的步骤**——把初步分析后的「总结的需求」写进 `require.md` 的对应段（原始需求段逐字冻结，只读）。
2. `brainstorm-options`：由 `bmad-brainstorming` 以 headless「ideate for me」立场发散并收敛出候选方向排序（只读）。
3. `analyze-requirements`：分析需求并产出可验证的需求与初步 story-sized 拆分（正式 Story 清单由 step 06 产出）。
4. `define-product-scope`：形成 PRD 和有序 Epic 提案（Epic 级，不做 Story 拆分）。
5. `design-architecture`：形成架构、边界、约束和决策记录。
6. `refine-stories`：**规划步骤**——确认实现范围，拆分 Story，细化 Sprint（每个 Sprint 的目标、Story 集合、进入/退出准则、可演示切片与退掉的风险），排定工作项先后（Story 编号即执行顺序），并固定每个 Story 的验收标准与 DoD；写入 `02-epics.md` 的 `## E<N>` 分段 + `### S-N` 清单 + `## Sprint 计划`，不改实现代码。
7. `implement-story`：由 `bmad-build` 执行的**重任务步骤**（`story_loop: 02-epics.md`）。每次只实现一个 Story，并产出实现、测试与验证证据；它是唯一创建实现产物、唯一新增或修改测试文件的步骤。
8. `system-integration-test`：由 `bmad-qa-generate-e2e-tests` 执行的**全系统最终验收步骤**，只在全部 Story 完成后运行一次，覆盖逐 Epic 集成与跨 Epic 端到端测试，并给出质量门禁结论。

**写权限边界**：步骤 01–02 只读，唯一例外是步骤 01 把初步分析结论写回 goal 目录的 `require.md`（原始需求段逐字冻结，仅补写「总结的需求」段）；步骤 06 只写规划产物（`02-epics.md`），不改代码；步骤 07 是唯一创建实现产物、唯一新增或修改测试文件的步骤（实现、测试、验证三阶段都在这一步内完成；Sprint 收口与 Epic 收口评审也在这一步的边界增量内完成，评审只可为修复自己报告的 Critical 与规格偏离改代码）；步骤 08 只做最小集成修复，不重新设计实现。任何改代码的步骤都必须重跑受影响测试并写明确切命令与结果。这条边界由步骤正文声明，代码不做强制校验。

**验证工作区约定**：步骤 07/08 需要临时副本或夹具（如变异测试）时，在工作区内的 `.heagent/tmp/<goal-id>-verify/` 下用 `file_write` / `file_read` 构造与回滚；不要用 shell 把项目拷到 `%TEMP%` 等工作区外路径（会被工作区路径围栏拦下）。要跑脚本就落盘成文件再执行——内联 `python -c` / `node -e` 单行脚本难以审查与复跑（含危险关键词的内联载荷仍会被整条命令扫描拦下）。被拦命令不产生结果，只会白耗迭代预算（步骤 07 用 `GOAL_MAX_ITERATIONS`，其验证子代理用 `SUBAGENT_MAX_ITERATIONS`）。

### 敏捷环节与机械保证

「每个 Story 都有开发、测试、验证」「每个 Sprint 都有退出验证」「每个 Epic 都有集成测试」不是正文里的口号，而是由声明和运行时校验共同约束的：

| 敏捷环节 | 工作流体现 | 机械保证 |
| --- | --- | --- |
| 需求初析与落盘 | 步骤 01（初步分析，只读步骤的唯一写操作） | `validation` 强制输出含 `## 需求总结` 章节，缺一即 BLOCKED；正文要求把「总结的需求」写进 `require.md`（原始需求段逐字冻结，只补写总结段） |
| Story 拆分 + Sprint 计划 | 步骤 06（规划步骤，只写 `02-epics.md`） | `validation` 强制输出含 `## Story 拆分` 与 `## Sprint 计划` 两个章节；Story 编号从 S-1 连续且即执行顺序（`parse_story_list` 按编号后缀排序），Sprint 成员须与编号连续单调，Story 须归在 `## E<N> — <标题>` Epic 段内且段内编号连续 |
| Story 开发 + 测试 + 验证 | 步骤 07（`story_loop`，重任务） | 每 Story 独立 checkpoint；`validation` 一次强制三个章节：`## 实现摘要` / `## 测试证据` / `## 验证结论`，缺一即 BLOCKED |
| Sprint 退出验证 | 步骤 07（该 Sprint 最后一条 Story 的增量内） | 步骤正文要求跑该 Sprint 的可演示切片、核对进入与退出准则，并把结果写进该增量的 `## 收口结论` |
| Epic 收口评审（代码评审） | 步骤 07（该 Epic 最后一条 Story 的增量内） | 评审范围是整条 Epic（不是单条 Story）；报告落 `epic-<eN>/review-report.md`，含 `## 评审发现` 与 frontmatter `review_loop_iteration`（>5 即 HALT）；`## 评审发现` / `## 收口结论` 由步骤正文要求返回（非 `section:` 门禁，因 `section:` 门禁按 Story 逐条校验，无法只对收口增量生效） |
| Epic 集成测试 + 系统集成测试 | 步骤 08（全部 Story 完成之后，只运行一次） | `validation` 强制输出含 `## 评审发现` / `## 质量门禁` / `## 系统集成结论` 三个章节，缺一即 BLOCKED；逐 Epic 子报告 `epic-<eN>/integration-report.md` + 顶层索引 |

`validation` 里的 `section: <标题>` 由 `WorkflowRunner._validate_output` 机械校验：输出缺少该 Markdown 标题即判为 BLOCKED，不会静默推进。唯一解析入口是 `required_sections()`（`engine/workflow_runner.py`）；`_goal_declarative_prompt` 会在派发步骤**之前**把同一批标题写进 prompt 的 "Gate requirements" 段（并声明标题须独占一行、不得改后缀），使执行者动手前就知道自己会被哪些标题判定——门禁本身仍然只在步骤返回后机械校验，不因 prompt 提示而放宽。所有步骤均由 `role:` 指向相应的 `.heagent/skills/<role>/SKILL.md`。

这些步骤不是 Python 中的固定状态机。`WorkflowRunner` 只负责顺序、输入缺失、输出结果、checkpoint 和恢复；`cli_goal.py` 负责确定性装配和 SubAgent 调用。

### 运行方式

```text
/goal <目标>       创建目标并执行 workflow.md 的第一步
/goal new <目标>   显式创建目标
/goal next         推进一个声明步骤或一条 Story
/goal run          连续推进，遇到 checkpoint/阻塞即停止
/goal status       查看当前状态和产物
/goal pause        保存并暂停
/goal resume       记录用户回复并继续
/goal auto [cron]  注册 cron 自动推进
/goal reset        清除 current 指针但保留目标目录
```

每个步骤或 Story 都启动新的 SubAgent/RunContext。上下文窗口重置、ledger 幂等、PolicyEngine、工具执行和 OS 沙箱属于运行机制；它们不决定 Epic/Story 如何拆分。

### 产物布局

```text
_he-output/goals/<goal-id>/
├── require.md                           # 需求文档：原始需求（创建时写入）+ 总结的需求（step 01 初步分析后写入）
├── 02-epics.md                          # 由 step 06 写入的 Epic/Story 清单（## E<N> 分段 + ### S-N，编号即执行顺序）+ ## Sprint 计划
├── step-01-market-research.md           # 市场调研摘要与证据缺口
├── step-02-brainstorm-options.md        # 头脑风暴与候选方向
├── step-03-...md                        # 其余非 Story 步骤输出
├── step-07-implement-story/
│   ├── index.md                         # 顶层索引（最后一条 Story 之后写：Epic 总览 + 逐 Story 表格）
│   └── epic-e1/                         # 按 Epic 分组（E1 -> epic-e1）
│       ├── review-report.md             # Epic 收口评审报告（该 Epic 最后一条 Story 的增量内写）
│       └── s-1/
│           ├── story.md                 # 该 Story 的验收契约（逐字定义）
│           ├── implementation.md        # 改动清单与决策
│           ├── test-report.md           # 测试证据（验收标准到测试的映射、命令与结果）
│           ├── verify-report.md         # 自验证判定（逐条验收标准的证据）
│           └── report.md                # CLI 写入的步骤输出（含三个强制章节）
├── step-08-system-integration-test.md   # 系统集成与测试报告（含三个强制章节）
├── step-08-system-integration-test/
│   └── epic-e1/integration-report.md    # 每个 Epic 的集成测试报告（全部 Story 之后）
└── checkpoints/                         # WorkflowRunner 运行时 checkpoint
```

`.heagent/skills/he-workflow/templates/` 提供 Goal、Epic、Story 的结构模板。历史规划、验收和 retrospective 归档在 [`_bmad-output/`](_bmad-output/README.md)，不作为当前运行时配置。

### 修改工作流的规则

- 变更流程顺序或阶段职责：修改 `.heagent/skills/he-workflow/workflow.md`。
- 变更步骤提示词或门禁文案：改包内 `templates/prompt-template.md` / `templates/gate-template.md`（占位符清单见包 `SKILL.md`；这两个是**运行时依赖**，清理 `templates/` 时不要删——缺失不会报错，只会静默退回内置模板）；变更 `/goal run` 的步数上限、`/goal auto` 的默认 cron、未决问题策略文案：改 `workflow.md` 的 frontmatter 声明（`max_rounds` / `auto_schedule` / `open_question_default` / `open_question_block`）。两者都不需要改 Python。
- 新增或重排步骤：在 `workflow.md` 加 `## Step NN: name` 区块，`NN` 必须从 1 连续递增；每个步骤的 `role:` 必须指向已安装的 `.heagent/skills/<role>/SKILL.md`——指向不存在的包会在执行到该步骤时硬失败（不是降级）；`input:` 的每个引用必须是 CLI 注入键（`user intent` / `user responses` / `existing project context`）或前序步骤 `output:` 声明的名字，否则该步骤会被判为 BLOCKED。
- Story 编号就是执行顺序：`parse_story_list` 按 `S-<n>` 后缀排序，因此 `02-epics.md` 的 Story 编号必须从 S-1 连续、无重复，Sprint 成员必须与编号连续单调；否则 Sprint 划分与实际执行顺序错位。步骤 07 读取该文件，不得修改。
- Epic 段落与编号：`02-epics.md` 里每个 Epic 用 `## E<N> — <标题>` 段（`N` 从 1 连续、与有序 Epic 提案同序同号），该 Epic 的 Story 用 `### S-N` 全部列在这一段内且编号连续。Story 归属只由所在 Epic 段落与 Story 块内的 `父 Epic` 字段（后者优先）决定，它同时决定产物目录名 `epic-<eN>/`；交叉或错号会让分组静默错位。
- 声明 `story_loop: <artifact>` 的步骤会按该产物里的 Story 列表逐条展开，每条 Story 独立 checkpoint；产物落到 `<goal-dir>/step-NN-<slug>/epic-<eN>/s-<n>/report.md`（`parse_story_list` 归一化 Epic 引用为 `E<N>`，无 Epic 分组的产物退化为 `<goal-dir>/step-NN-<slug>/s-<n>/report.md`）。未声明 `story_loop` 的步骤只运行一次，需要按 Epic 分片时由步骤正文要求逐 Epic 产出子报告（如步骤 08）。
- 收口动作不是独立步骤：Sprint 收口与 Epic 收口评审由步骤 07 的正文按「当前 Story 是否落在边界上」判定并执行，因为它们共享 Story 循环的会话与 checkpoint。`section:` 门禁按每条 Story 逐次校验，无法只对收口增量生效，故这两个章节靠步骤正文要求 + 步骤 08 复核。
- 重任务步骤可用 `max_iterations: <1..1000>` 覆盖该步骤的 SubAgent 迭代预算（缺省继承 `Settings.goal_max_iterations`）；原子大 Story 建议显式放宽，撞上限会让整步/整批以 `failed` 收场。
- 遗留项台账由 bmad-build 模板写入 `_bmad-output/implementation-artifacts/deferred-work-archive.md`（goal 内的 Epic 级台账落在 `_he-output/goals/<goal-id>/step-*/…/deferred-work.md`）；`/deferred` 是它的 reader，会列出全部台账的条目数与最新条目。
- 需要机械保证的验收证据，用 `validation: section: <标题>; <说明>` 声明——`WorkflowRunner` 会校验输出是否包含该 `## <标题>`（必须是独占一行、无后缀的 `## 标题`；`## 标题（S-1）` 照样判缺失）。这些标题会由 `_goal_declarative_prompt` 先注入步骤 prompt 的 "Gate requirements" 段，执行者无需猜测门禁标题。不要在 `validation` 里使用 `given` 一词，除非确实要求输出符合 Given/When/Then 格式。
- 变更角色执行方法：修改 `role:` 指向的 `.heagent/skills/<skill>/SKILL.md`；`workflow.md` 仅维护步骤的声明、边界与产物约束。
- 变更产物字段或父子关系：同步修改 `engine/artifacts.py`、模板和测试。
- 变更恢复、checkpoint、路径安全或工具执行：修改 `src/heagent/` 机制代码，并同步 `docs/frame.md`。
- 重排已有步骤编号会让存量未完成 goal 的 checkpoint 索引错位；改动前先确认没有活跃 goal 指针。
- 不要在 `cli_goal.py` 增加与 `workflow.md` 平行的业务流程分支。

## 配置与运行时数据

完整配置、默认值和路由池示例见 [`.env.example`](.env.example)。以下是常见开关：

```dotenv
# 工具权限与 shell 后端；都只是纵深防御，不是 OS 级安全边界
PLAN_MODE=false
APPROVAL_TOOLS=shell,file_write
SANDBOX_MODE=workspace-write      # read-only | workspace-write | danger-full-access
SANDBOX_BACKEND=auto              # auto | passthrough | firejail | winjob
SANDBOX_NETWORK=false

# 上下文与路由
CONTEXT_STRATEGY=compressor       # compressor | reset
TOKENIZER=auto                    # auto | estimate | tiktoken
MAX_CONTEXT_TOKENS=512000
# ROUTING_POOLS={"deepseek":{"tiers":{"fast":"deepseek-flash","pro":"deepseek-v4-pro"}}}

# 可观测性与扩展
EVENTS_ROLLOUT_ENABLED=false
MCP_ENABLED=true
HOOKS_ENABLED=false
```

项目运行时状态写入 `.heagent/`，不应提交密钥或个人状态：

| 位置 | 内容 |
| --- | --- |
| `.heagent/skills/` | 本地技能包 |
| `.heagent/memory/`、`.heagent/user/` | 事实记忆与用户画像 |
| `.heagent/sessions/` | 会话历史 |
| `.heagent/runs/`、`.heagent/ledger/` | 运行快照、rollout 与工具幂等记录 |
| `.heagent/cron/` | Cron 状态 |
| `.heagent/CONTEXT.md` | 项目上下文，优先级高于 `AGENTS.md`、`CLAUDE.md` |

`SOUL.md` 可放在项目 `.heagent/SOUL.md` 或用户 `~/.heagent/SOUL.md`，项目级优先。会话、日志、编辑快照、run、ledger 和沙箱目录有保留期清理策略；技能、记忆与 Cron 不会自动删除。

## 安全说明

HeAgent 能执行 shell、读写文件、调用外部 API，并把工具返回内容再次送入模型上下文。请始终假定不可信网页、文件、MCP server 和工具输出可能含 prompt injection。

- `SafetyGuard`、路径校验、`PolicyEngine` 和内置 sandbox **不是完整安全边界**。
- 处理不可信任务时，请在容器、VM 或其他 OS 级隔离中运行，并限制文件系统和出站网络。
- `firejail` 仅适用于 Linux；不可用时回退到 `passthrough`。Windows `winjob` 仅做进程级约束，不隔离文件系统。
- Hooks 以当前用户权限执行本地命令，默认关闭；启用前必须确认仓库可信。

MCP 从 `.mcp.json` 加载，密钥应保存在环境变量中而非配置文件里。详细安全边界、工具链和已知缺口见 [架构参考](docs/frame.md) 与 [部署说明](deploy/README.md)。

## Python API

```python
import asyncio

from heagent import Agent, OpenAIProvider


async def main() -> None:
    agent = Agent(OpenAIProvider(api_key="sk-...", model="gpt-4o"))
    print(await agent.run("你好"))


asyncio.run(main())
```

## 开发

```bash
# 默认跳过 integration 与 benchmark
pytest

# 外部依赖集成测试
pytest -m integration

# 静态检查
ruff check src tests
ruff format --check src tests
mypy src
```

模块依赖、测试与安全约束见 [AGENTS.md](AGENTS.md)。测试、代码、配置与历史文档的权威关系见 [文档索引](docs/README.md)。

## 深入阅读

| 目标 | 文档 |
| --- | --- |
| 当前架构、数据流、工具与已知缺口 | [架构参考](docs/frame.md) |
| 项目定位、设计目标和非目标 | [设计说明](docs/design.md) |
| 部署、Docker 与 Windows 可执行文件 | [部署说明](deploy/README.md) |
| 历史规划与验收证据 | [_bmad-output/README.md](_bmad-output/README.md) |

## 许可证

本项目采用 [MIT License](LICENSE)。使用时还应遵守依赖项及外部 Provider 的许可与服务条款。
