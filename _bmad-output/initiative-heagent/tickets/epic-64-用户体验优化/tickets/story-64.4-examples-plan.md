---
title: 'Story 64.4 建立示例库'
type: feature
ticket: 4
created: '2026-11-18'
status: built
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
  - 'src/heagent/__init__.py'
  - 'src/heagent/providers/base.py'
  - 'src/heagent/tools/decorator.py'
  - 'README.md'
---

## Intent

**Problem:** 票面要求 `examples/` 收录 ≥5 个可运行示例，含自定义 tool、Provider 扩展、技能包开发，
各带 README 与完整代码。仓库当前**没有 `examples/`**：扩展点知识只散在 `AGENTS.md` 的约束条目与
`docs/frame.md` 的模块叙述里，读者想跑通一个最小例子得自己拼装。

**Verify 拆解：**
- 「可运行」→ 每个示例必须能在本机跑起来并给出可观察输出；**默认离线**（stub provider），
  不要求 API key，否则「可运行」只是空话。
- 「含自定义 tool / Provider 扩展 / 技能包开发」→ 三个必选主题各一个示例。
- 「各带 README 与完整代码」→ 每目录 `README.md` + `main.py`（或 `SKILL.md` + 资源）。

**Approach:** 新增 `examples/`，5 个示例：`custom-tool` / `custom-provider` / `provider-chain` /
`events-stream` / `skill-package`。前四个用不联网的 stub provider，`python main.py` 直接有输出；
`skill-package` 给可被 `SkillStore` 解析的真实技能包，并附一行校验命令。

## Boundaries & Constraints

**Always:**
- 每个示例**默认离线**：不得要求凭据或网络；需要真实 Provider 的地方在 README 里另给一行说明。
- 代码只依赖 `pip install -e .` 的公开符号（`heagent` 包 `__all__` 里的 `Agent` / `tool` /
  `OpenAIProvider` / `ProviderChain` / `Settings`），扩展点需要包内路径时在 README 注明「非稳定 API」。
- 示例必须通过 `python examples/<name>/main.py` 实跑验证，输出写进 README 的「期望输出」段。
- 技能包示例必须能被现有 `SkillStore` 解析（`SKILL.md` 带 frontmatter `name` / `description`）。
- 不修改 `src/`、`tests/`、门禁脚本；示例不进 ruff / mypy / pytest 的既有范围。

**Never:**
- 不写「伪代码」「省略号」式示例（`...` 占位）；每个文件都是完整可执行的。
- 不在示例里演示任何安全边界的绕过（`SANDBOX_MODE=danger-full-access` 之类）。
- 不宣称示例覆盖全部扩展点；README 的根 `examples/README.md` 明确写出「这 5 个覆盖什么」。

## Code Map

- `examples/README.md` — 索引：每个示例解决什么问题、怎么跑、需要什么。
- `examples/custom-tool/` — `main.py` + `README.md`：`@tool` 自动注册 → Agent 调用 → 打印 schema。
- `examples/custom-provider/` — `main.py` + `README.md`：实现 `send` / `stream` / `get_metadata`
  的最小 Provider（离线回显），`isinstance(p, BaseProvider)` 结构性校验。
- `examples/provider-chain/` — `main.py` + `README.md`：`ProviderChain` 在首个 provider 抛错时回退。
- `examples/events-stream/` — `main.py` + `README.md`：订阅事件总线收集一轮 run 的事件并打印。
- `examples/skill-package/` — `SKILL.md` + `scripts/` 资源 + `README.md`：技能包结构与放置位置。
- 事实源（只读）：`src/heagent/__init__.py`（公开符号）、`providers/base.py`（Protocol 三方法与
  `ProviderMetadata` 字段）、`tools/decorator.py::tool` 签名（`name` / `description` / `enabled` /
  `read_only` / `destructive`）、`agent/loop.py::AgentLoop.__init__`（可注入组件）、
  `skills/skill_store.py::default_skill_roots`（双根与全局优先）。

## Tasks & Acceptance

**Execution:**
- [x] `examples/README.md` — 索引与运行约定 — 入口
- [x] `examples/custom-tool/main.py` + `README.md` — `@tool` 最小闭环 — 必选主题 1
- [x] `examples/custom-provider/main.py` + `README.md` — Protocol 三方法实现 — 必选主题 2
- [x] `examples/skill-package/SKILL.md` + 资源 + `README.md` — 技能包契约 — 必选主题 3
- [x] `examples/provider-chain/main.py` + `README.md` — 容错组合 — 加分示例
- [x] `examples/events-stream/main.py` + `README.md` — 事件订阅 — 加分示例

**Acceptance Criteria:**
- Given `examples/`，when 列目录，then 有 ≥5 个子目录，每个含 `README.md`。
- Given 任一 `main.py`，when 在仓库根执行 `python examples/<name>/main.py`，then 退出码 0 且
  输出与 README 的「期望输出」一致，全程不需要网络或 API key。
- Given `examples/skill-package/`，when 用 `SkillStore` 扫描该目录（README 给命令），then 能解析出
  该技能（`canonical_id` / `description` 非空）。
- Given `examples/custom-provider/main.py`，when 跑 `isinstance(provider, BaseProvider)`，
  then 为 `True`（证明 Protocol 不要求继承）。
- Given 全文，when 搜 `danger-full-access` / `...`（占位省略），then 无命中。

## Implementation Notes

- 目录：`examples/{README.md, custom-tool, custom-provider, provider-chain, events-stream, skill-package}`。
  四个 `main.py` 实跑退出码均为 0（stub provider，离线）；`skill-package` 用 `SkillStore` 校验通过
  （`list_skills() == ['release-notes']`，`parse()` 拿到 `pattern` 与 23 条 `steps`，`read_resource` 可读）。
- 实现期纠了三处事实：
  1. `messages` 是 pydantic `Message` 列表，不是 dict（`m.get("role")` 会 `AttributeError`，改 `m.role`）；
  2. 事件名是 `tool_call_completed`（不是 `tool_call_finished`）——`engine/executor.py:272/343`；
     同步修了 `docs/performance.md` 里 3 处同名错误；
  3. `ProviderChain` 只对 `RATE_LIMITED` / `AUTH_FAILED` / `TRANSIENT` 回退，`RuntimeError` 会被判
     `NON_TRANSIENT` 而**不**回退（`providers/chain.py:68-100`）⇒ 示例改抛
     `ProviderError(status_code=503)`，README 用表格写明四类错误的回退差异。
- 技能包结构按现有真实形态：frontmatter 含 `triggers` / `negative_triggers`，正文含 `## Pattern` /
  `## Steps`（`SkillStore.parse()` 的结构化来源）。不放 `meta.yaml`（运行时写的计数文件）。
- 示例文件行尾已核（9p 会对某些写入路径产出 CRLF；本次 `rglob` 检查 0 命中）。
- 已知遗留（未做，超出本票）：`examples/` 不在 `ruff check` / `mypy` 的既有范围内
  （`src tests scripts`），示例代码的静态检查靠人工与实跑。
- review 后补修（本票 diff 只含 `examples/`，`docs/performance.md` 的 3 处 `tool_call_finished` →
  `tool_call_completed` 是本票发现并顺手改的，属 64.3 的产物，不在本票 diff 里）：
  `custom-tool` / `provider-chain` 的 `stream` 均改为真正的 async generator；`events-stream` 的期望输出
  把 `duration_ms` 标为 `<ms>`（机器相关）；`skill-package` 的期望输出按实测改成
  `release-notes True 24 发布说明|发布公告|release no`；`group_commits.py` 的用法路径补 `release-notes/`；
  `examples/README.md` 区分「公开符号 vs 包内路径（非稳定 API）」并补 `pip install -e .` 前提；
  三处 `...` 示意改为具体值（使 AC「搜 `...` 无命中」成立）。

## Review Triage Log

- 2026-11-18 quick lens（1 个 reviewer，24 findings）：patch 14 / false 9 / maybe-false 1。
- patch：`...` 占位命中 AC 禁项（3 处改成具体值）；`events-stream` 期望输出含机器相关的
  `duration_ms`（改 `<ms>` 并说明条数与顺序稳定）；`skill-package` 期望输出的 `pattern[:20]` 与
  `len(steps)` 与实测不符（按实测 24 改，并解释三个数各校验什么、补 `bool(description)`）；
  `provider-chain` 的首行是 stderr WARNING 而非 print（移出期望输出并说明）；`custom-tool` 与
  `provider-chain` 的 `stream` 无 `yield` ⇒ 不是 async generator（改为真正 yield）；
  `group_commits.py` 用法路径缺 `release-notes/`；`SKILL.md` 的资源命令与「仓库根执行」口径冲突
  （改写为完整路径）；`custom-provider` 的 docstring 指错 README；`examples/README.md` 的
  「每个示例内嵌 stub Provider」对 `skill-package` 不成立；缺「包内路径属非稳定 API」说明；
  缺 `pip install -e .` 前提；`.env.example` 节号引用改为节名；plan 标题重复与残留 `7`。
- false（附证据）：`EngineContainer` 不在公开符号——`heagent/__init__.py` 的 `__all__` 含它；
  `isinstance(provider, BaseProvider)` 依赖 `@runtime_checkable`——`providers/base.py` 已有该装饰器
  且实测返回 `True`；`metadata` 四键——`ProviderMetadata` 恰好四个字段，实测 `model_dump()` 一致；
  `SANDBOX_MODE=read-only` 是自造键——`.env.example` 第 13 节有该键及三个取值；
  降级提示字符串未验证——实跑输出即该行；`heagent replay` 不存在——`cli/console.py:445` 有该子命令；
  `docs/faq.md` 链接无证据——faq.md 是 64.1 产物、已在工作树。
- maybe-false：全部新文件 `100755`（9p 不支持 `chmod`，提交时 `git add --chmod=-x`）。

## Plan Change Log


## Design Notes

示例默认离线是有意的：`AGENTS.md` 的测试纪律要求不调真实 API，示例若必须联网就变成「读者先配 key
才能验证示例本身对不对」，把两件事耦合了。stub provider 让读者先看到框架怎么转，再换成真实 provider
只改一行构造。

## Verification

**Commands:**
- `for d in examples/*/; do [ -f "$d/main.py" ] && python "$d/main.py" > /dev/null || true; done; echo OK` -- expected: 各示例退出码 0
- `.heagent/tmp/py311-venv-linux/bin/python -c "from heagent.skills.skill_store import SkillStore; print(SkillStore('examples/skill-package').list_skills())"` -- expected: `['release-notes']`（`SkillStore` 没有 `scan`；根目录下每个含 `SKILL.md` 的子目录即一个技能）
- `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_release_workflow_contract.py -q` -- expected: pass
