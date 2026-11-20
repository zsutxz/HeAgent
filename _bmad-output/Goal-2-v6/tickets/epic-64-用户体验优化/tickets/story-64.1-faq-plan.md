---
title: 'Story 64.1 编写 FAQ 文档'
type: feature
ticket: 1
created: '2026-11-18'
status: done
baseline_revision: '198b2aa6a4af9bbdd7e6483f385db65a130de12c'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: false
context:
  - 'README.md'
  - 'docs/README.md'
  - '.env.example'
  - 'mkdocs.yml'
---

## Intent

**Problem:** 票面要求 `docs/faq.md` 收录 ≥20 个常见问题及解决方案。当前 `docs/` 只有
`frame.md` / `design.md` / `testing.md` / `sandbox.md` / `goal-workflow.md`，全部是**架构与机制
叙述**，没有面向使用者的问答式入口；`README.md` 是线性快速开始，遇到具体报错时无可跳转页。

**Verify 拆解：**
- 「≥20 个常见问题」→ 实际给 30 条，按**配置 / 使用 / 故障排查**三栏分类；
- 「解决方案」→ 每条含可执行命令或配置键，不写「请检查配置」这类空话；
- 「包含代码示例与命令」→ 配置类给 dotenv 片段，使用类给 CLI 命令，排查类给诊断命令 + 期望输出。

**Approach:** 新增 `docs/faq.md`，内容全部从 `README.md`、`.env.example`、`docs/frame.md`
（§4.17/4.19）、`docs/sandbox.md` 提炼，**不新造机制**；同步登记进 `docs/README.md` 索引表与
`mkdocs.yml` nav，避免 strict 构建的「页面不在 nav」告警。

## Boundaries & Constraints

**Always:**
- 每条问题只在**一个**栏目出现，不复制粘贴换措辞凑条数。
- 所有命令与配置键必须与当前代码/`.env.example` 一致；写不出准确答案的条目不写。
- 与安全相关的答案必须与 `docs/frame.md` §4.19「安全口径（canonical）」一致：三层非边界、
  OS 级沙箱兜底、本地/对外两模式、端点可见性。
- 中文正文 + 反引号包标识符；问题用二级/三级标题，便于 anchor 跳转。

**Never:**
- 不新增 `docs/` 以外的目录；不写 `docs/decisions/` 一类新结构。
- 不描述尚未实现的能力（`heagent doctor`、`heagent cron status`、`/help <command>` 在本票
  时点**尚不存在**，属 Epic 64 后续票，FAQ 不提前宣告）。
- 不把历史叙述（端口从 8766→9001→9901→9201 的沿革）写进 FAQ 主体；FAQ 只讲当前值。

## Code Map

- `docs/faq.md` — 新建。三栏 + 30 条问答。
- `docs/README.md` — 「当前事实」表的「开发」行与条目列表需补 FAQ 入口。
- `mkdocs.yml` — `nav:` 列表补 `常见问题: faq.md`（strict 构建口径）。
- 事实源（只读）：`README.md`（命令表 / 选项表 / HTTP/WS 两模式 / 配置与运行时数据）、
  `.env.example`（配置键与默认值）、`docs/frame.md` §4.17/4.19（端口、模式、安全口径）、
  `docs/sandbox.md`（四档后端与前提）、`src/heagent/cli/console.py`（子命令：run/replay/init/gui/http-server）、
  `src/heagent/cli/interactive.py:642-670`（斜杠命令注册表）、
  `src/heagent/providers/composition.py:130-235`（provider 条目名与构建顺序、「No API key configured」
  报错原文）、`src/heagent/config/__init__.py`（`ROUTING_POOL_ENTRIES` / `http_enabled` 等字段默认值）。

## Tasks & Acceptance

**Execution:**
- [ ] `docs/faq.md` — 新建三栏 30 条问答（分类与配额见下）— 票面主体
- [ ] `docs/README.md` — 索引表与条目列表补 FAQ 一行 — 让 FAQ 可被发现（verify 的「分类」可核）
- [ ] `mkdocs.yml` — nav 补 `常见问题: faq.md` — strict 构建一致性

**FAQ 分类与配额（31 条）：**
- 配置（11）：凭据最小集与优先级；本地 Ollama；切换 provider；默认 provider 编号来源；
  `/model` 与 `--model` 分工；路由池 `ROUTING_POOLS` 与「not supported by any configured account」判读；
  配置文件分层（env > 项目 `.env` > `~/.heagent/setting.md` > 默认）；关掉网页/WS 入口；
  上下文窗口与 `MAX_CONTEXT_TOKENS`；沙箱后端四档；WS 对外模式的 token/TLS 与端点可见性。
- 使用（9）：单次 vs 交互 vs 子命令；斜杠命令清单；自定义斜杠命令；技能/角色存放位置；
  会话续跑（`--continue` / `--resume`）；`/goal` 命令族与产物目录；MCP 接入（`.mcp.json`）；
  Python API 嵌入；网页控制台与端口。
- 故障排查（11）：`heagent` 命令找不到；无可用 provider / 认证失败；端口被占用（顺延日志）；
  容器内 `dubious ownership`；工具路径被拒（`/workspace` 绝对路径）；WS 403/1008 与
  token 来源（含 `/api/notifications/ws` 未注册时的裸 403）；`WS_HOST=0.0.0.0` 触发对外模式告警；docker 后端降级；日志里查不到某 provider
  的调用记录（`provider_call_completed` 与路由的归因口径）；上下文压缩/窗口重置何时触发；
  技能列表显示 stale 但不应归档。

**Acceptance Criteria:**
- Given 打开 `docs/faq.md`，when 数二级/三级问答标题，then 数量 ≥ 20（实为 31），且分布在
  配置（11）/ 使用（9）/ 故障排查（11）三个二级栏下。
- Given 任一条目，when 阅读答案，then 能看到至少一条可执行命令或可直接粘贴的配置片段。
- Given FAQ 中出现的每个配置键，when 与 `.env.example` 或 `docs/frame.md` §4.19 对照，
  then 键名与默认值一致，无臆造键。
- Given 仓库根，when 运行 `mkdocs build --strict`，then 构建成功且无「faq.md 不在 nav」类告警。
- Given 仓库根，when 运行 `pytest tests/test_release_workflow_contract.py -q`，then 通过
  （FAQ 不触碰发版契约，作为回归护栏）。

## Implementation Notes

- `docs/faq.md` 31 条（配置 11 / 使用 9 / 排查 11），每条至少一个 fenced 代码块，`awk` 校验无遗漏。
- `docs/README.md`：索引表加「使用问答」行 + 条目列表加一行；`mkdocs.yml` nav 加 `常见问题: faq.md`。
  `.heagent/tmp/py311-venv-linux/bin/python -m mkdocs build --strict` 通过（0.9s，无告警）。
- 事实纠偏（**超出原计划的必要修正**）：`.env.example:22-23` 的「条目名 / 构建顺序」注释与
  `providers/composition.py:130-215` 实际插入序不符（写成 `kimi / glm / ollama / openai / gpt / anthropic`，
  实际条目名是 `deepseek / claude / openai / kimi / glm / ollama`）。FAQ 两处都按代码真值写，
  同步修 `.env.example` 这两行注释——否则 FAQ 与该文件互相矛盾。
- 已知遗留（不在本票范围，未改）：`.env.example:52-53/65/69` 仍把 Responses 条目称作 `gpt`
  （实际条目名 `openai`）、`DEFAULT_MODEL` 注释仍提「OpenAI Chat Completions 条目」（该条目已删）。
- 9p 挂载上所有文件权限都是 `0777`，`chmod` 返回 `EPERM` ⇒ 新文件在 diff 里显示 `new file mode 100755`。
  提交时用 `git add --chmod=-x docs/faq.md` 把索引 mode 钉成 `100644`。

## Plan Change Log

- 2026-11-18 评审 loopback：把配额改回实际值 31（配置 11 / 使用 9 / 排查 11，原写 30/配置 10 与实际
  条目表不符）；排查项「WS 401/403/1008」改为「403/1008」——WS 认证失败回 1008、握手前 401 不出现，
  凭空写 401 会让读者去找不存在的状态码；事实源补 `providers/composition.py` 与 `config/__init__.py`。
  KEEP：三栏分类、每条给命令、不提前宣告未实现能力的立场保持不变。

## Review Triage Log

- 2026-11-18 quick lens（1 个 reviewer，23 findings）：patch 15 / false 7 / maybe-false 1。
- patch：配置条数与 plan 不符；路由池缺「not supported by any configured account」判读；4 条问答缺
  命令块（编号来源 / 技能位置 / `WS_HOST=0.0.0.0` / 技能 stale）；provider 条目顺序两条自相矛盾；
  WS 403/1008 把 `0.0.0.0` 归进「本地模式」；漏 `/api/notifications/ws` 未注册的裸 403；
  沙箱条抹掉「OS 级沙箱兜底」；WS 对外条缺端点可见性；对外示例推荐 `WS_HOST=0.0.0.0` 与排查条指引相反；
  单次/交互条未标「代码默认 vs 项目 `.env`」语境；plan 的 401 与事实源缺口。
- false（附证据）：`/goal doctor` 真实存在（`cli/goal/commands.py:713` 帮助文本、`_goal_declarative_doctor`），
  plan 禁的是独立 `heagent doctor` 命令；`~/.heagent/.env` 层已由 `setting.md` 取代
  （`cli/init.py:88-95` 自动迁移）；默认值断言均出自 `.env.example`（本身即计划事实源）；
  「网络入口不连接 MCP」出自 `README.md`（同属事实源）；`--model deepseek-v4-pro` 与 `--port 9100`
  分别在 `.env.example:64` 与 `README.md` 原文。
- maybe-false：`docs/faq.md` 的 `100755` 文件模式——9p 文件系统不支持 `chmod`（`EPERM`），
  只能在提交时 `git add --chmod=-x`。

## Design Notes

FAQ 与既有文档的分工：`README.md` 是「第一次跑起来」的线性路径，`docs/frame.md` 是「为什么
这样实现」的架构权威，FAQ 补的是第三类需求——**已经踩到了坑、想立刻找到答案**。因此 FAQ 每条
都以问句开头、答案首句给结论，命令放在结论之后，不展开原理（原理链接到既有文档）。

## Verification

**Commands:**
- `pytest tests/test_release_workflow_contract.py -q` -- expected: pass
- `ruff check src tests scripts` -- expected: pass（不改代码，作为无副作用护栏）
- `.heagent/tmp/py311-venv-linux/bin/python -m mkdocs build --strict` -- expected: 构建成功
- `grep -c '^### \|^## ' docs/faq.md` -- expected: 问答条目计数 ≥ 30
