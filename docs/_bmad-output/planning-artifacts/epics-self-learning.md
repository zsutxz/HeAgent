---
stepsCompleted: [1, 2]
inputDocuments:
  - HeAgent/docs/prd-HeAgent-2026-05-23/prd.md
  - HeAgent/docs/architecture-HeAgent-2026-05-23/architecture.md
  - HeAgent/docs/frame.md
  - HeAgent/src/heagent/agent/loop.py
  - HeAgent/src/heagent/memory/skills.py
  - HeAgent/src/heagent/cli.py
  - HeAgent/src/heagent/config.py
status: 'in-progress'
project_name: 'HeAgent'
user_name: 'tan'
date: '2026-06-08'
---

# HeAgent - 自学习闭环 Epic 分解

## Overview

本文档为 HeAgent 新增的「自学习闭环」功能提供 Epic 和 Story 分解。这些功能超出了原有 MVP PRD（FR-1~19）的范围，参考 Hermes Agent 的 5 大支柱设计，补上 HeAgent 从"被动工具"到"主动学习者"的关键能力差距。

所有新功能基于已有的 AgentLoop/Provider/工具/记忆架构，遵循现有模式（Pydantic model、configure_* 注入、@tool 装饰器注册、async/await）。

## Requirements Inventory

### Functional Requirements（新增）

- FR-20: Context Files 自动加载 — 扫描项目目录下的上下文文件（.heagent/CONTEXT.md、AGENTS.md、CLAUDE.md），自动注入系统提示词，让 Agent 理解项目背景
- FR-21: SOUL.md 人格系统 — 通过 SOUL.md 定义 Agent 人格和语气，支持全局（~/.heagent/SOUL.md）和项目（.heagent/SOUL.md）两级，项目级覆盖全局级
- FR-22: Memory Nudge 记忆提醒 — 在系统提示词中注入静态提醒，鼓励 Agent 主动保存重要信息，可配置启用/禁用
- FR-23: Skill Curator 技能策展 — 追踪技能使用频率和时效性（usage_count、last_used），检测过期技能并支持归档到 .archive/
- FR-24: Cron 定时调度 — 内置 cron 调度器（asyncio 后台任务），支持 5-field cron 表达式和一次性/循环任务，Agent 可通过工具自主创建定时任务

### NonFunctional Requirements（继承自原有 PRD）

- NFR-1: 代码可读性 — 核心循环 <1,500 行，单模块 <400 行，函数 <50 行
- NFR-2: 插件化零耦合 — 新增功能不修改核心循环逻辑，通过注入和扩展实现
- NFR-6: 可测试性 — 所有模块可独立单元测试
- NFR-7: 依赖最小化 — 不引入新外部依赖，手写 cron 解析器代替 croniter

### Additional Requirements（来自 Architecture）

- Pydantic v2 BaseModel — 所有新数据模型（CronJob 等）使用 BaseModel
- configure_* 注入模式 — 新工具模块遵循 skills.py/memory.py 的模块级全局变量 + configure/reset 函数对
- .heagent/ 目录 — 新增 SOUL.md、CONTEXT.md、cron/jobs.json、skills/.archive/
- Settings 扩展 — 新配置字段遵循 pydantic-settings 的 Field 声明模式
- 系统提示词注入顺序 — identity > user system > project-context > skills > memory-nudge > memory > profile

### UX Design Requirements

不适用 — HeAgent 是 CLI/库项目，无 UI。

### FR Coverage Map

| FR | Epic | 说明 |
|----|------|------|
| FR-20 | Epic 6 | Context Files 自动加载 |
| FR-21 | Epic 7 | SOUL.md 人格系统 |
| FR-22 | Epic 8 | Memory Nudge 记忆提醒 |
| FR-23 | Epic 9 | Skill Curator 技能策展 |
| FR-24 | Epic 10 | Cron 定时调度 |

## Epic List

### Epic 6: Context Files 自动加载
用户成果：Agent 自动理解项目背景和约定，无需手动配置
**FRs covered:** FR-20
**新建文件:** context/loader.py
**修改文件:** agent/loop.py, cli.py, config.py

### Epic 7: SOUL.md 人格系统
用户成果：Agent 有可定制的人格和语气，支持多场景切换
**FRs covered:** FR-21
**新建文件:** memory/soul.py
**修改文件:** agent/loop.py, cli.py

### Epic 8: Memory Nudge 记忆提醒
用户成果：Agent 主动保存重要信息，记忆积累不再完全依赖用户触发
**FRs covered:** FR-22
**修改文件:** agent/loop.py, config.py（无新文件）

### Epic 9: Skill Curator 技能策展
用户成果：技能库保持精简有效，过期技能自动检测和归档
**FRs covered:** FR-23
**修改文件:** memory/skills.py, agent/loop.py, tools/builtins/skills.py, config.py

### Epic 10: Cron 定时调度
用户成果：Agent 可自主安排定时任务，实现无人值守的自动化工作
**FRs covered:** FR-24
**新建文件:** cron/__init__.py, cron/jobs.py, cron/scheduler.py, tools/builtins/cron.py
**修改文件:** agent/loop.py, cli.py, config.py, tools/builtins/__init__.py

## Epic 6: Context Files 自动加载

用户成果：Agent 自动理解项目背景和约定，无需手动配置

### Story 6.1: 上下文文件扫描器

As a 开发者,
I want 扫描项目目录下的上下文文件并按优先级合并,
So that Agent 在启动时就能理解项目背景和约定。

**Acceptance Criteria:**

**Given** 项目目录下存在 .heagent/CONTEXT.md、AGENTS.md 或 CLAUDE.md 中的一个或多个
**When** 调用 `load_context_files(cwd)`
**Then** 按优先级（.heagent/CONTEXT.md > AGENTS.md > CLAUDE.md）合并找到的文件内容
**And** 每个文件内容以 `## 文件名` 作为分隔标记
**And** 无文件时返回 None
**And** 空文件（仅空白字符）视为不存在

### Story 6.2: AgentLoop 集成 Context Files

As a 开发者,
I want AgentLoop 在构建系统提示词时自动注入项目上下文,
So that LLM 能理解当前项目的背景信息。

**Acceptance Criteria:**

**Given** AgentLoop 配置了 `context_dir` 参数
**When** 调用 `_build_system()`
**Then** 在用户 system 字符串之后、skills 注入之前插入 `<project-context>` 块
**And** `<project-context>` 包含扫描到的所有上下文文件内容
**And** `context_files_enabled=False` 时不扫描不注入
**And** context_dir 为 None 时跳过扫描

### Story 6.3: CLI 接入与配置

As a 用户,
I want CLI 自动传递当前工作目录给 AgentLoop,
So that 无需额外配置即可使用上下文文件功能。

**Acceptance Criteria:**

**Given** 用户在项目目录下运行 `python -m heagent`
**When** CLI 初始化 AgentLoop
**Then** 自动传入 `context_dir=os.getcwd()`
**And** Settings 新增 `context_files_enabled: bool = True` 字段
**And** 单次模式和交互模式均生效

---

## Epic 7: SOUL.md 人格系统

用户成果：Agent 有可定制的人格和语气，支持多场景切换

### Story 7.1: SoulStore 人格加载器

As a 开发者,
I want 从全局和项目两级 SOUL.md 加载 Agent 人格定义,
So that Agent 有可定制的身份和语气。

**Acceptance Criteria:**

**Given** 项目级 `.heagent/SOUL.md` 或全局 `~/.heagent/SOUL.md` 存在
**When** 调用 `SoulStore.load()`
**Then** 项目级 SOUL.md 存在时返回其内容（覆盖全局）
**And** 项目级不存在时回退到全局 SOUL.md
**And** 两者均不存在时返回 None
**And** 空文件视为不存在

### Story 7.2: AgentLoop 集成 SOUL.md

As a 开发者,
I want SOUL.md 内容作为系统提示词的第一段（identity 层）,
So that Agent 的身份定义优先级最高，影响所有后续行为。

**Acceptance Criteria:**

**Given** AgentLoop 配置了 `soul` 参数
**When** 调用 `_build_system()`
**Then** 使用 `parts.insert(0, ...)` 将 `<identity>` 块插入到 parts 列表最前面
**And** `<identity>` 块包含 SOUL.md 的完整内容
**And** soul 为 None 或 load() 返回 None 时不注入

### Story 7.3: CLI 人格选项

As a 用户,
I want 通过 CLI 参数指定自定义 SOUL.md 路径,
So that 我可以在不同场景使用不同的人格。

**Acceptance Criteria:**

**Given** 用户运行 `python -m heagent --soul /path/to/custom-soul.md`
**When** CLI 初始化
**Then** 创建 SoulStore 并将指定路径作为 project_path
**And** 未指定 --soul 时使用默认路径（.heagent/SOUL.md + ~/.heagent/SOUL.md）
**And** 交互模式和单次模式均支持 --soul 参数

---

## Epic 8: Memory Nudge 记忆提醒

用户成果：Agent 主动保存重要信息，记忆积累不再完全依赖用户触发

### Story 8.1: 系统提示词注入记忆提醒

As a 开发者,
I want 在系统提示词中注入记忆保存提醒,
So that LLM 会在完成重要任务后主动使用 fact_add 工具保存知识。

**Acceptance Criteria:**

**Given** AgentLoop 配置了 facts 参数且 memory_nudge_enabled=True
**When** 调用 `_build_system()`
**Then** 在 facts 注入之后追加 `<memory-nudge>` 块
**And** 内容为静态提醒文本："After completing a complex task or learning something important, consider using fact_add to save key insights for future sessions."
**And** facts 未配置时不注入
**And** `memory_nudge_enabled=False` 时不注入
**And** Settings 新增 `memory_nudge_enabled: bool = True` 字段

---

## Epic 9: Skill Curator 技能策展

用户成果：技能库保持精简有效，过期技能自动检测和归档

### Story 9.1: 技能使用追踪元数据

As a 开发者,
I want 技能文件记录使用次数和最后使用时间,
So that 可以追踪哪些技能真正在使用，哪些已过期。

**Acceptance Criteria:**

**Given** 一个已有的 SKILL.md 文件
**When** 调用 `SkillStore.record_usage(name)`
**Then** frontmatter 中 `usage_count` 字段 +1
**And** `last_used` 字段更新为当前 ISO 时间戳
**And** SkillContent dataclass 新增 `usage_count: int = 0` 和 `last_used: str = ""` 字段
**And** `_parse_skill_md()` 正确解析这两个新 frontmatter 字段
**And** `save()` 方法正确写入这两个字段

### Story 9.2: 过期技能检测与归档

As a 开发者,
I want 检测长期未使用的技能并归档,
So that 技能库保持精简，不积累废弃内容。

**Acceptance Criteria:**

**Given** 技能库中有多个技能，部分超过 N 天未使用
**When** 调用 `SkillStore.stale_skills(days=30)`
**Then** 返回所有超过 N 天未使用的技能名称列表
**And** 从未使用过的技能（usage_count=0）也视为过期
**And** 调用 `SkillStore.archive(name)` 将技能目录移动到 `.heagent/skills/.archive/`
**And** 归档后的技能不再出现在 `list_skills()` 和 `matching_skills()` 结果中

### Story 9.3: AgentLoop 使用追踪集成

As a 开发者,
I want 技能被自动匹配时自动记录使用,
So that 使用统计无需人工干预。

**Acceptance Criteria:**

**Given** AgentLoop 配置了 skills 参数
**When** `_build_system()` 匹配到相关技能
**Then** 对每个匹配的技能调用 `self.skills.record_usage(name)`
**And** 使用追踪发生在技能内容加载之前（先记录再加载）

### Story 9.4: 技能策展工具

As a 用户（通过 LLM）,
I want 通过工具查看过期技能和归档技能,
So that 我可以管理技能库的整洁度。

**Acceptance Criteria:**

**Given** SkillStore 已配置
**When** LLM 调用 `skill_curate(days="30")`
**Then** 返回所有超过指定天数未使用的技能列表（含 usage_count、last_used）
**And** LLM 调用 `skill_archive(name="old-skill")`
**Then** 将指定技能移至 .archive/，返回归档确认
**And** Settings 新增 `skill_curator_stale_days: int = 30` 字段

---

## Epic 10: Cron 定时调度

用户成果：Agent 可自主安排定时任务，实现无人值守的自动化工作

### Story 10.1: CronJob 模型与持久化

As a 开发者,
I want 定时任务的定义和持久化存储,
So that Agent 创建的定时任务可以跨会话保存。

**Acceptance Criteria:**

**Given** 项目初始化完成
**When** 实现 `cron/jobs.py`
**Then** `CronJob(BaseModel)` 包含 id、prompt、cron（5-field）、recurring、created、last_run、enabled 字段
**And** `JobStore` 将任务列表持久化为 `.heagent/cron/jobs.json`
**And** JobStore 支持 add、remove、list_jobs、get、update 操作
**And** 文件不存在时返回空列表，不报错
**And** 遵循与 SessionStore 相同的 JSON 文件持久化模式

### Story 10.2: Cron 表达式解析器

As a 开发者,
I want 不依赖外部库解析 5-field cron 表达式,
So that 框架不引入 croniter 等额外依赖。

**Acceptance Criteria:**

**Given** 一个 5-field cron 表达式（如 `*/5 * * * *`、`0 9 * * 1-5`）
**When** 调用 `CronScheduler._matches(cron_expr, datetime)`
**Then** 正确匹配：`*`（任意值）、`*/N`（每隔 N）、具体值、逗号分隔列表
**And** 支持分钟、小时、日、月、星期五个字段
**And** 不匹配时返回 False
**And** 无外部依赖

### Story 10.3: Asyncio 后台调度器

As a 开发者,
I want 一个 asyncio 后台任务定期检查并执行到期任务,
So that 定时任务能在 Agent 空闲时自动运行。

**Acceptance Criteria:**

**Given** JobStore 中有已启用的定时任务
**When** 调用 `CronScheduler.start()`
**Then** 启动后台 asyncio.Task，每 `cron_tick_seconds` 秒（默认 60）检查一次
**And** 匹配当前时间的任务通过 `asyncio.create_task()` 异步执行
**And** 执行任务时创建独立的 AgentLoop 实例（构造函数注入 provider + stores）
**And** 任务执行后更新 `last_run` 字段
**And** 一次性任务（recurring=False）执行后自动删除
**And** `stop()` 优雅取消后台任务

### Story 10.4: Cron 管理工具

As a 用户（通过 LLM）,
I want 通过工具创建、查看和删除定时任务,
So that 我可以用自然语言让 Agent 安排自动化工作。

**Acceptance Criteria:**

**Given** JobStore 和 CronScheduler 已配置
**When** LLM 调用 `cron_add(prompt="每天早上检查代码质量", schedule="0 9 * * *", recurring=True)`
**Then** 创建新的 CronJob 并添加到 JobStore，返回 job ID
**And** LLM 调用 `cron_list()` 返回所有已调度任务的列表（含 ID、prompt、schedule、last_run）
**And** LLM 调用 `cron_remove(job_id="abc123")` 删除指定任务
**And** 未配置时返回 "Error: cron tools not configured."
**And** 工具模块遵循 configure_cron_tools / reset_cron_tools 模式

### Story 10.5: CLI 调度器生命周期管理

As a 用户,
I want CLI 在交互模式下自动启动和停止调度器,
So that 定时任务在聊天期间可用，退出时干净关闭。

**Acceptance Criteria:**

**Given** 用户运行 `python -m heagent`（交互模式）
**When** CLI 初始化
**Then** 创建 JobStore 和 CronScheduler，传入 AgentLoop
**And** REPL 循环开始前调用 `await scheduler.start()`
**And** REPL 退出时（Ctrl+C 或空行）在 finally 块中调用 `await scheduler.stop()`
**And** `cron_enabled=False` 时不创建调度器
**And** 单次模式（带 prompt 参数）不启动调度器
**And** Settings 新增 `cron_enabled: bool = True` 和 `cron_tick_seconds: int = 60` 字段
