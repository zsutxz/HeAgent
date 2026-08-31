# Epic 41 开发上下文（/goal 启动 skill 执行工作流）

> 契约权威：[`spec-goal-command/SPEC.md`](spec-goal-command/SPEC.md) + [`spec-goal-command/goal-workflow-contract.md`](spec-goal-command/goal-workflow-contract.md)。本文件只给代码锚点。

## 挂载点（行号基于 2026-08-29 master e192934）

- `src/heagent/cli.py`
  - `_build_slash_registry` :865-909——`/goal` 注册点（:899 后、自定义命令循环 :901 前）；handler 闭包可达 provider/loop（engine 经 `loop.engine` 公开属性，:185）
  - `_run_job` :505-521——cron runner，**前缀路由挂点**（每个 cron job 本就在全新 AgentLoop 跑，goal 前缀分流到 goal 推进路径）
  - `_dream_runner` :630-648——SubAgent 闭包先例（懒导入 `from heagent.agent.sub import SubAgent`）
  - `_handle_slash` :912-920——name+args 拆分语义（args = 空白折叠 join）
  - imports 区 :19-46——需补 `SubAgent`、`engine.persist.atomic_write_text`
  - uuid 惯例 :694 `uuid.uuid4().hex[:8]`
- `src/heagent/agent/sub.py`
  - `__init__` :61-81——`metadata: dict[str, Any] | None = None` 参数挂点（window_reset 之后）
  - `run()` :168——metadata 合并点 `{"kind": "subagent", **self._metadata}`
  - 每次 run 全新 AgentLoop + 独立 RunContext（fresh context 本体）；异常不抛出回传 success=False
- `src/heagent/context/window_reset.py`——`WindowResetConfig(threshold)`：token 阈值→摘要→清窗→metadata 落盘→续跑（直接复用，勿改）
- `src/heagent/config.py:109`——`window_reset_threshold`（默认 0.6）；`max_iterations` 字段同文件
- `src/heagent/slash.py`——`SlashRegistry.register/dispatch`（零依赖纯注册表，slash 不得 import agent/providers）
- `src/heagent/engine/persist.py:112`——`atomic_write_text(path, text, *, lock=False)`（自动 mkdir；Runner 落盘全走它）
- `.heagent/skills/goal/SKILL.md`——工作流 skill 草稿已就位（采纳为基线）；契约全文同 `_bmad-output/specs/spec-goal-command/goal-workflow-contract.md`

## 状态目录约定

`.heagent/goals/<goal_id>/GOAL.md`（LLM 按 skill 契约维护）+ `goal.txt`（原始描述，planning 恢复路径）+ `.heagent/goals/current` 指针（Runner 独占）。机器只扫：首处 `status:` 行（planning|executing|done|blocked）+ `- [ ]`/`- [x]` checkbox 计数。

## 测试模式

- `tests/test_agent_loop.py:26-67`——StubProvider 预配置响应序列 + `_tc`/`_tool_resp`（脚本化 file_write tool_calls 让 LLM「写」GOAL.md）
- `tests/test_slash.py`——直接 import `heagent.cli` 内部，假 registry 测 dispatch
- `tests/test_sub_agent.py`——SubAgent 构造最小用例（metadata 回归锁定）
- 全部 `monkeypatch.chdir(tmp_path)` + `reset_settings()` fixture
- file_write 工具会真实写 tmp cwd（ToolRegistry 单例 + builtins import 副作用注册），workspace 围栏锚定 cwd

## 边界提醒

- 禁止建 goal.py 模块（NFR-1 分层铁律，用户多轮拍板）；机制代码全在 cli.py（~130 行内）
- sub.py 只加 metadata 参数（默认 None 向后兼容）
- 非 goal 前缀 cron 路径逐字节一致（回归锁定）
- `.heagent/` gitignored：SKILL.md 属运行时本地件，skill 缺失报错附创建指引即分发通道
