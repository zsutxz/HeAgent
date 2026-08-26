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
