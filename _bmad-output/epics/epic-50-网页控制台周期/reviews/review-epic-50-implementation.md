---
epic: E50（网页控制台）
scope: Epic 50 全部增量（Story 50-1 / 50-2 / 50-3 / 50-4）
diff_range: 33adba0..3ff9d8d（评审时 HEAD；修复后另起提交）
review_loop_iteration: 0
reviewer: code_review 契约（三镜头 + 定级 + 分诊）
verdict: 有条件放行（Epic 收口**不放行**：还差 50-5/50-6/50-7 与 1 条待裁决 intent_gap）
created: '2026-09-24'
---

# Epic 50 实现增量 · 收口评审报告

按 `code_review` 契约执行：**对抗式 / 边界追踪 / 验证缺口** 三镜头各自独立成段；定级前逐条打开源码读调用点
与守卫；Critical（high）就地最小修复并重跑受影响测试 + 负向验证。

## 评审范围

- **Epic**：`_bmad-output/epics/epic-50-网页控制台周期/`（脊柱 + 7 份 story）。
- **覆盖的 story**：50-1（工作区一等化）、50-2（项目注册表 API）、50-3（会话持久化 / 会话 API / 项目内运行）、
  50-4（配置来源求解与只读配置 API）。50-5/50-6/50-7 尚未实现，不在本次代码面内。
- **diff 范围**：`git diff 33adba0..HEAD` —— 47 文件 / +6235 −217。其中 src 约 3.9k 行、tests 约 2.3k 行。
- **改动文件（评审对象）**：`workspace.py`、`projects.py`、`context/session.py`、`network/http_protocol.py`、
  `network/http_console_protocol.py`、`network/http_server.py`、`cli_http.py`、`cli.py`、`config_catalog.py`、
  `tools/path_safety.py`、`housekeeping.py`、`engine/container.py`、`agent/loop.py`（cron 绑定）、
  `agent/run_lifecycle.py`（失败落盘）；测试面 9 个文件。
- **三镜头并行执行**：两个隔离子代理负责「对抗式」「验证缺口」的广度扫描，边界镜头首轮超迭代上限后**收窄重跑**；
  三条发现的**定级与处置由我逐条打开被引用的源码/配置后给出**（下表凡标「已核」者均为亲读）。

### 我实际执行过的命令与结果

| 命令 | 结果 |
|---|---|
| `python -m pytest -q` | 评审开始时 **2735 passed / 10 skipped**；本轮全部修复与证据补齐后 **2747 passed / 10 skipped** |
| `python -m pytest -q --cov` | 评审开始时 TOTAL **91.33%**；收口时 **91.44%**（门限 87%） |
| `python -m ruff check src tests` | All checks passed（两轮） |
| `python -m ruff format --check src tests` | 272 files already formatted |
| `python -m mypy src` / `python -m mypy --platform linux src` | 均 `Success: no issues found in 144 source files` |
| `python .heagent/tmp/mutate_50_review.py` | **7/7** 变异体精确变红（本轮全部修复与新增证据的可执行判据） |

---

## 镜头一 · 对抗式（找「缺什么」）

| # | 位置 | 问题 | 证据（亲读） | 严重度 | 处置 |
|---|---|---|---|---|---|
| 1 | `context/session.py:224` | 畸形消息条目让**整页会话列表 500**，与自身 docstring 的 fail-soft 承诺矛盾 | `title = derive_title([Message(**item) for item in message_list if isinstance(item, dict)])`，而 `list_metadata` 只 `except SessionUnreadableError`（`:404`）⇒ pydantic `ValidationError` 穿透 | **high** | **patch 已修**（A 变异体） |
| 2 | `projects.py:213-226` + `:137/:164/:184/:203` | 注册表解析失败 ⇒ 空表被回写 ⇒ **一次坏字节清空全部已登记项目**（只留一行 WARNING） | `_decode` 解析失败 `return []`，而 4 条写路径都 `entries = self._decode(raw)` → `_encode(entries)` 写回 | **high** | **patch 已修**（B 变异体；同时改写了把该行为钉成预期的既有用例） |
| 3 | `network/http_server.py:1320` vs `:1332/:1400/:1420/:1433/:1447` | 回环闸门只装在登记/移除，危害更大的「起 run」与会话增删改无闸门 | `register_project` 有 `_loopback_error`，其余写路由没有 | medium | **defer**（49 的 `/api/runs` 本无闸门 ⇒ 暴露面未扩大；已登记台账） |
| 4 | `network/http_server.py:659/665/690/710` | `deadline_reason` 一经写入永久保留 ⇒ 用户的 `DELETE` 可能被误报 `timed_out` 并吞掉取消；`reopen()` 可让旧任务上报 `timed_out` | 看门狗先写 `deadline_reason` 再 `cancel()`；`_execute` 只判「非 None 且未关停」 | medium | **defer**（与镜头二②同族；已登记台账） |
| 5 | `network/http_server.py:659` | `tools_in_flight` 永不衰减 ⇒ 一个**永不返回**的工具让静默判据恒不成立，名额被无界占用 | 计数只由 `tool_call`/`tool_result` 增减；`http_request_timeout` 默认 0 | medium | **defer**（需「在途工具计龄」策略；已登记台账） |
| 6 | `cli.py:226/:275` + `agent/loop.py:686` | `enable_cron=False` 只拒调度器，**cron 工具面仍绑定** ⇒ 网页运行可写 `jobs.json`，任务在后续 CLI 会话无人监督执行 | `cron_store = JobStore(...) if config.cron_enabled else None` 仍进 loop；`cli_http.new_loop` 的 `scheduler is not None → raise` 对 `enable_cron=False` 恒不可达 | medium | **intent_gap → blocked**（两条互斥修法都要改可观察行为，交人裁决；已登记台账） |
| 7 | `cli_http.py:595` vs `new_loop`/`for_workspace` | 配置面板按**项目** `.env` 报来源与取值，而运行端读的是**服务器 cwd** 的 `.env` ⇒ 同一键两个口径 | 面板显式 `build_config_report(root/".env")`；运行端共享 `self.settings`（`env_file=[global, ".env"]` 按进程 cwd 解析） | **high** | **bad_spec 已修**（脊柱 §7 明确要求「项目运行时必须显式传 `_env_file`」；C 变异体） |
| 8 | `cli_http.py:499/595/600/651` | 唯一事件循环里做同步 I/O（会话列表 / 配置求解 / `registry.list()` / 加锁重写） | 均为 `async def` 体内的阻塞调用 | medium | **defer**（已登记台账） |
| 9 | `context/session.py:388/401` | >1 MiB 会话仍整份读入（只跳过了「数消息」） | `read_text` 无视 `info.st_size` | low | **defer**（已登记台账） |
| 10 | `cli_http.py:505-508`、`:571-583` | ① `create()` 的 `SessionConflictError`（非 `ValueError` 子类）漏捕 ⇒ 500；② 名额冲突前已落一个空会话文件 | `except ValueError` 一处；`_resolve_session` 先 `create()` 再 `start_run()` | low | ① **patch 已修**；② **defer**（失败请求留下空会话，登记台账） |
| 11 | `tools/path_safety.py:310` vs `:318` | 新增 `root` 形参只参与相对解析，deny 集仍取全局 `workspace_root()` ⇒ 接缝级绕过 | `build_internal_state_dirs() \| build_internal_state_dirs(workspace_root())` | low | **defer**（当前调用方同根；已登记台账） |
| 12 | `docs/frame.md:1014` | 文档写 `HttpErrorCode` 封闭 **22** 码，实测 **27** | `len(list(HttpErrorCode)) == 27` | low | **patch 已修**（文档） |
| 13 | `.env.example:339` | `HTTP_MAX_INFLIGHT_RUNS` 已是**每项目**口径，文档仍写「全局上限」 | `_inflight_in_scope(project_id)` | low | **patch 已修**（文档） |
| 14 | `config_catalog.py:329` | 「控制台自身」排除规则声明了两个**尚不存在**的 `Settings` 键 | 全仓引用核对：只出现在常量表与测试里 | low | **reject**（有意为之：常量先就位，50-5 新增该两键后即生效，见 50-4 的 T6 边界说明） |

## 镜头二 · 边界追踪（真实调用链）

| # | 位置 | 边界输入 → 行为 | 证据 | 严重度 | 处置 |
|---|---|---|---|---|---|
| ① | `http_server.py:1238` vs `:780` | N 个并发 `GET /api/runs/{id}/events` → 限额「先查后加」可被穿过（不崩、不泄漏，但每订阅者驻留 512 事件队列） | 检查在端点，登记在生成器首个 `__anext__` | medium | **defer**（已登记台账） |
| ② | `http_server.py:607/690/710` | 关停与看门狗同 tick 到达 → 归因偏向 `cancelled`（终态唯一、名额正确，仅「为什么结束」由谁先跑决定） | `self._closing = True` 先置位 | low | **defer**（与镜头一④同族） |
| ③ | `config_catalog.py:783` + `:926` | 项目 `.env` 值非法 ⇒ 整层被摘 ⇒ **文件里的未知键也一起消失**（AC5 的诊断恰在最需要它时丢失） | 实测：`notes=('project_env_invalid',) unknown_keys=()` | medium | **patch 已修**（改依据行级扫描 + 非 UTF-8 门；D 变异体） |
| ④ | `config_catalog.py:786` | 四层候选全败 → 抛 `ValidationError` → 不透明 500 无稳定码 | 仅在**系统环境变量**非法时可达（进程级配置错误） | low | **defer**（有意抛：此时运行期 `Settings()` 同样失败） |
| ⑤ | `config_catalog.py:611-634` | 0 字节 `.env` → `line_count=1`（按 `split("\n")` 段数计） | 实测 | low | **patch 已修**（改 `splitlines()` + 0 字节用例） |
| 已核无问题 | — | 同一项目第二个 run / 跨项目并发（`http_server.py:458` 按项目计名额）；DELETE 幂等且 `wait(timeout)` 有界（`:563`）；断线在 `finally` 释放（`:805`）；关停由 `_finalize` 兜底（`:530`）；一万行 / 5000 未知键 / 全重复键均线性且有界（`MAX_UNKNOWN_KEYS` 与协议 `max_length` 同源） | 附行号 | — | — |

## 镜头三 · 验证缺口（对照 AC 与测试）

| # | AC / 声称 | 实际证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | 50-3 AC10「失败/取消的 run 也写会话文件」 | 唯一相关用例用替身 handler「先 `save` 再 `raise`」= **循环论证**；`persist_and_cache` 所在的 `finally`（`run_lifecycle.py:278`）零覆盖 | high→medium（实现正确、证据缺失） | **patch 已补证据**：新增真实 `AgentLoop` + 真实 `SessionStore` 的失败落盘用例（F 变异体证明有牙） |
| ② | 50-2 AC9「上限后返回 `project_limit_reached`」 | 网络层项目用例**全用假 console**，真实 `HttpProjectConsole` 的注册表方法无 HTTP 级证据 | medium | **patch 已补证据**：真实 console + 31 条登记 + HTTP POST → 409 |
| ③ | 脊柱 I1「网络层不得 import config/projects」 | `FORBIDDEN_RUNTIME_IMPORTS["network"]` 只列**子包** ⇒ 顶层模块写法可绕过（契约形同虚设） | medium | **patch 已修**：加 `heagent.config/config_catalog/projects/workspace` + 顶层模块名识别器 + 识别器单元测试（E 变异体） |
| ④ | 50-3 AC4「PATCH 持旧 fingerprint ⇒ 409 且不覆盖」 | 只有「假 console 直接抛码」用例；真实 `fingerprint → expected_version → 409` 链路零证据 | medium | **patch 已补证据**（H 变异体证明有牙） |
| ⑤ | 50-3 AC2/AC3「工具调用配对」「第二次运行写回同一文件」 | HTTP 端到端只跑无工具调用的 prompt；「写回同一文件」无断言 | medium | **defer**（需要 tool-calling 替身走 HTTP；登记台账） |
| ⑥ | 50-2 Dev Record「110 passed, 1 skipped」 | 同一命令在当前树实测 **294 passed**；按用例增量反推该命令在 `7ef2c92` 时 ≥238 ⇒ 该数字不可复现 | medium | **defer**（文档准确性；原因见下） |
| ⑦ | 50-2 T7「新增码同步文档」 | `docs/frame.md:1014` 写 22 码、实测 27（与镜头一⑫同处） | low | **patch 已修**（文档） |
| ⑧ | 脊柱 §8「110 = 46 + 64」；§3.1 `config_backups` 路径 | 实测 111 = 46 + 65（残留 0）；代码是 `state_dir/"backups"`（无 `/env`） | low | **patch 已修**（脊柱就地校正 + §14 补 C9/C10 校正行，遵守其「要改先改本文件」规则） |

> ⑥ 的补充说明：该数字出自 50-2 当时的环境，我无法在不 `checkout` 历史提交（评审纪律禁止写操作）的前提下复现，
> 故只登记「不可复现 + 反推下界」，不擅自改写他人 story 的验证记录。

---

## 就地修复清单（最小修复，逐条带负向验证）

| 文件 | 修复 | 回归用例 | 变异体 |
|---|---|---|---|
| `context/session.py` | 消息项不合法 ⇒ `SessionUnreadableError`（与「JSON 坏了」同档），列表 fail-soft、详情回稳定码 | `test_list_metadata_treats_invalid_message_entry_as_unreadable` 等 2 例 | A（RED） |
| `projects.py` | 读写分工：读 fail-soft（不变）、写 **fail-closed**（解析不了就拒绝改写，`server_error`） | `test_corrupt_registry_is_read_fail_soft_but_never_overwritten` 等 2 例 | B（RED，4 处一起回退） |
| `cli_http.py` | 派生 runtime 按**项目** `.env` 解析 settings（脊柱 §7），坏文件回退 + WARNING | `test_for_workspace_resolves_settings_from_the_project_env` 等 2 例 | C（RED） |
| `cli_http.py` | `create_session` 补捕 `SessionConflictError` → `session_conflict` | 覆盖于会话路由用例集 | — |
| `config_catalog.py` | 未知键改依据行级扫描（+ 非 UTF-8 门）；`line_count` 改 `splitlines()` | `test_unknown_keys_survive_layer_degradation` 等 3 例 | D（RED） |
| `network/http_server.py` | `_CONSOLE_ERROR_STATUS` 补 `SERVER_ERROR: 500`（服务端状态类失败不再落到默认 400） | 见 B 的 HTTP 通道 | — |
| `tests/test_architecture_contracts.py` | I1 契约覆盖顶层模块 + 识别器单元测试 | `test_forbidden_import_detection_covers_top_level_modules` | E（RED） |
| `tests/test_agent_loop.py` | AC10 真实链路证据 | `test_failed_run_still_persists_the_history` | F（RED） |
| `tests/network/test_http_console_sessions.py` | AC4 真实指纹冲突证据 | `test_stale_fingerprint_conflicts_through_the_real_store` | H（RED） |
| `tests/network/test_http_console_projects.py` | AC9 真实上限证据 | `test_project_limit_is_reported_with_a_stable_code_over_http` | — |
| `docs/frame.md` / `.env.example` / 脊柱 / 台账 | 数字与语义校正（22→27 码、每项目上限、111/65、备份落点、C9/C10、3 条 deferred） | —（纯文档） | — |

**删除检查**：本次改动未删除任何既有守卫或契约；改动的既有测试只有一条
（`test_corrupt_registry_warns_and_recovers_empty` → `test_corrupt_registry_is_read_fail_soft_but_never_overwritten`），
原因是它的断言把「一次坏字节清空全部已登记项目」钉成了预期行为——**断言被改强而非削弱**（新断言额外要求原字节保留）。

## 处置汇总

| 严重度 | 条数 | 处置 |
|---|---|---|
| high | 3 | 全部 **patch/bad_spec 就地修复**（会话列表 500、注册表被清空、运行端读错配置），0 条残留 |
| medium | 13 | **patch 已修 6**；**defer 6**（运行时归因与兜底族、阻塞 I/O、cron 工具面、工具配对证据、50-2 数字、大面积会话读）；**intent_gap/blocked 1**（cron 工具面 + 非回环运行姿态，待人裁决） |
| low | 8 | **patch 已修 6**（含文档 4 处、`line_count`、`create_session` 码映射）；**defer 2** |
| reject | 1 | 镜头一⑭（有意为之的常量先就位） |

- 新增 deferred 台账条目 **3 条**（活动区 8 → 11 条，`ledger_count.py` 复核 11 open / 3 closed）。
- `review_loop_iteration: 0` —— 本轮无「回去重新推导」的情形：所有 Critical 都是**就地最小修复**（契约允许范围）。

## 结论

- **Story 层（50-1…50-4）：放行**。三条 high 已就地修复并通过负向验证；`pytest` **2747 passed**、覆盖率 **91.44%**、
  ruff/format/mypy 双平台全绿。
- **Epic 50 收口：不放行**，阻塞项两条：
  1. **待裁决（blocked）**：`enable_cron=False` 只拒调度器、cron 工具面仍可写任务（后续 CLI 会话会无人监督执行）
     —— 两条修法互斥，需产品/安全口径拍板（台账第 3 条）。
  2. **未完成面**：50-5（配置写入通道）、50-6（控制台 UI）、50-7（安全验收与文档）尚未实现；其中 50-5 直接复用
     本次校正后的白名单/守卫/指纹常量，50-7 需把台账第 1、3 条写进 `docs/frame.md` 五 与验收文档。
- **给 50-5 的两条硬前提**（本次评审发现）：① `HTTP_CONSOLE_*` 两键新增后会自动落入「控制台自身」排除规则
  （无需改分类逻辑）；② 备份落点只有一个来源 `WorkspacePaths.config_backups`（脊柱 §3.1 已按代码校正为 `backups`，
  不得另拼 `backups/env`）。
