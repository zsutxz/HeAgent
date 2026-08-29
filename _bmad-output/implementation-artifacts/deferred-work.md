# Deferred Work

- source_spec: `_bmad-output/epics/epic-40-沙箱会话化周期/stories/40-1-session-workspace-directory.md`
  summary: 沙箱会话目录 crash 孤儿无 GC/保留策略（40.4 teardown 只覆盖正常结束路径）
  evidence: review 迭代1 分诊：每 run 创建 `.heagent/sandboxes/<run_id>/`，进程 crash 后目录残留无回收；ledger 有 `ledger_retention_days` 先例，sandboxes 无对应策略，长期开启开关无界占盘
- source_spec: `_bmad-output/epics/epic-40-沙箱会话化周期/stories/40-1-session-workspace-directory.md`
  summary: 沙箱会话目录对 LLM 不可见（无 system prompt 注入或工具暴露，shell 与 file 工具 split-brain）
  evidence: review 迭代1 分诊：sandboxed shell 相对路径写入落会话目录，但 LLM 无从得知目录位置，file 工具按 workspace_root 围栏解析——40.4 SandboxSession 规划时应一并决定模型可见性送达链路
- source_spec: `_bmad-output/epics/epic-40-沙箱会话化周期/stories/40-1-session-workspace-directory.md`
  summary: `--private` 空 HOME 语义未文档化（firejail --private 是 HOME 替换非全文件系统隔离，per-run 空目录丢失 gitconfig 等 HOME 相对访问）
  evidence: review 迭代1 分诊：frame.md 既有「OS 级文件系统隔离」措辞高估 `--private` 实际语义，本故事加深依赖；属既有文档 accuracy 修复，非 40.1 阻塞
- source_spec: `_bmad-output/epics/epic-40-沙箱会话化周期/stories/40-1-session-workspace-directory.md`
  summary: WinJob cwd 分支在 Linux CI 零覆盖（win32-only skip 模式，需假 ctypes 注入做成跨平台测试）
  evidence: review 迭代1 分诊：两个新 WinJob cwd 测试非 win32 即 skip，项目 CI 跑 Linux，新增分支从未在 CI 执行；属既有 WinJob 测试模式整体局限
- source_spec: `_bmad-output/epics/epic-40-沙箱会话化周期/stories/40-1-session-workspace-directory.md`
  summary: `SANDBOX_SESSION_WORKSPACE` 无 CLI 旗标对等（兄弟配置 SANDBOX_BACKEND 有 `--sandbox` 旗标且启动横幅打印）
  evidence: review 迭代1 分诊：env-only 入口对 CLI 用户不可发现；epic 约束只要求既有入口不破坏，未要求新旗标，属可发现性增强
- source_spec: `_bmad-output/implementation-artifacts/spec-41-1-goal-skill-single-step.md`
  summary: goal 会话 max_iterations 恒用 SubAgent 默认 20，用户无法经 CLI/设置调整
  evidence: 评审（Story 41.1 blind-hunter）确认 _goal_session 不传 max_iterations，而主循环用 CLI 参数、dream 闭包用 settings.dream_max_iterations，三处口径不一致；长 story 实现会话会触顶显性失败（可经 /goal next 重试）但用户为长 story 调大上限会被静默截断。41.2 run 循环设计时应复核（引入 goal_max_iterations 设置或透传 CLI 参数）。
- source_spec: `_bmad-output/implementation-artifacts/spec-41-1-goal-skill-single-step.md`
  summary: TUI（gui/）平行 slash 面不识别 /goal，输入会当普通 prompt 提交给主 AgentLoop
  evidence: 评审（verification-gap）确认 gui/widgets/input_area.py:23 的 _SLASH_COMMANDS 补全表与 gui/screens/chat.py:181-193 的 _handle_slash 均未纳入 /goal，chat.py:193 return False 后落入普通 prompt 路径，LLM 收到字面 "/goal next"。GUI 平行 slash 处理先于本 story 存在（非本 story 造成），但 /goal 已交付的 CLI 能力在 TUI 不可达是真实采用缺口。
