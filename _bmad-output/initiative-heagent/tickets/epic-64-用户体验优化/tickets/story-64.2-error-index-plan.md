---
title: 'Story 64.2 建立错误信息解释索引'
type: feature
ticket: 2
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
  - 'src/heagent/network/http_protocol.py'
  - 'src/heagent/network/http_server/pipeline.py'
  - 'src/heagent/pub/exceptions.py'
  - 'tests/fixtures/contract_baselines/transport_errors.json'
  - 'docs/README.md'
  - 'mkdocs.yml'
---

## Intent

**Problem:** 票面要求 `docs/errors.md` 错误信息解释索引，每条含错误码/描述/原因/方案、可按码或
关键词检索。当前 `docs/` 无此页；错误面分散在三处且**异构**——传输层有封闭码集合
（`network/http_protocol.py::HttpErrorCode`，35 码，含 5 个「无静态 HTTP 出口」的码）、框架层只有
9 个无码异常类（`pub/exceptions.py`）、CLI/启动期是自由文本（如 `Error: No API key configured.`）。
统一错误码体系是 Epic 69.3（planned），本票不重做它。

**Verify 拆解：**
- 「覆盖 >80% 用户可见错误」→ 把「用户可见错误」界定为**三个可枚举集合的并集**，并写明该口径：
  传输层 35 码全覆盖 + 框架 9 类全覆盖 + CLI/启动期 12 条常见错误；合计 56 条，三条链路各自的
  覆盖率为 100%（口径写在页首，便于日后核对）。
- 「每条含错误码/描述/原因/方案」→ 码表四列：`code` / 描述 / 原因 / 方案（HTTP 状态作附加列）。
- 「可按码或关键词检索」→ 除三张主表外附一张「看到这句话 → 找哪条」的关键词跳转表。

**Approach:** 新增 `docs/errors.md`；内容全部由代码事实生成或核对，不臆造码。传输层的状态码取
`tests/fixtures/contract_baselines/transport_errors.json`（脚本从调用点静态抽取的权威快照），
5 个 `status: null` 的码按实际行为写「无固定 HTTP 状态：…」，不当成缺数据。

## Boundaries & Constraints

**Always:**
- 每个码必须能在代码里找到定义点（`http_protocol.py:57-113`）或调用点，不得新增码。
- 契约快照标 `unmapped` 的 5 码（`agent_error` / `empty_prompt` / `origin_forbidden` /
  `shutting_down` / `timeout`）要如实区分：`empty_prompt` 与 `origin_forbidden` 有确定出口
  （400 / 403），`shutting_down` 走 WS 错误帧 + `1001`，`agent_error` 与 `timeout` **当前无发送点**
  ——后者必须写明「保留码，当前无发送点」，不能让读者以为线上会遇到。
- 「方案」必须是可执行动作（改哪个配置键、看哪条日志、调哪个上限），不是「请检查配置」。
- 与 `docs/frame.md` §4.17 的 35 码口径一致（同一封闭集合、同一分组），不另立码表。

**Never:**
- 不把 Epic 69.3 的「统一错误码体系」当成已存在；页首必须写明 CLI/框架层**暂无稳定码**，
  待 69.3 落地后补码列。
- 不复制 `frame.md` 4.17 的整段正文；本页只做「码 → 修复动作」的索引，机制回指。
- 不新建 `docs/` 之外的目录。

## Code Map

- `docs/errors.md` — 新建：三张主表 + 关键词跳转表 + 口径声明。
- `docs/README.md` — 「当前事实」表与条目列表补「错误索引」入口。
- `mkdocs.yml` — `nav:` 补 `错误索引: errors.md`。
- 事实源（只读）：`src/heagent/network/http_protocol.py:57-113`（35 码定义与分组注释）、
  `src/heagent/network/http_server/pipeline.py:109-156`（码 → HTTP 状态映射、未列出码默认 400、
  未知码降级 500）、`src/heagent/network/http_server/middleware.py:96-101`（`origin_forbidden` → 403）、
  `src/heagent/network/http_server/service.py:151-157`（`run_conflict` 三条消息）、
  `src/heagent/cli/http_console.py`（`ConsoleOperationError` 的码与文案）、
  `src/heagent/pub/exceptions.py`（9 个异常类）、`src/heagent/providers/composition.py:206-230`
  （两条启动期致命配置错误原文）、`tests/fixtures/contract_baselines/transport_errors.json`（状态快照）。

## Tasks & Acceptance

**Execution:**
- [ ] `docs/errors.md` — 新建；口径声明 + 传输层 35 码表 + 框架 9 类表 + CLI 12 条 + 关键词跳转表 — 票面主体
- [ ] `docs/README.md` — 索引表与条目列表补一行 — 可发现性
- [ ] `mkdocs.yml` — nav 补 `错误索引: errors.md` — strict 构建一致性

**Acceptance Criteria:**
- Given 打开 `docs/errors.md`，when 数传输层码行，then 恰为 35 行，且与
  `HttpErrorCode` 枚举逐字相同（可用一行 Python 比对）。
- Given 任一码行，when 阅读单元格，then 描述 / 原因 / 方案三列都非空，且方案含具体键名或命令。
- Given 快照里 `status: null` 的 5 个码，when 看它们的「HTTP 状态」列，then 不出现编造的数字，
  而是写明固定状态或「无发送点」。
- Given 页内的关键词跳转表，when 用 CLI 真实报错片段（如 `No API key configured`）搜索，then
  能定位到对应条目。
- Given 仓库根，when 运行 `mkdocs build --strict`，then 构建成功无告警。

## Implementation Notes

- `docs/errors.md`：三张主表（传输层 35 / 框架 9 / CLI 12）+ 关键词跳转表 + 覆盖口径声明（合计 56，
  三条链路各 100%）。码行用枚举比对脚本核过：传输出层 35 个值全部有且仅有一行，无多余码。
- 分组按 `HttpErrorCode` docstring 的原文分组（输入 / 项目与会话 / 原生选择 / 运行 / 资源 / 边界 /
  服务）排表；枚举里 `write_disabled` / `field_not_writable` / `invalid_value` / `config_conflict` /
  `config_write_failed` / `confirm_required` / `loopback_required` 七个码**原文未归组**，文档单列
  「配置写入与确认类」并在表前注明，不假装它们是枚举分组的一部分。
- `docs/README.md` 索引表 + 条目列表各补一行；`mkdocs.yml` nav 补 `错误索引: errors.md`；
  `mkdocs build --strict` 通过，`tests/test_release_workflow_contract.py` 9 passed / 1 skipped。
- 语义纠偏（review 后核对源码才发现）：`project_not_removable` 的真实成因是「**默认项目**不能移除」
  （`pub/projects.py:206`），不是「仍被引用或路径不可达」；`project_limit_reached` 是注册表条目满
  （`pub/projects.py:175`），与 `HTTP_MAX_*` 限额无关。
- `docs/errors.md` 与 `docs/faq.md` 同为 9p 新品 ⇒ 提交时同样要 `git add --chmod=-x`。

## Plan Change Log

## Review Triage Log

- 2026-11-18 quick lens（1 个 reviewer，12 findings）：patch 9 / false 2 / maybe-false 1。
- patch：页首缺覆盖口径（补 35+9+12=56 与三链路 100%）；CLI 表多出一行行为描述（删掉，
  改为表后的说明句，条数回到 12）；分组名与枚举 docstring 不一致（按原文七组重排，未归组七码单列）；
  「HTTP」列用 `—` 占位（改为「无固定状态」+ 描述列写明 WS 错误帧 / 无发送点）；
  `request_too_large` 原因与括号解释互相否定（重写）；`project_limit_reached` 用通配符 `HTTP_MAX_*`
  （改为真实键）；多行方案缺键名或命令（补 `ls -d` / `logs/heagent-*.log` / `confirm=true` /
  `HTTP_CONSOLE_PROJECTS_FILE`）；关停语义在 `run_conflict` 与 `shutting_down` 两处并列无边界
  （`run_conflict` 注明 `message` 为 `server is shutting down`，`shutting_down` 注明只走 WS 帧）。
- false：reviewer 报「diff 引用了不存在的 `docs/faq.md`」——`faq.md` 是 64.1 的产物、已在工作树中
  （`ls docs/faq.md` 存在，`mkdocs build --strict` 实测通过），diff 范围只含本票文件故未出现它的 hunk；
  及其衍生条「README 提前宣告不存在的文档」，同一误判。
- maybe-false：`new file mode 100755` —— 9p 不支持 `chmod`，提交时用 `git add --chmod=-x`。

## Design Notes

三层同页而非三页：使用者手里只有**一段错误文本**，不知道它属于传输层还是框架层——按层分页会逼他
先做归因。所以页首给「先认形态」的两句话判别（`{"error":{"code":…}}` 信封 = 传输层；中文/英文
自由文本 = CLI 层），再按层展开。

## Verification

**Commands:**
- `.heagent/tmp/py311-venv-linux/bin/python -c "from heagent.network.http_protocol import HttpErrorCode as C; print(len(list(C)))"` -- expected: `35`
- `grep -c '^| \`[a-z_]*\`' docs/errors.md` -- expected: ≥ 35（码表行数）
- `.heagent/tmp/py311-venv-linux/bin/python -m mkdocs build --strict` -- expected: 构建成功
- `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_release_workflow_contract.py -q` -- expected: pass
