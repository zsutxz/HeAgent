- source_spec: `_bmad-output/epics/epic-41-目标驱动开发周期/spec-41-1-goal-skill-single-step.md`
  summary: 为 GUI `/goal` 定义输出转发、取消控制和 cron scheduler 生命周期，并添加端到端交互测试。
  evidence: GUI 直接调用 CLI runner，`click.echo` 的进度和失败信息不进入 RichLog，且 GUI 仅持有 JobStore、没有运行 CronScheduler；现有测试只覆盖 CLI registry。
- source_spec: `epic-41/spec-41-1-goal-skill-single-step.md`
  summary: Add an inter-process lock around goal pointer reads, sessions, and GOAL.md writes.
  evidence: The current asyncio lock only serializes tasks within one process; a second CLI process can execute the same story concurrently and lose progress.

- source_spec: `epic-41/spec-41-1-goal-skill-single-step.md`
  summary: Route CLI goal runner output into the Textual RichLog instead of process stdout/stderr.
  evidence: GUI goal commands currently invoke the shared runner, whose click.echo output is not captured by the chat log.
