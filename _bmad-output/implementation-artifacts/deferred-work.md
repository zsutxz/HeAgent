- source_spec: `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/stories/46-1-skill-resource-toctou-assessment.md`
  summary: 后续评估 descriptor-relative/目录句柄、可信导入 snapshot 或 OS sandbox 加固。
  evidence: Story 46.2 已以 `O_NOFOLLOW` 加固支持平台上的最终路径组件，并保留不支持该标志时的兼容回退；中间目录替换、可信导入 snapshot 与 OS sandbox 仍未交付，现有路径围栏保留竞态残余风险。
- source_spec: `.claude/skills/bmad-build/step-04-review.md`（渲染件 `_bmad/render/bmad-build/heagent-50877a51e192/aeca6e838f8ddd95e529/step-04-review.md`）
  summary: Blind Hunter 层未定义 `CONTENT` 的范围、无「空 diff 前置门禁」、无大 diff 分片或体量上限。
  evidence: `step-04-review.md:27` 只写「Conduct a review of CONTENT.」，`CONTENT` 到末尾才以
    `CONTENT:\n{diff_output}` 出现（同目录 `review-prompts/edge-case-hunter.md`、`verification-gap.md`
    用另一措辞）；「If the content is empty, stop and say so」只约束子代理，父层仍无条件启动 3 个 reviewer；
    diff 体量与分片无任何约定（对照 2026-09-12 已交付的 shell 逐通道 512 KiB 上限）。

- source_spec: `.claude/skills/bmad-build/step-04-review.md`（渲染件 `_bmad/render/bmad-build/heagent-50877a51e192/aeca6e838f8ddd95e529/step-04-review.md`）
  summary: 三个 review 层对产出格式没有统一契约，Classify 阶段只能吞异构输入。
  evidence: `step-04-review.md:27-32` 要求 Blind Hunter 输出「Markdown 列表、无 severity/priority」，
    而 edge-case-hunter 与 verification-gap 两层未规定格式；下游 `### Classify` 需按 claim/action 自行归并。

- source_spec: `_bmad-output/deferred-work.md`（本台账自身）
  summary: deferred 台账存在三处路径漂移，且全仓没有任何 reader，条目会静默积压。
  evidence: 模板一律指向 `{.implementation_artifacts}/deferred-work.md`（= 
    `_bmad-output/implementation-artifacts/deferred-work.md`，当前不存在）；历史台账在本文件；
    goal 流程又落在 `_he-output/goals/project-a/step-07-implement-story/epic-e1/deferred-work.md`
    （该文件自述「路径变更，格式与语义不变」）。`git grep deferred-work` 只命中注释，无读写代码。

- source_spec: `.claude/skills/bmad-build/step-04-review.md`（渲染件 `_bmad/render/bmad-build/heagent-50877a51e192/aeca6e838f8ddd95e529/step-04-review.md`）
  summary: 「无 subagent 可用 → 写 implementation-artifacts 再 HALT」的降级路径在 HeAgent 侧没有任何实现。
  evidence: 模板末段要求逐层写出「替换占位符后的子提示词」并 HALT 请人另开会话执行；HeAgent 侧只有
    `task_parallel`/`task_delegate` 工具，无能力探测、无该降级分支的代码或 CLI 提示。

- source_spec: `src/heagent/cli_display.py`（2026-09-12 内容审查，无对应 spec）
  summary: 进度公告只写 stderr、不进日志文件，事故后无法从日志重建「谁跑了哪些层」。
  evidence: `_announce_start/_announce_end` 用 `click.echo(..., err=True)`；`cli.py:78` 另有一个
    `logging.StreamHandler(sys.stderr)`，因此把公告改成 logger 会在 stderr 重复打印。正解是把
    子代理的 kind/role/workflow_step 写进 engine `run_started` 的 details（当前只有 `session_id`）。
    2026-09-12 已先在公告里加运行 id（`▶ 启动 [name#runid]`）以便与 `run_started` 行对齐。

- source_spec: `src/heagent/config.py`（`goal_max_iterations` 默认 20）
  summary: `/goal` 单步与并行 Story 子代理共用 20 轮上限，原子大 Story 会撞上限后整批失败。
  evidence: 2026-09-12 11:52:30 `engine event=run_failed ... error='Exceeded 20 iterations without final
    answer'`（logs/heagent-20260912-114357.log），该 run 属 step 07 并行批次；`config.py` 只有全局
    `goal_max_iterations`，无按步骤/Story 规模分档的入口。
- source_spec: `.claude/skills/bmad-build/customize.toml`（渲染件 `_bmad/render/bmad-build/heagent-50877a51e192/fbd4ca336b2e98e5f87b/step-04-review.md`）
  summary: 收口（2026-09-12）——review 层的 `CONTENT` 定义、空 diff 前置门禁、大体量分片与统一输出契约已直接写入模板。
  evidence: 提示词真源是 `[[workflow.review_layers]]` 的 `instruction`（`step-04-review.md` 只含
    `{workflow.review_layers}` 占位符，渲染时展开）。已在 `.heagent`（运行时）/`.claude`（git 跟踪）/`.agents`
    三份逐字节一致的副本中补：CONTENT = 自 baseline commit 起的完整 diff；diff 为空时父层不启动任何 reviewer
    并 HALT；超一次读不完则按文件/hunk 分片并列出未覆盖切片、禁止静默截断；每条发现须带 `file:line`/命令/原文
    证据与具体改法（两个「读文件式」层同步加 grounding+slicing 要求）。已重渲染并核对渲染件含新文本
    （`step-04-review.md:21`、`:33-34`、`:46`、`:60`）。

- source_spec: `_bmad-output/deferred-work.md`（本台账自身）
  summary: 仍开放——台账三处路径漂移与「无 reader」未收口；本条只为记录 2026-09-12 的进展。
  evidence: 模板仍指向不存在的 `_bmad-output/implementation-artifacts/deferred-work.md`；`src/` 依旧没有任何
    reader；本轮新增 6 条登记后总量增长，说明积压是真的。
- source_spec: `_bmad-output/implementation-artifacts/deferred-work.md`（本台账自身）
  summary: 收口（2026-09-12）——台账路径漂移与「无 reader」、进度公告不进日志、委派不可用时无降级提示，三项均已修。
  evidence: 台账已 `git mv` 到模板约定路径（旧 `_bmad-output/deferred-work.md` 不再存在），并新增 reader
    `/deferred`（`cli_display.show_deferred_work`：列出 canonical + legacy + goal 内 Epic 级台账的条目数与
    最新条目）。`agent/loop.py` 的 `run_started` 事件现在带 `kind/role/workflow_step/workflow_story/goal_id/
    goal_kind`（`_delegation_details`），日志可重建「哪个 agent/步骤在何时跑」，无需再依赖 stderr 公告。
    `tools/builtins/subagent.py` 的「not configured」与 depth-limit 两类拒绝都追加了 bmad 模板要求的降级路径
    （把子提示词逐字写入 implementation-artifacts 后 HALT）。
