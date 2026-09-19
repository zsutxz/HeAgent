# HeAgent 与 Codex 的对照

HeAgent 在权限档位、分层上下文文件、机器可读事件流和编辑原语等机制上有意参考 Codex；两者的目标不同：Codex 是产品，HeAgent 是实验性框架。

## 一览

| 维度 | Codex（OpenAI） | HeAgent |
| --- | --- | --- |
| 定位 | 产品级编码代理，含 IDE、桌面端与云端形态 | 实验性 Agent 框架，用于学习、原型与架构验证 |
| 实现 | Rust 工作区，多 crate | Python asyncio 单进程库，模块化 DAG |
| 模型 | 以 OpenAI 模型为主，也支持自定义 provider | DeepSeek、OpenAI、Anthropic、Kimi、GLM、Ollama，可组合路由 |
| 执行边界 | OS 级沙箱与审批策略 | 策略闸门、权限档位与可选 shell 后端；不是安全边界 |
| 上下文文件 | 分层 `AGENTS.md` 约定 | 仓库根到 cwd 的分层加载，`.heagent/CONTEXT.md` 优先 |
| 机器接口 | `codex exec --json` 事件流 | `heagent run "..." --json` JSONL、rollout 落盘与回放 |
| 代码编辑 | `apply_patch` | 唯一命中 `file_edit`、写前快照、diff 回执、CRLF/BOM 保真 |
| 多 Agent | 线程与子代理编排 | 角色化 SubAgent 委派、并行与递归深度闸门 |
| 成熟度承诺 | 官方产品与支持渠道 | 无 API 稳定性或生产就绪承诺 |

## HeAgent 的取向

1. **Provider 中立与多层容错。** 跨 Provider 回退、多密钥轮换、指数退避重试、运行时切换，以及由 `ROUTING_POOLS` 声明的 fast/mid/pro 路由池都可直接配置。
2. **声明式 Goal 工作流。** `/goal` 从 `.heagent/skills/he-workflow/workflow.md` 读取步骤、Story、checkpoint 和验收门禁，再以独立 SubAgent 会话推进。
3. **文件化的记忆与技能。** 技能、事实记忆、用户画像与 `SOUL.md` 都是可审阅、可替换的本地文件。
4. **作为库使用。** Provider、工具注册表、策略引擎、事件汇和存储均可注入，应用可只复用其中一部分。

## 有意对齐的机制

- **权限档位**：`SANDBOX_MODE` 使用 `read-only`、`workspace-write`、`danger-full-access` 三档；HeAgent 没有路径级文件系统策略。
- **分层上下文文件**：从 cwd 向仓库根合并上下文，按字节预算近端优先截断，并显式标记截断结果。
- **JSONL 事件流**：`--json` 输出包含 `run_id`、`iteration`、事件种类、工具和目标的机器可读事件；工具输出仍必须视为不可信输入。
- **编辑原语**：`file_edit` 要求旧文本唯一命中，0 处或多处命中时都不写盘；写前保留快照并生成 diff 回执。
- **Token 计量与压缩**：优先使用可用 tokenizer，回退到启发式估算，并以 Provider usage 做在线校准。

## 关键差距

1. **安全边界。** HeAgent 的 `SafetyGuard`、`PolicyEngine` 和可选 shell 后端仅是纵深防御；不提供 Codex 级别的 OS 沙箱保证。
2. **产品成熟度与生态。** HeAgent 没有云端任务、IDE 集成、SLA 或兼容性承诺。
3. **模型协同。** HeAgent 使用通用 Provider 接口，不包含产品与模型的联合调优。

## 如何选择

- 目标是可靠完成日常代码任务，应优先使用 [Codex](https://github.com/openai/codex) 等产品级编码代理。
- 目标是理解或试验 Agent 的运行时机制，或者需要自行组合 Provider、工具和记忆策略，HeAgent 更适合作为可修改的参考实现。

> 本文只描述两者的设计取向。Codex 的具体行为和能力变化很快，应以其官方文档和实际版本为准。
