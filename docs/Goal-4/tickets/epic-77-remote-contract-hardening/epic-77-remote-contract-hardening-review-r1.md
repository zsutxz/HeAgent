---
type: review
code: E77-R1
epic: epic-77-remote-contract-hardening
review_loop_iteration: 0
lens: 规格对账（Requirements / Done when 逐条对实测）
reviewed_at: 2026-11-24
head: 669ed177
---

# E77 收口三审 · R1 规格对账

## 范围

E77 在构建轮**没有跑**三审（用户直接 `approve e77`，见 `progress.md` 交接块）。本轮补审，评审对象 =
**未提交的工作树**（`HEAD 669ed177` + 20 modified / 2 untracked）。本镜头只判一件事：epic 的
Requirements R1–R3 与 Done-when 四条，逐条在代码里成立吗。

实跑命令与结果（本轮末次）：

| 命令 | 结果 |
|---|---|
| `pytest tests/network -q` | **742 passed**（21.23s） |
| `pytest tests/test_ws_project_adapter.py tests/test_ws_submission_cache.py tests/network/test_ws_project_{commands,submit}.py tests/network/test_ws_protocol.py tests/network/test_ws_command_fields.py tests/test_contract_baselines.py tests/test_architecture_contracts.py tests/test_http_web_ui.py -q` | **338 passed**（29.03s） |
| `python scripts/contract_snapshot.py --check` | 五份全 `[OK]` |
| `pytest -q`（全量，带 node） | **5899 passed / 17 skipped / 30 deselected / 1 xfailed / 0 failed**（322s） |

## 逐条对账

| 规格条目 | 判据 | 实测 | 判定 |
|---|---|---|---|
| R1 `run` 帧可选 `request_id`（1–64、不 strip） | `ws_protocol.py::WsCommandFrame.request_id` + `_FRAME_FIELDS` / `_OPTIONAL_FRAME_FIELDS` | `Field(min_length=1, max_length=64)`；`" req-1 "` 原样保留（`test_run_frame_carries_an_opaque_request_id_and_does_not_strip_it`）；空串 / 65 字符在解析面即 `malformed` | ✅ |
| R1 同键 60s 窗口内只调一次控制台、两 ack 同 `run_id` | `SubmissionCache` + 适配器 | 在途合流（控制台 1 次、两个 task 同 `run_id`）/ 成功重放 / 不同键互不干扰 / 无键逐字等价 / 失败不缓存 / TTL 过期重投，六例 + 本轮新增 5 例直接单测 | ✅ |
| R1 不带 `request_id` 的旧帧逐字等价 | 同上 | `request_id is None` ⇒ 直接走 `_submit`，不查表不登记；`test_without_request_id_every_call_is_a_new_submission` 断言 2 次真提交 | ✅ |
| R2 `project_channel_unavailable` 分流「未装配」与「帧拼错」 | `HttpErrorCode` + `ws_commands.py` 两处 | 未装配 ⇒ `project_channel_unavailable` 且**不断连**（随后 `ping` 仍 ack）；帧拼错 ⇒ `invalid_request` 且按 `WS_CLOSE_POLICY` 断连（对照用例同文件） | ✅ |
| R2 `HttpErrorCode` 只增 36 → 37、`transport_errors` 只多一条 | 枚举 + 基线 | AST 实测成员 **37**；`transport_errors.json` diff = 1 条 entry + `unmapped` 5→6 + `unmapped_codes` 增一项，其余零漂移 | ✅ |
| R3 只读 listener 零能力面、AD-8 措辞与实现对齐 | 架构 AD-8 + `docs/framework.md` §4.16.1 | AD-8 正文改成「零能力面」并把「被拒替代 (a)」标为**采用**；§4.16.1 只读旁观行补「`projects` 同样不可达」；`ws_host.py:265` 的 `if not config.readonly` 是唯一判据 | ✅ |
| R3 `brief.md` 三条延期项带裁决 + 落点 | `brief.md` §延期项 | 三条各自「已裁决 / 落点 / 判据」齐备，表头写明「本段不再有未裁决项」 | ✅（措辞瑕疵见 R3-L-1） |
| Done-when：`ruff` / `format` / `mypy` / `bandit` 与 HEAD 同谱 | 门禁 | `ruff check` 全绿、`ruff format --check` 512 files 已格式化、`mypy src` 242 files 无 issue、`bandit -r src/ -ll` `No issues identified`（4 处已知 `#nosec` 噪声，非新增） | ✅ |

## 发现

### R1-M-1（Medium，已落改）`docs/errors.md` 传输层码计数差一

- 位置：`docs/errors.md:33-35`。
- 现象：改前写「传输层全部 **35** 个稳定码」，而 `HttpErrorCode` 当时已是 36 个成员；E77 顺着旧偏差
  +1 写成 36，枚举实际已是 **37**（本镜头 AST 实测）。`合计 77 条` 的算式因此也少 1（应为 78）。
- 定位：`_bmad-output` 与测试面都**没有**守卫这个数字（`grep "个稳定码"` 只命中 docs 自身），
  所以它从 E76 起就一直差一，E77 只是继承。
- 处置：**已落改**为 37 / 78（同批核对：`pub/exceptions.py` 异常类 29 条与 `error_codes.json` 基线
  29 条一致、CLI/启动期 12 条不变 ⇒ 只有传输层这一项错）。

### R1-L-1（Low，记录不改）`exception_types.json` 收进了 `SubmissionCache`

- 位置：`tests/fixtures/contract_baselines/exception_types.json`（新增 `heagent.cli.ws_submission_cache.SubmissionCache`，`bases: []`）。
- 判定：不是误收——`scripts/contract_snapshot.py:301-321` 的口径是「子类名以 `Error`/`Exception` 结尾
  **或**在模块 `__all__` 里」，`SubmissionCache` 因进 `__all__` 被收。属既定口径，无落改。
- 副作用提醒：这个基线文件名为 `exception_types` 但实为「异常命名类 + 公共导出类」，下次见非异常类
  入表不必惊慌。

### R1-L-2（Low，验证无缺口）Web 端错误文案已有全量判据

- `tests/test_http_web_ui.py::test_every_console_error_code_has_a_readable_text` 以 `HttpErrorCode` 参数化，
  断言每个码在 `app.js` 里都有 `code:` 文案。E77 新增码的文案（`app.js:70`）自动进这条判据，
  实测 37/37 覆盖、无需补守卫。

## 结论

**有条件的通过**：Critical 0 / High 0 / **Medium 1** / Low 2。Medium 当轮落改，Low 为记录项。
R1–R3 与 Done-when 四条全部成立；无「规格说要、代码没做」的空洞。
