# HeAgent GUI 终端界面 — Product Brief

> BMad Method · Step 1: brief
> 日期: 2026-07-23
> 状态: draft
> 参考: docs/gui-plan.md

## 一、产品意图

HeAgent 当前仅提供 CLI 交互（`python -m heagent` 进入 REPL 聊天，或 `python -m heagent "prompt"` 单次执行）。对于日常使用场景，CLI 有三个体验短板：

1. **流式输出与工具调用混在一起**——用户难以区分 LLM 文本、工具调用参数、工具返回结果
2. **管理操作无界面**——技能/Soul/Cron/记忆的查看与管理需要手动编辑文件或记住工具名
3. **运行历史不可见**——子 Agent 委派、运行树、事件日志等运行时信息在 CLI 中完全不可见

本次周期的目标：**为 HeAgent 增加一个终端 GUI（TUI），把 Agent 交互从"命令行 REPL"升级为"结构化终端应用"**。不改动核心模块（`AgentLoop` 等），GUI 是纯消费者。

## 二、目标与非目标

### 目标（In Scope）

1. **流式聊天界面**：Markdown 渲染的对话列表，LLM 文本流式逐字显示
2. **工具调用可视化**：工具调用/结果以折叠卡片呈现，参数和返回值可展开查看
3. **管理面板**：技能列表/创建/编辑/归档；Cron 任务查看/增删；记忆/画像浏览
4. **运行可观测性**：引擎事件日志、运行历史树（supervisor → sub-agent 关系）、Token/迭代状态栏
5. **斜杠命令**：`/model` 切换 LLM、清屏、中断 Agent 运行
6. **可选依赖**：`[gui]` extra，不装 Textual 不影响现有 CLI

### 非目标（Out of Scope）

- **Web 界面**（浏览器访问）——属未来独立周期
- **多会话并发**——保持与 CLI 交互模式一致的单会话模型
- **图形化配置向导**——`.env` 编辑已足够
- **移动端或远程访问**——TUI 定位是本地终端
- **修改 `AgentLoop` 核心**——GUI 仅消费 `run_stream()` + `EventBus`，核心零改动

## 三、成功标准

| # | 标准 | 衡量方式 |
|---|------|----------|
| 1 | `pip install -e ".[gui]"` 后可启动 TUI | 手工验证 |
| 2 | 输入 prompt 后流式看到 LLM 回复，Markdown 正确渲染 | 手工验证 |
| 3 | 工具调用以折叠卡片显示，展开后可见参数和结果 | 手工验证 |
| 4 | 技能/Cron 管理面板可完成 CRUD 操作 | 手工验证 |
| 5 | 运行历史树正确展示 supervisor → sub-agent 层级 | 手工验证 |
| 6 | 核心模块（`agent/`、`engine/` 等）零改动 | `git diff` 验证 |
| 7 | 不装 `[gui]` extra 时 CLI 行为不变 | 现有测试全量通过 |

## 四、约束

- GUI 包位于 `src/heagent/gui/`，**禁止**从 `agent/` / `engine/` 等核心模块导入 GUI 代码
- 依赖 Textual ≥ 1.0（终端 UI 框架），通过 `[project.optional-dependencies] gui` 声明
- 入口为 `heagent gui` 子命令（`click.Group`），与现有 `heagent [prompt]` 并列
- 复用现有接口：`AgentLoop.run_stream()`（流式对话）、`EventBus`（引擎事件）、`RunStore`（运行历史）、`SkillStore`/`FactStore`/`ProfileStore`/`JobStore`（管理面板数据源）
- Windows Terminal / macOS Terminal.app / Linux 现代终端均可运行（Textual 1.0 官方支持）

## 五、风险

| 风险 | 缓解 |
|------|------|
| Textual 1.x API 不稳定 | pin 版本；Textual 1.0 已 GA |
| `run_stream()` 的 `CancelledError` 清理不完整 | Phase 1 即验证中断路径 |
| 终端兼容性（Windows cmd 旧版） | 检测终端能力，不支持的报友好错误 |
| GUI 依赖拉重 | `[gui]` optional extra，默认不装 |

## 六、决策日志

| ID | 决策 | 理由 | 日期 |
|----|------|------|------|
| D1 | GUI 周期不改动核心模块 | 核心已有 `run_stream()` + `EventBus` 两个充分接口；GUI 是纯消费者 | 2026-07-23 |
| D2 | 选 Textual（TUI）而非 Web | 对齐项目定位（终端工具 / 学习实验）；Textual async-native 无需桥接层 | 2026-07-23 |
| D3 | 分 4 个 Phase 交付 | 每 Phase 独立可演示，降低集成风险 | 2026-07-23 |
| D4 | `heagent gui` 子命令而非 `--gui` flag | CLI 模式与 GUI 模式启动路径差异大（asyncio 上下文、Session/Scheduler 策略）；子命令更干净 | 2026-07-23 |
