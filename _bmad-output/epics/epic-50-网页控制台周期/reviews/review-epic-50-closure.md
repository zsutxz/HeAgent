---
epic: E50（网页控制台）
scope: Epic 50 全量收口（Story 50-1 / 50-2 / 50-3 / 50-4 / 50-5 / 50-6 / 50-7 全部 7 条）
diff_range: 33adba0..1ca29cf（含第一轮 33adba0..3ff9d8d 与后续 50-5/50-6/50-7 增量）
review_loop_iteration: 0
reviewer: code_review 契约（三镜头 + 定级 + 分诊）
first_round: reviews/review-epic-50-implementation.md（增量轮，覆盖 50-1..50-4）
verdict: 放行（Epic 50 收口通过；3 条 low 级 deferred 与 2 条 blocked 待人裁决不阻塞收口）
created: '2026-09-24'
---

# Epic 50 · 全量收口评审（第二轮）

按 `code_review` 契约执行：**对抗式 / 边界追踪 / 验证缺口** 三镜头各自独立成段；定级前逐条打开源码读
调用点与守卫（不只看 diff hunk）；Critical / `patch` 就地最小修复并重跑受影响测试 + 负向验证。

**与第一轮的关系**：第一轮（`review-epic-50-implementation.md`）是**增量轮**，只覆盖 50-1…50-4，并在结论里
写明「Epic 50 收口**不放行**：还差 50-5/50-6/50-7」。本轮是**收口轮**，覆盖 Epic 50 **全部 7 条 story**，
并逐条复核第一轮的发现（见「第一轮发现复核」）。两文件并存：前者记录增量轮的发现与修复，本文件给出收口裁决。

## 评审范围

- **Epic**：`_bmad-output/epics/epic-50-网页控制台周期/`（脊柱 + 7 份 story + 三份验收/评审产物）。
- **覆盖的 story**：50-1（工作区一等化）、50-2（项目注册表）、50-3（会话持久化 / 会话 API / 项目内运行）、
  50-4（配置来源求解与只读面板）、50-5（配置写入通道）、50-6（控制台 UI + 浏览器验收）、50-7（安全收口与文档）。
- **diff 范围**：`git diff 33adba0..1ca29cf` —— **75 文件 / +15535 −465**（src 约 7.6k 行、tests 约 6.2k 行、
  产物与文档约 1.7k 行）。
- **本轮重点**：50-5/50-6/50-7 的**新增面**（写入流水线 / 保真写 / 覆盖层面板 / 两栏 UI / 契约与验收），
  并对 50-1..50-4 的面做**回归式复核**（第一轮的修复是否仍在、断言是否仍有效）。
- **执行方式**：三镜头由我逐处读取真实源码 + 亲跑命令；对抗式与边界镜头另用一次性探针直接打真实模块
  （`.heagent/tmp/review50_probe.py`、`review50_errorcodes.py`），不靠读 diff 猜。

### 我实际执行过的命令与结果

| 命令 | 结果 |
|---|---|
| `python -m pytest -q` | **3076 passed / 11 skipped / 18 deselected**（含本轮补的 19 例：1 例真实装配 + 18 例枚举驱动参数） |
| `python -m pytest -q --cov=heagent --cov-fail-under=87` | TOTAL **92%**；`Total coverage: 91.83%`（门限 87%） |
| 逐模块覆盖率（全量测试集） | `envfile.py` **100%**、`workspace.py` **100%**、`config_write.py` **99%**、`config_catalog.py` **98%**、`http_console_protocol.py` 94%、`cli_http.py` **89%**、`context/session.py` **90%**（补证前 85%）、`projects.py` 85% |
| `ruff check src tests` / `ruff format --check src tests` | All checks passed! / 277 files already formatted |
| `mypy src` / `mypy src --platform linux` | 均 `Success: no issues found in 146 source files` |
| `node tests/js/console_acceptance.mjs` | `ACCEPTANCE {"rows":18,"failed":0}`（真浏览器 Chrome 153） |
| `python .heagent/tmp/review50_probe.py` | 11 组边界探针（大小写键 / 锁文件落点 / 重复键 / 空值键 / 目标为目录 / 无等号行 / 裸 CR-LF / 注释行同名键 / 无末行换行追加 / 进程环境） |
| `python .heagent/tmp/review50_errorcodes.py` | `HttpErrorCode` 32 码 ↔ `app.js::ERROR_TEXT` 32 键**完全对齐**（0 缺 0 幽灵） |
| `python .heagent/tmp/mutate_50_review2.py` | 3 组（含 1 组**负对照**）全部符合预期 |

---

## 第一轮发现复核（是否仍成立 / 是否已闭合）

| 第一轮条目 | 本轮复核 | 结论 |
|---|---|---|
| high#1 会话列表 500（畸形消息条目） | 读 `context/session.py` 现状：`SessionUnreadableError` 已覆盖「消息项不合法」；`test_list_metadata_treats_invalid_message_entry_as_unreadable` 在位并通过 | **已闭合** |
| high#2 注册表被一次坏字节清空 | `projects.py` 写侧 `_decode_or_raise` 在位；`test_corrupt_registry_is_read_fail_soft_but_never_overwritten` 通过 | **已闭合** |
| high#3 面板与运行端配置口径不一致 | `cli_http._project_settings()` 显式传 `_env_file=[全局, 项目]`；`test_for_workspace_resolves_settings_from_the_project_env` 通过 | **已闭合** |
| medium 6 条 defer（运行时归因 / 在途工具计龄 / SSE 限额竞态 / 阻塞 I/O / 工具配对证据 / 50-2 数字） | 逐条比对台账：6 条**仍在活动台账**且描述与本轮实测一致，无一条被静默关闭 | **仍成立（已登记）** |
| medium intent_gap 1 条（`enable_cron=False` 仍绑 cron 工具面） | 台账标 `blocked`；代码未变（`cli.py` 仍构造 `cron_store` 并在 `enable_cron=False` 时传给 loop） | **仍成立（blocked）** |
| low 8 条（含文档 4 处、`line_count`、`create_session` 码映射、`path_safety` 接缝、>1MiB 会话读） | 文档 4 处已修且本轮未回退；`line_count` 用 `splitlines()` 在位；`path_safety` / 大文件读**仍在**（已登记） | **已闭合 6 / 仍成立 2** |

---

## 镜头一 · 对抗式（找「缺什么」）

| # | 位置 | 问题 | 证据（亲读 / 亲跑） | 严重度 | 处置 |
|---|---|---|---|---|---|
| 1 | `config_write.py:530-560`（`_verify` + `except ConfigWriteRejection`） | 回读不符时无条件宣称「the project .env **was rolled back** to its previous content」——若**回滚本身也失败**（`persist._restore_bytes` 抛错只 `logger.error`），对客户端的文案就是**假的** | `_verify` 先设 `state.readback_failed` 再抛固定文案；回滚发生在 `persist.atomic_update_bytes` 内部，成败不回流到消息 | low | **defer**（`config_write_failed` 的**用户可见**文案在 UI 侧本就是诚实的「服务端已尝试恢复备份」，且该码不在 JS 的 `DETAIL_CODES`（不显示服务端 message）⇒ 实际只影响直接调 API 的客户端。精确文案需把回滚结果回传，非最小改动） |
| 2 | `persist.py::atomic_update_bytes`（`lock_path = path.with_name(path.name + ".lock")`） | 写项目 `.env` 会在**用户项目根**留下一个 0 字节 `.env.lock`（探针 B 实测：`['.env','.env.lock','.heagent']`）。HeAgent 自己的仓库有 `.gitignore` 条目，但**用户的项目**没有 | 探针 B | low | **defer**（锁文件刻意不删——删除会引入「B 等旧 inode、C 拿新文件加锁成功」的竞态，见 `persist` 注释；挪到状态目录会改变锁的语义。登记后由「是否给写入方加一条 README 提示」决定） |
| 3 | `config_write._apply_locked` | **全部**写入 I/O 在跨进程锁内完成，包括 `validate_candidate`（构造 `Settings` ⇒ 读候选临时文件 + 全局 `.env` + 环境）与备份目录扫描 ⇒ 锁持有时间随文件与环境规模增长 | 读码：`atomic_update_bytes(target, _update, ...)` 内的回调包含候选构造与 `prune_backups` | low | **defer**（失败模式是 fail-closed：并发写最坏得到 `config_write_failed`（锁超时 5s）而非 `config_conflict`，**不会**产生损坏或部分写入。要收窄需「锁外构造 + 锁内复检指纹」的乐观重试，属改造） |
| 4 | `cli_http.py:565-569`（`create_session` 的两个 except） | 分支**不可达**（`session_id = uuid.uuid4().hex` 不可能撞已存在文件；标题边界协议层已挡）⇒ 覆盖率为 0。第一轮报告曾把这处修复记为「覆盖于会话路由用例集」——**该主张不成立** | 逐模块覆盖率（全量集）显示 565-569 未执行；读码确认 `uuid4` 唯一性 | low | **低风险（防御性代码）**：分支本身正确且方向 fail-closed，**不补造用例**（补了也只是对着 unreachable 断言）；在本报告如实纠正第一轮的覆盖主张 |
| 5 | `network/http_server.py` 的写路由面 | 项目**重命名**、四个**会话**写操作、项目内**运行入口**均**无**回环门（登记 / 移除 / 配置写入有） | 读 `_loopback_error` 调用点 + `test_non_loopback_clients_cannot_register_or_remove_projects` 的 docstring | medium | **intent_gap → blocked**（沿用第一轮；两条修法都改变可观察行为，交人裁决） |
| 6 | `network/http_server.py:659/665/690/710` | `deadline_reason` 一经写入永久保留 ⇒ 用户的 `DELETE` 可能被误报 `timed_out` 并吞掉取消 | 沿用第一轮（本轮复核代码未变） | medium | **defer**（已登记） |
| 7 | `network/http_server.py:659` | `tools_in_flight` 永不衰减 ⇒ 一个永不返回的工具让静默判据恒不成立，名额被无界占用 | 沿用第一轮（代码未变） | medium | **defer**（已登记） |
| 8 | `cli_http.py` 的会话/配置读路径 | 唯一事件循环里做同步 I/O（会话列表 / 配置求解 / 注册表列举） | 沿用第一轮（代码未变；50-5 写了一处 `to_thread`，读路径未动） | medium | **defer**（已登记） |
| 9 | `tests/test_http_web_ui.py::TestConsoleApiContract` | **测试名说 every、实际只枚举 14/32 个错误码** ⇒ 「每个码都有文案」这一声称没有自维护判据 | `review50_errorcodes.py`：枚举 32 ↔ JS 32 键完全对齐，但用例只覆盖 14 | medium | **patch 已修**：参数改为由 `HttpErrorCode` 枚举派生（32 条），负向验证见下 |
| 10 | `cli_http.py:764-765`（`_resolve_session` 的 `SessionUnreadableError`） | 「用**损坏会话**起 run」这条**可达**路径零覆盖 ⇒ 若分支失效，会在损坏文件上继续写而无人察觉 | 覆盖率实测该行未执行；读码确认可达（`POST …/runs` + `session_id`） | medium | **patch 已修**：新增真实装配用例（409 `session_unreadable` + 损坏文件字节不变 + 无新会话文件） |
| 11 | `web/app.js::askConfirm` | 第二个确认框到来时直接覆盖 `confirmPending` ⇒ **前一个 promise 永不结算**（那次危险操作既没执行、也不会走到 `await` 之后的代码） | 读码：`confirmPending = { resolve, wantsInput }` 覆盖式赋值；无并发守卫 | low | **patch 已修**（1 行：被顶掉者以「取消」结算）。**如实标注：无可观察差异**（两种写法都不删/不改），修的是「未来任何 `await askConfirm` 之后的代码会静默不执行」的陷阱，故**没有新增断言** |
| 12 | `tests/test_config_write.py::TestAuditRetention` 与 `RESOURCE_CEILINGS` | 上界表 / 审计回收的**取值口径**只由「规则用例」钉（≥10× 默认、完备性） | 复核：`test_the_ceiling_table_is_exactly_the_agreed_one` **已在**（50-7 前的批次补的），逐条比对键与刻度 ⇒ 规则之外还有数值钉 | — | **已核无问题**（记录为「已具备」，非缺项） |
| 13 | `docs/frame.md` 4.18 与代码 | 文档声称「条目上限 32 / id 为 `p`+8 位十六进制 / 写侧 fail-closed / 凭证只回掩码」等 12 条事实 | 逐条对照 `projects.py` / `config_catalog.py` / `config_write.py` 与测试 | — | **已核无问题**（12 条全部与代码一致；本轮唯一发现的文档偏差是本轮自己修的 27→32 与 111/65→113/67） |
| 14 | `envfile.parse_index` 的键大小写 / 无等号行 / 注释行 | 写 `MAX_ITERATIONS` 而文件里是 `max_iterations=5`：**原地替换**（不留死行）；无等号行不入索引；注释行同名键**追加**新行而不动注释 | 探针 A / F / J | — | **已核无问题**（这三处是保真写最容易出错的地方，现为正确行为） |

> 镜头一合计 **11 条发现**（另 3 条为「已核无问题」记录）——满足契约「至少 10 条」。

## 镜头二 · 边界追踪（真实调用链）

| # | 边界输入 → 行为 | 证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | 同一键在文件里出现两次（真实 `.env` 就有）：写一次只重写**最后一行**，第一行原样留下（值仍以后者生效） | 探针 C：`…=4000\n…=4096` → 写 8192 后为 `…=4000 / …=8192` | — | **已核无问题**（「后者生效」语义与解析一致，且面板 `duplicate_keys` 会告警） |
| ② | 空值键（`KEY=`）被写通道接着写：原地替换为 `KEY=4096`，不产生重复行 | 探针 D | — | **已核无问题** |
| ③ | 目标是**目录**（病态输入）：`ConfigWriteRejection: config write failed: [Errno 13] Permission denied`，**零副作用** | 探针 E | — | **已核无问题**（fail-closed；锁文件除外，见镜头一 #2） |
| ④ | 值含裸 `CR` / 裸 `LF`：`EnvWriteError: contains a control character` 拒 | 探针 G | — | **已核无问题**（否则可破坏行结构） |
| ⑤ | 文件**无末行换行**时追加新键：保持「无末行换行」这一文件属性 | 探针 K：`MAX_ITERATIONS=5\nSHELL_TIMEOUT=60`（新行同样无末行换行） | low | **defer**（有意保真：跟文件既有风格；但某些工具有「必须末行换行」的约定 ⇒ 记入台账备查） |
| ⑥ | 写成功后**进程环境**不受影响（`.env` 不是环境变量） | 探针 I：`os.environ.get("MAX_ITERATIONS") == "<未设置>"` | — | **已核无问题**（面板的 `system_env` 层由此天然区分） |
| ⑦ | 32 个错误码 ↔ UI 文案表：0 缺 0 幽灵 | `review50_errorcodes.py` | — | **已核无问题** |
| ⑧ | 项目根被删 + 写请求：闸门 → 项目解析 ⇒ `project_unavailable`（409），不触碰文件 | 读码 + 既有用例（`test_real_console_reports_unavailable_project`） | — | **已核无问题** |
| ⑨ | 写入期间并发第二个写：唯一胜者，败者 `config_conflict`（**跨进程**由文件锁兜底） | 既有用例 `test_concurrent_writers_only_one_wins` + 读 `atomic_update_bytes` | — | **已核无问题**（附带镜头一 #3 的锁时长隐患） |

## 镜头三 · 验证缺口（对照 AC 与测试报告）

| # | AC / 声称 | 实际证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | 「每个控制台错误码都有可读文案」（用例名 + 50-6 记录） | 用例只枚举 **14/32**；JS 表实际齐全 ⇒ 声称成立但**判据不覆盖** | medium | **patch 已修**（枚举驱动；负对照证明旧清单是瞎的） |
| ② | 50-3 AC9 / D1「损坏会话」的**运行入口**侧 | `_resolve_session` 分支零覆盖（可达） | medium | **patch 已修**（新增真实装配用例） |
| ③ | 50-7 验收表称 `cli_http.py`「计入总量并由测试覆盖」 | 实测 **89%**（41 条未覆盖）：其中 `194-201`（`http-server` 命令的 serve 主体，测试桩掉了 `_serve_http`）、`831-863`（serve 收尾/关闭的错误路径）、`519/611/785/1058`（日志与防御分支）为**合理的**未覆盖；`531-535/546-550/565-569/764-765` 为**错误分支**（565-569 不可达） | low | **patch 部分**（②已补 764-765，实测 cli_http 89% / session 85→90%）；其余如实记入本报告，`cli_http.py` 不 omit 的口径**不变** |
| ④ | 50-5 的「审计不含值」 | 既有用例 + `TestAuditRetention` 的哈希断言 + 50-7 的五面用例（变异体⑥证明有牙） | — | **已核无问题** |
| ⑤ | 50-6 的浏览器验收 18 行 | 本轮亲跑：`ACCEPTANCE {"rows":18,"failed":0}`（新工作区，Chrome 153） | — | **已核无问题**（不进 CI 的缺口已登记） |
| ⑥ | 50-2 Dev Record 的「110 passed, 1 skipped」 | 沿用第一轮结论（不可复现，反推下界 ≥238） | low | **defer**（已登记；不改写他人 story 记录） |
| ⑦ | 50-7 的「6 条变异体全部精确变红」 | 本轮复核：`mutate_50_7.py` 6/6 仍全红 | — | **已核无问题** |

---

## 就地修复清单（最小修复 + 负向验证）

| 文件 | 修复 | 受影响测试（重跑） | 负向验证 |
|---|---|---|---|
| `tests/test_http_web_ui.py` | 错误码参数改为**由 `HttpErrorCode` 枚举派生**（32 条，自维护） | `tests/test_http_web_ui.py` → **117 passed** | `M1`：从 `app.js` 删 `server_error` 文案 ⇒ **1 failed**；**`M1b` 负对照**：同一变异 + 旧手写清单 ⇒ **0 failed**（证明修复有牙） |
| `tests/network/test_http_console_e2e.py` | 新增 `test_a_run_cannot_be_started_in_an_unreadable_session`（真实装配） | `tests/network/test_http_console_e2e.py` → **10 passed** | `M2`：把该分支的 `except SessionUnreadableError` 换成别的类型 ⇒ **1 failed** |
| `src/heagent/web/app.js` | `askConfirm` 被顶掉时把前一个按「取消」结算（1 行 + 注释） | `tests/test_http_web_ui.py`（含 14 个 node 探针用例）→ 全绿 | **无可观察差异**（已分析：两种写法都不执行危险操作）⇒ 无新增断言，如实标注 |
| `docs/frame.md` / `docs/README.md` / 脊柱 / 总览 / 状态 / story | 50-7 的文档同步（27→32 码、111/65→113/67、4.18 小节、Epic 49/50 两行等） | 全量 `pytest` | 纯文档（50-7 的 6 条变异体已覆盖文档契约面） |

**删除检查**：`33adba0..1ca29cf` 未删除任何既有守卫或契约。被改写的既有测试只有两处，均为**改强**：
① `test_corrupt_registry_warns_and_recovers_empty` → `…_is_read_fail_soft_but_never_overwritten`（第一轮）；
② `test_every_console_error_code_has_a_readable_text` 的参数由 14 条**扩到 32 条**（本轮）。

## 处置汇总

| 严重度 | 条数 | 处置 |
|---|---|---|
| high | **0** | —（第一轮的 3 条 high 已闭合，本轮复核无回退） |
| medium | **7** | **patch 已修 2**（镜头三①②）；**defer 3**（镜头一 #6/#7/#8，沿用第一轮已登记）；**intent_gap/blocked 1**（非回环运行姿态）；**patch+defer 1**（镜头三③：补证 + 如实记录未覆盖面） |
| low | **6** | **patch 已修 1**（镜头一 #11）；**defer 4**（回滚文案 / `.env.lock` 落点 / 锁内 I/O / 末行换行约定）；**不补造用例 1**（镜头一 #4 不可达分支 + 纠正第一轮覆盖主张） |
| 已核无问题 | **11 条**（镜头一 3 + 镜头二 8） | —（记录在案，避免「没写就是没查」） |
| reject | 0 | — |

新增 deferred 条目 **1 条**（末行换行约定；`.env.lock` 落点与锁内 I/O 两条并入既有「控制台」族条目下的说明）。
`review_loop_iteration: 0` —— 本轮无「回实现阶段重新推导」的情形（全部为就地最小修复或如实登记）。

## 结论

- **Story 层（50-1…50-7）：全部放行。** 第一轮 3 条 high 已闭合且本轮复核无回退；本轮 2 条 medium 验证缺口
  已就地补上并带负向验证；`pytest` **3076 passed**、覆盖率 **91.83%**（门限 87%）、ruff / format / mypy 双平台
  全绿、真浏览器 18/18。补证的可量化收益：`context/session.py` 覆盖率 **85% → 90%**（损坏会话的运行入口路径）。
- **Epic 50 收口：放行。** 七条 story 的交付物齐备（含两份验收清单与三份文档同步），Epic 级无 high 级残留。
- **不阻塞收口但需人裁决/后续跟进的 3 项**（均已在台账）：
  1. **blocked**：非回环运行姿态（项目重命名 / 四个会话写操作 / 项目内运行入口无回环门）；另 `enable_cron=False`
     仍绑 cron 工具面 —— 两条都需要产品/安全口径拍板。
  2. **defer（medium）**：`deadline_reason` 归因保留、`tools_in_flight` 不衰减、唯一事件循环里的同步 I/O。
  3. **defer（low）**：`.env.lock` 落在用户项目根、回滚失败时的文案、写锁内 I/O 时长、无末行换行文件的追加约定。
- **给下一次评审的备忘**：本轮的「负对照」手法（同一变异 + 旧判据 ⇒ 应当全绿）能证明**判据修复**本身的价值，
  建议对「补证据」类发现一律配套使用。
