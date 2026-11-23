---
epic: epic-74-ws-frame-contract
code: E74
round: R3
axis: 三镜头对抗式评审
skill: code_review
review_loop_iteration: 1
date: 2026-11-23
verdict: 通过（H-1 经宿主复核为误报）
critical: 0
high: 0
medium: 8
low: 6
---

# E74 收口三审 · R3 三镜头对抗式评审

## 范围

- **评审对象**：整个 epic E74（74.1 帧字段 / 74.2 项目提交 / 74.3 `cancel_run` / 74.4 事件零漂移 / 74.5 错误码与哑传输）。
- **覆盖面**：`git diff d6e705de^..HEAD -- src/ tests/` + 工作树未提交的两处守卫修补；`ws_protocol.py` / `ws_commands.py` / `ws_server.py` / `ws_host.py` 全文；6 个 WS 测试文件；`http_server/service.py` 的真实 `cancel_run`；`cli/http_console.py` 的真实项目提交；`transport_errors.json` 结构。
- **本轮技能**：`code_review`（三个镜头各跑一遍）；`review_loop_iteration: 1`。
- **本轮命令与结果**（评审子会话自跑）：
  - `pytest tests/network -q --cov=heagent.network.ws_commands --cov=heagent.network.ws_protocol` → 671 passed；`ws_commands.py` 98%（缺 133-134）、`ws_protocol.py` 98%（缺 350/354/377）
  - `transport_errors.json` 探针 → 七条 code 全在 `entries`；`unmapped_codes` = agent_error / empty_prompt / origin_forbidden / shutting_down / timeout
- **宿主复核后的落改实测**：`pytest tests/network tests/test_architecture_contracts.py -q` = **719 passed**；`ruff check` / `ruff format --check` / `mypy src` / `bandit -r src/ -ll`（No issues identified）全绿。

## 镜头一：对抗式（≥10 条）

| # | 位置 | 问题 | 严重度 | 处置 |
|---|---|---|---|---|
| H-1 | `tests/test_architecture_contracts.py:187-190`（`_package_of`） | 评审方报「包名被加成 `heagent.heagent.*`，相对导入与禁令集合零相交，守卫仍无牙」 | **high（复核为误报）** | **reject**：见下方「H-1 复核」 |
| M-1 | `ws_host.py:268-289` | 生产装配从不传 `project_service`，也没有 `hello` 版本那样的 wiring 判据 ⇒「R2 完成」与「生产恒回 `invalid_request`」同时为真 | medium | 转 **75.5**（装配注入 entry）验收条：注入点 + wiring 判据；本条落 `brief.md`「延期项」 |
| M-2 | `ws_commands.py:191-193` → `ws_server.py:189-202` | 端口抛非 `HttpRunConflictError` 时无声退化为 `server_error` + 1011 断连，无用例 | medium | **本轮落改**：`test_untranslated_port_error_becomes_server_error_and_closes`（并钉住「异常文本不外泄」） |
| M-3 | `ws_commands.py:161-162`、`ws_server.py:242-288` | 项目端口两次 await 无时间上界，集合级端点无 `_supervise`：端口挂起即占席位、断连不被感知 | medium | 转 **75.2 / 75.3**：端口契约写明「必须有内部超时」+ 一条挂起用例 |
| M-4 | `ws_commands.py:161-162`、`test_ws_project_submit.py:235-249` | 「零副作用」只覆盖 `ensure_available` 失败；`start_project_run` 建 run 后抛错无幂等键、无判据 | medium | 转 **75.2**：`ProjectChannelService` docstring 明确「提交失败不做原子性保证」，E75 决定是否引入 `request_id` |
| M-5 | `ws_commands.py:88` | docstring 写「回终态 ack」，而真实端口在忽略取消时如实返回 `running` | medium | **本轮落改**：措辞改为「ack 带端口当时返回的状态，`running` = 取消未立即生效」+ 用例 `test_cancel_ack_reports_the_status_the_port_returned` |
| M-6 | `ws_server.py:362` | 单 run 端点的 `project_service` 接受后静默丢弃 | medium | **本轮落改**：传非 `None` 时记 `ws event=project_service_ignored`（debug），不静默吞掉 |
| M-7 | `ws_commands.py:154-159` | 「未装配项目通道」与「帧字段拼错」共用 `invalid_request`，客户端不可区分（message 不在契约面） | medium | 转 **76.6**：决定是否新增具名 code 或改环境类 code；落「延期项」 |
| M-8 | `ws_commands.py:233-243`、`ws_protocol.py:73-76` | 集合级端点可取消任意 run_id，「权限口径」实为入口口径（谁能连上谁就能取消），无所有权判定 | medium | 转 **76.6**：文档必须写成「入口口径，不是授权」（与安全声明第 3 条同型风险） |
| L-1 | `ws_server.py:487`、`:608` | CLI 旁路 / 通知流新增的 `cancel_run` 拒绝分支无任何用例（靠 tuple 共享行覆盖） | low | **本轮落改**：两条 e2e 各加一条 `cancel_run` 帧断言 |
| L-2 | `ws_protocol.py:376-377` | 「合法 JSON 不是对象」分支零覆盖 | low | **本轮落改**：`test_json_that_is_not_an_object_is_malformed`（4 例参数化） |
| L-3 | `ws_commands.py:132-134` | 单 run 端点「绑定 run 已消失」的断连分支零覆盖，现状无钉子 | low | **本轮落改**：`test_single_run_endpoint_closes_when_the_bound_record_is_gone` |
| L-4 | `ws_protocol.py:97`、`:233` | `project_id` 的 `max_length=16` 无判据（`run_id` 两侧已有）；`_OPTIONAL_FRAME_FIELDS` 粒度是字段名而非 (命令, 字段) | low | 补 `test_overlong_project_id_is_malformed`（落改）；`_OPTIONAL_FRAME_FIELDS` 结构改造转 **75.6** 并落「延期项」 |
| L-5 | `test_ws_command_fields.py:23` | 私有 `_FRAME_FIELDS` 被测试直接 import，属实现细节耦合 | low | 转 **75.6**（加 `frame_fields()` 公开读口后测试改读）；落「延期项」 |
| L-6 | `test_ws_error_codes.py:88-93` | R4 判据留逃生门：允许落在 `unmapped_codes` 也算通过 | low | **本轮落改**：删掉 `or code in baseline["unmapped_codes"]`（七条全在 entries，删后仍绿） |

## 镜头二：边界追踪

| 边界 | 会不会崩 | 会不会静默错 | 有没有测试 |
|---|---|---|---|
| `project_id` 缺席 / `null` / `""` / 带空格 / 非字符串 | 不崩 | 不会（缺省等价旧路径；`""` ⇒ `malformed`；不做 strip） | 有（`null` 与「空格原样」在同一族用例里） |
| `project_id` 17 字符 / 极大值 | 不崩 | 不会 | **本轮补齐** |
| `prompt=""` + `project_id` | 不崩 | 不会（`RunRequest` 先于项目护栏 ⇒ `empty_prompt`） | 有（帧层；`_is_blank_prompt` 靠文案含 `blank` 判，属既有口径） |
| `run_id` 空串 / 65 字符 / `null` | 不崩 | 不会（`malformed`） | 有（`test_run_id_is_exclusive_to_cancel_run` 参数化） |
| 同一帧「最大 prompt + `project_id`」 | 不崩 | 不会（`WS_MAX_INBOUND_CHARS = 6*32768+1024`，新增键 ≈25 字符仍在允差内） | 无混合用例（不影响结论，记 Low） |
| 端口抛 `HttpRunConflictError` | 不崩 | 不会（具名 code、不断连） | 有（ensure / start 各一例） |
| 端口抛其它异常 | 不崩 | **曾经会**（`server_error` + 1011） | **本轮补齐**（钉住后果 + 异常文本不外泄） |
| 端口挂起 / 无超时 | 不崩 | **会**：席位不释放、断连不感知 | 无 ⇒ M-3 转 E75 |
| 端口返回 `resolved != project_id` | 不崩 | 有：ack 不含 `resolved`，客户端不知真实落点（设计上 ack 只有 `run_id`/`status`） | 无 ⇒ 记 Low，随 E75 决定 |
| `start_project_run` 部分成功 | 不崩 | 有：无幂等键 ⇒ M-4 转 E75 |
| 取消：已终态 / 未知 id / 不匹配绑定 run / readonly | 不崩 | 不会 | 有（四个象限各有用例） |
| 取消：单 run 端点目标不存在 | 不崩 | 语义差：断连（刻意的分层） | **本轮补齐**（钉子 + 注释指向 plan 74.3） |
| 取消：真实端口超时（忽略取消） | 不崩 | ack 带 `running`（如实） | **本轮补齐**（+ docstring 措辞修正） |
| `cancel_run` 送进 CLI 旁路 / 通知流 | 不崩 | 不会 | **本轮补齐**（两条 e2e） |
| JSON 非对象帧 | 不崩 | 不会（`malformed`） | **本轮补齐** |

## 镜头三：验证缺口

- **R1**：白名单单表有强判据；长度上界本轮补齐。`null` 形态与「空格原样」有用例。
- **R2**：只到**签名层** —— 生产装配零注入点（M-1）、单 run 端点形参被丢弃（本轮改为显式 debug）、端口异常类型本轮补判据（M-2）。
- **R3**：「先 ensure 后 start」有次序判据、`code` 逐字透传有判据；「零副作用」仍只到**调用次数**（M-4 + R1 M-1 同源）。
- **R4**：七条 code 全在 `entries`（评审与宿主各测一次）；逃生门本轮收紧。
- **R5**：四象限齐；真实端口的断连分支、超时 `running`、两条只读流拒绝本轮补齐。
- **R6**：最强的一条 —— golden 信封逐字节相等 + 两层 `project_id` 拒绝 + 路由集对基线，无反例。
- **R7**：`network/` 侧守卫可用；架构契约侧经反证确认可用（见 H-1 复核）。
- **覆盖率 ≠ 行为**：`ws_commands.py` / `ws_protocol.py` 98% 时缺的那几行恰好是未定义行为的边界 —— 本轮把其中 2 处补成判据。
- **无真 e2e**：项目通道提交路径只有替身证据（生产恒 `None`），属 epic 边界内的正当留白；E75 必须带上 wiring 判据（M-1）。

## H-1 复核（宿主亲自实测，判为误报）

- **评审方主张**：`_package_of()` 返回 `heagent.heagent.network`，相对导入因此与禁令集合零相交。
- **成因**：评审调用时传的是 `SRC/'heagent'/'network'/...`，而 `SRC` 已等于 `src/heagent` ⇒ 路径本身多了一层，得出双前缀的假象。
- **宿主实测（真实接线）**：
  - `_package_of(SRC/'network'/'ws_commands.py')` → `heagent.network`（正确）
  - `_package_of(SRC/'network'/'__init__.py')` → `heagent.network`（正确）
  - 注入 `from ..config import get_settings` 到 `src/heagent/network/ws_commands.py` 后跑 `pytest tests/test_architecture_contracts.py::test_no_reverse_dependency_on_agent` → **红**，报错文本逐字为 `运行期反向依赖：network/ws_commands.py → heagent.config`
  - `git checkout` 复原后同一判据 → **绿**
- **结论**：守卫**有牙**，H-1 判 `reject`（噪声），不落改。评审建议的「新用例改走 `_package_of`」仍采纳一半：真实接线的红/绿已由宿主反证记录在本节，`_package_of` 本身无需修改。

## 处置汇总

| 级别 | 计数 | 落改 / 转下游 |
|---|---|---|
| high | 1（复核后 0） | H-1 = 误报（reject），附宿主反证 |
| medium | 8 | 落改 3（M-2 / M-5 / M-6）；转 75.2·75.3·75.5·76.6 共 5（M-1 / M-3 / M-4 / M-7 / M-8），全部落 `brief.md`「延期项」 |
| low | 6 | 落改 5（L-1 / L-2 / L-3 / L-4 的 `max_length` 部分 / L-6）；转 75.6 共 2（L-4 的 optional 结构、L-5） |

**落改实测**：`pytest tests/network tests/test_architecture_contracts.py -q` = 719 passed（+8 例）；`pytest tests/network -q` = 679 passed；`ruff check` / `ruff format --check`（499 files） / `mypy src`（239 files） / `bandit -r src/ -ll`（No issues identified）全绿。

## 结论

**通过。**

- 唯一 high（H-1）经宿主实测为误报：真实接线注入相对导入后架构契约判据**转红**，复原**转绿**。
- medium 8 条中 3 条本轮落改、5 条转下游 entry 并写明义务；low 6 条中 5 条本轮落改。
- 无遗留 high / critical ⇒ 放行进回顾与提交。
