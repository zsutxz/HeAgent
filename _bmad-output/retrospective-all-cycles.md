# HeAgent 全周期综合回顾

> 生成: 2026-07-22
> 覆盖: Epic 1–23 + S1–S4，7 个开发周期
> 基准: 922 测试全绿、ruff clean、覆盖率 90%

---

## 一、各周期要点速览

### 1. 主线 MVP（Epic 1–5）· 2026-05–06

| 维度 | 要点 |
|------|------|
| 成就 | BaseProvider Protocol 双实现 (OpenAI/Anthropic)、ProviderChain+KeyRotation 多层容错、@tool 声明式注册、AgentLoop 主循环、SafetyGuard、并行工具执行、会话持久化+上下文压缩、自学习记忆三件套 (skills/facts/profile)、多 Agent 并行编排 |
| 难点 | 双层异常重包、流式 backstop 不对称、P0.2 compressor 超窗口、SubAgent 竞态误判（经核实「不成立」） |
| 做对 | 协议优于实现 (Protocol+decorator)、deferred 编号化跟踪、「不成立」关闭+回归测试锁定、依赖最小化 |
| 改进 | 安全边界诚实度、send/stream 对称测试、并发竞态先核实 await 交错再定级 |

### 2. MCP Client 集成一（Epic 11–13）· 2026-06–07

| 维度 | 要点 |
|------|------|
| 成就 | 零侵入集成 (AgentLoop+ToolRegistry API 零改动)、双 transport 统一 (stdio+HTTP)、协议演进封装、错误隔离坚固、GitHub E2E 只读验收、安全立场诚实声明 |
| 难点 | eager vs lazy 发现、生命周期不污染 AgentLoop、安全诚实 vs 实用张力、MCP SDK 版本锁定 |
| 做对 | 架构基于真实代码核实非臆断、YAGNI 克制 (不抽 Protocol/不新建异常/不新建重试)、deferred 编号化、安全声明同构 |
| 改进 | FR-3 断连 auto-unregister (已补)、MCP 输出围栏 V1 缺位 (已补 DP-4)、回顾非实时 (应在 epic 完成后即做) |

### 3. MCP V2 + 内置工具扩展（Epic 14–17）· 2026-07

| 维度 | 要点 |
|------|------|
| 成就 | 写操作治理确定性闸门 (annotations→审批/放行/fail-safe)、Resources on-demand 桥接、Prompts slash 命令、4 个 git 内置工具、v1→v2 隔离层先行 |
| 难点 | fail-safe 精准作用域 (仅 MCP+缺注解)、annotations 不可信但又用它裁决的张力、两份 Epic 14 编号冲突、跨 server 同名 URI 消歧 |
| 做对 | 步 0 前置闸门 `schema=None` 零回归保护、显式策略优先于 annotations、`guard_content` 提取为公共函数、Resources on-demand / Prompts user-controlled 正确切分、MCP 后续不作为必要功能——边界清晰 |
| 改进 | Epic C (Prompts) 预算紧张仍交付——应先验证 A+B、`idempotentHint`/`openWorldHint` 透传不裁决但 LLM 可见、Prompts slash 分发器最简实现 (未来可能需要结构化注册表)、git 工具本质是 shell wrapper |

### 4. Sandbox 硬化（Epic S1–S4）· 2026-07-20

| 维度 | 要点 |
|------|------|
| 成就 | 死字段激活 (`sandbox_profile` → firejail 参数映射)、零门槛可及 (.env/CLI 启用)、Linux 进程组 kill + `--private` workspace 隔离、contextvar 同构注入 |
| 难点 | 纯函数可测性 vs 运行时 contextvar、降级不抛异常意味着静默失去保护、`--private` 参数插入位序 |
| 做对 | 每个 FR 至少 1 独立单测+1 集成测试、模块边界严格 (不反依赖 agent/providers/memory)、`available` 属性暴露可观测性、安全声明始终诚实 |
| 改进 | S4-1 emit 事件被跳过 (可观测性缺口)、降级为静默 (伪安全感)、无内置安全 profile 库、无人验证 profile 参数合法性 |

### 5. 健壮性/质量硬化（Epic 18–19）· 2026-07-21

| 维度 | 要点 |
|------|------|
| 成就 | 跨进程文件锁 (POSIX/Windows 自适应)、Cron 范围/步进表达式、WinJobBackend (Job Objects)、覆盖率 89→90%、CI 3平台×3Python 矩阵、静态分析 (Ruff/Bandit/pip-audit)、v0.3.0 版本同步 |
| 难点 | 跨平台文件锁双实现、Cron 范围+步进组合解析、Windows Job Objects (ctypes)、覆盖率 90% 硬拦精准定位 |
| 做对 | "不改架构、不加依赖、全 stdlib"、优雅降级模式一致、defense-in-depth 意识贯穿、参数化对齐测试、CI 不引入提交延迟 |
| 改进 | agent/loop.py 复杂度是技术债 (C901 accepted)、覆盖率 438 条 miss 可推 92%、benchmark 缺乏历史趋势追踪 |

### 6. 质量工程深化（Epic 20–23）· 2026-07-22

| 维度 | 要点 |
|------|------|
| 成就 | Coverage 工程化 (`[tool.coverage]` 段落入)、benchmark 重构 (pytest-benchmark)+CI 历史对比、Docker 硬化 (.dockerignore/HEALTHCHECK/digest)、CI 效能 (pip 缓存/3.14-dev)、安全左移 (CodeQL/dependency-review)、pre-commit 加固 (卫生 hooks+bandit)、Ruff 规则扩展 (PLC/RUF/PT/PIE+format) |
| 难点 | benchmark 语义迁移 (单次→多轮)、CI runner 噪音 (20% 退化阈值)、新增 ruff 规则告警量控制、HEALTHCHECK 无 HTTP 端点 |
| 做对 | benchmark warning 不 fail (AD-2)、3.14-dev continue-on-error (AD-4)、CodeQL 仅 security+每周 (AD-3)、分层门禁 (本地88/CI90)、豁免必须注释、历史 artifact 下载失败优雅跳过 |
| 改进 | coverage fail_under 未提升 (AD-7)、CodeQL 仅 security (quality 可能藏 bug)、bandit -ll 可探讨 -l、benchmark 数据不入库 (artifact 7 天过期)、Docker digest 无自动更新 |

---

## 二、跨周期模式：做对了什么

| # | 模式 | 证据 |
|---|------|------|
| 1 | **协议优于实现** | BaseProvider Protocol、@tool 装饰器、Middleware 管道——新增模块零改动核心 |
| 2 | **deferred 编号化** | DP-4 等「暂不做」决定跨文档引用 (CLAUDE.md/frame.md/architecture.md)，防遗忘 |
| 3 | **「不成立」关闭模式** | SubAgent 竞态误判经核实关闭+回归测试锁定假阴性——比硬修不存在的问题更有价值 |
| 4 | **依赖最小化** | 手写 cron 解析器避掉 croniter、文件锁全 stdlib——NFR 贯彻始终 |
| 5 | **增量保持干净** | P5+engine 叠加式不动契约、DI 注入不篡改 AgentLoop 签名 |
| 6 | **YAGNI 克制** | MCP 2 transport 不抽 Protocol、不新建异常/重试、annotations 透传不裁决 |
| 7 | **防御纵深意识** | 所有安全相关组件明确标注「非真正边界，须 OS 级沙箱兜底」 |
| 8 | **分层门禁** | 本地 88/CI 90 coverage、bandit -ll 不阻塞 CI——差异化约束不互锁 |
| 9 | **优雅降级模式** | Firejail/WinJobBackend 不可用→warn+Passthrough，不 crash、不中断 |
| 10 | **对称性审查** | send/stream、enter/exit、kill/wait——成对路径互相对照补齐 |

---

## 三、跨周期模式：可改进什么

| # | 模式 | 建议 |
|---|------|------|
| 1 | **安全边界诚实度** | SafetyGuard/engine sandbox 均非真边界但命名像边界——命名/文档应降低「安全」期望 |
| 2 | **回顾不及时** | 仅 epic-13 做过实时回顾，其余事后补——epic 完成即回顾 |
| 3 | **静默降级** | firejail 不可用仪 warn 不中断——用户可能误以为沙箱已开。应加首次加载提示或 CLI banner 标注 |
| 4 | **编号冲突** | 两份 Epic 14 (mcp-v2-upgrade 与 mcp-client-v2) 同名异义——后续跨周期应统一编号空间 |
| 5 | **复杂度接受** | agent/loop.py C901 超标不拆——长期应拆分 |
| 6 | **可观测缺口** | S4-1 emit 事件跳过、benchmark 数据不入库——历史趋势和沙箱执行轨迹不可追溯 |
| 7 | **内置预设缺失** | sandbox profiles 无开箱即用预设、cron 无常见模板——降低用户上手成本 |
| 8 | **扩展点不足** | Prompts slash 分发器最简 `startswith("/")`、git 工具逐个加——未来可能需要结构化注册表 |

---

## 四、指标总结

| 指标 | 数值 |
|------|------|
| 总 Epic 数 | 27 (主线 10 + MCP V1 3 + MCP V2 4 + Sandbox 4 + 健壮性 2 + 质量 4) |
| 总 Story 数 | ~85 |
| 总测试数 | 922 |
| 覆盖率 | 90% (4310 statements, 438 miss) |
| 代码行数 | ~12000 (含测试) |
| 外部依赖 | 6 (openai/anthropic/tiktoken/pydantic/pydantic-settings/mcp) |
| 开发周期 | 2026-05-26 → 2026-07-22 (58 天) |

---

## 五、已归档

本文标记所有周期回顾为 `done`。sprint-status.yaml 中所有 `epic-N-retrospective` 均更新为 `done`。

回顾产物索引：
- Epic 13 正式回顾: `_bmad-output/mcp-client/retrospective-epic-13.md`
- Engine P5 回顾: `_bmad-output/patches/retrospective-engine-p5.md`
- P0 技术债回顾: `_bmad-output/patches/retrospective-p0-tech-debt.md`
- **全周期综合回顾 (本文)**: `_bmad-output/retrospective-all-cycles.md`
