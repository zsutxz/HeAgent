---
id: 48-5
title: 网络入口安全边界与可观测性
status: done
parent_epic: E48
priority: P1
depends_on: [48-4]
created: '2026-09-22'
---

# Story 48-5：网络入口安全边界与可观测性

## 用户故事

作为服务运行者，我希望 TCP 入口默认只暴露给本机，并为每次请求提供有限、可关联且不泄密的诊断信息，以便实验使用时能识别风险和定位失败。

## 范围

- localhost 默认和非 loopback 告警。
- request id、连接阶段、耗时、结果状态和错误码日志。
- 日志/响应信息最小化和敏感信息边界。
- 与现有 EngineEvent、JSONL rollout 和 CLI stderr/stdout 边界说明。
- README、`docs/frame.md` 的安全声明与模块说明。

## 边界与约束

**Always**

- TCP 输入按不可信用户输入处理。
- 非 loopback 监听明确提示“无认证、无 TLS、非生产安全边界”。
- 日志包含 request id 和稳定错误码。
- 观测失败只 warning，不改写业务响应。
- 复用现有 Agent/Engine 埋点，不复制工具和 Provider 事件。

**Never**

- 不记录 API Key、凭证环境变量或完整 traceback 到客户端。
- 不默认记录完整 prompt、工具原始输出或可能含凭证的响应体。
- 不宣称 SafetyGuard、PolicyEngine 或 sandbox 能替代网络认证/OS 隔离。
- 不因“仅 localhost”而把客户端视为可信。

## 任务

- [x] 使用 `ipaddress` 或等价标准库逻辑判断 loopback；主机名解析语义需明确测试。（新模块 `network/exposure.py`：IP 字面量走 `ipaddress.is_loopback`（含 `[::1]` 脱括号）、字面量 `localhost` 判回环、**其余主机名不解析 DNS**（阻塞 I/O + 「解析到本机」≠「绑定到本机」）⇒ fail-safe 按暴露处理；`tests/network/test_exposure.py` 22 例，含「把 `socket.getaddrinfo` 打成炸点」的零解析锁与 `localhost.` 变体语义）
- [x] 非 loopback 启动时向 stderr 和 logger 输出一次明确告警。（CLI 向 stderr 印一行 `[tcp] WARNING: …`；`TcpServer.start()` 记一条 `event=exposed`，两者文案同源。默认 logging 配置下 stderr 会看到两行——刻意冗余：`LOG_LEVEL=ERROR` 时仍保证有提示，已写入测试 docstring）
- [x] 为 accepted/rejected/processing/completed/failed 阶段添加结构化日志字段。（`tcp event=accepted|rejected|processing|completed|failed` + `started|exposed|cancelled`；字段 request_id / peer / bytes / reason / 稳定 code / elapsed_ms；rejected 有 5 个 reason：idle_timeout / oversized_line / decode_failed / inflight_limit / connection_limit）
- [x] 记录 elapsed_ms，不记录无界 prompt 正文。（`_elapsed_ms(started_at)` 单点；`tests/network/test_tcp_server.py::test_prompt_body_never_reaches_the_logs` 用哨兵串断言正文零出现）
- [x] 将内部异常映射为协议错误码，详细 traceback 只进入受控 debug/error log。（`_run_request` → `server_error`、`__call__` → `agent_error`；traceback 只经 `_safe_log(..., exc_info=True)` 进服务端 error 日志）
- [x] 明确 TCP response、CLI stdout/stderr、rollout JSONL 三条输出通道。（README + frame 4.16 + `cli_tcp` 模块 docstring；`test_socket_channel_carries_exactly_one_response_line`（读到 EOF 仅一行 + stdout 零写入）与端到端 `test_tcp_response_is_one_line_regardless_of_rollout_setting`（含「TCP 入口不写 rollout」的现状锁））
- [x] 更新 README 使用示例与风险说明。（新增「TCP 入口（实验性）」章节：命令示例、一条请求/响应样例、8 个稳定错误码、五条风险、通道说明；安全说明补一条）
- [x] 更新 `docs/frame.md` 模块 DAG、CLI 入口、数据流、配置表和安全边界。（§二 加 TCP 路径、§三 加 `network/` 依赖规则、§4.1 加入口行、§4.10 加 8 个 `tcp_*` 行、新增 §4.16 详解表、§五 加 5 条缺口、§六 目录树 + §七 调用链）
- [x] 如架构契约新增 network 依赖规则，更新可执行断言。（48-3 已建 `FORBIDDEN_RUNTIME_IMPORTS["network"]`；本 Story 按评审 W-7 把入口层域模块 `heagent.goal` 纳入 `_ENTRY_LAYER_MODULES`，其余包条目同步收紧——AST 实测运行期只有 `cli_goal` 导入 `goal/`）

## 验收标准

- Given 默认 host，when 启动，then 监听 localhost 且不输出外部暴露告警。
- Given host=`0.0.0.0` 或非 loopback 地址，when 启动，then stderr/log 明确提示无认证和非生产风险。
- Given 请求成功，when 完成，then 日志可由 request id 关联 accepted→completed 并含耗时。
- Given 请求失败，when 完成，then 日志含稳定错误码，客户端不收到 traceback、API Key 或绝对路径。
- Given logger/事件 sink 抛异常，when 处理请求，then业务响应不被改成失败。
- Given `EVENTS_ROLLOUT_ENABLED` 任一状态，when TCP 请求完成，then TCP 响应不混入 rollout 事件行。

## Definition of Done

- 安全告警和日志脱敏有自动化测试。
- README/frame 与代码事实一致。
- 没有把 TCP 描述成生产级服务或安全边界。
- 现有安全声明未被削弱。

## 代码地图

- `src/heagent/network/tcp_server.py`：连接与请求日志。
- `src/heagent/cli.py`：启动告警和本地展示。
- `src/heagent/events/`：只读复用边界，不复制埋点。
- `README.md`：使用与风险。
- `docs/frame.md`：架构权威。
- `tests/test_cli_tcp.py`：告警与输出通道。
- `tests/network/test_tcp_server.py`：日志失败不影响业务。

## 验证命令

```text
pytest tests/test_cli_tcp.py tests/network/test_tcp_server.py tests/test_events_jsonl.py -q
ruff check src tests
ruff format --check src tests
mypy src --platform linux
```

## Verification

**Commands and results (2026-09-22 本机 UTC+8；CI 等价 Linux 复跑见 Deviation)：**

- 定向：`pytest tests/network tests/test_cli_tcp.py tests/test_tcp_agent_integration.py tests/test_architecture_contracts.py tests/test_events_jsonl.py -q` → **161 passed**
- 全量 `pytest -q --cov=heagent --cov-fail-under=87` → **2210 passed / 9 skipped / 18 deselected，覆盖率 90.99%**（门限 87%；本 Story 净增 38 条测试）
- `ruff check src tests` → All checks passed；`ruff format --check src tests` → 246 files already formatted；`mypy src --platform linux` → Success: no issues found in 135 source files
- 反向验证（变异体必须让护栏精确红，跑完按 sha256 还原原文）：**7 个变异体全红** —— ①去掉非回环告警、②把 prompt 正文写进日志、③完成日志绕过 `_safe_log`、④取消路径不记终态、⑤oversized 的 reason 分裂回两个桶、⑥`id` 丢掉上界与控制字符校验、⑦`cli_tcp` 回到裸 `logger`（评审 C-1 原病）

**Implemented：**

- `src/heagent/network/exposure.py`（新）：`is_loopback_host` / `exposure_warning` 单点判定与告警文案。
- `src/heagent/network/tcp_server.py`：`_safe_log`（观测故障不影响协议）、`_elapsed_ms`、`_peer_label`、`_reject`；阶段日志 `started|exposed|accepted|rejected|processing|completed|failed|cancelled`；`start()` 非回环记 `event=exposed`。
- `src/heagent/cli_tcp.py`：`_safe_log` + 两处异常分支改走它；启动前 stderr 告警；模块 docstring 写明 MCP 决策、三通道与「观测故障保证边界」。
- `src/heagent/network/protocol.py`：`id` 有界（≤128）+ 禁控制字符。
- `tests/`：`tests/network/test_exposure.py`（新，22 例）、`tests/network/test_tcp_server.py`（+10 例）、`tests/network/test_protocol.py`（+2 例含参数化）、`tests/test_cli_tcp.py`（+5 例）、`tests/test_tcp_agent_integration.py`（+1 例参数化）、`tests/test_architecture_contracts.py`（入口层清单纳入 `heagent.goal`）。
- 文档：`README.md`（新章节 + 安全说明）、`docs/frame.md`（§二/§三/§4.1/§4.10/§4.16/§五/§六/§七）、`.env.example`（`TCP_HOST` 注释同步告警语义）。

**关键设计决策（含证据）：**

1. **暴露判定：IP 字面量 + 字面量 `localhost`，其余不解析 DNS**。启动期解析是阻塞 I/O，且「解析到本机」与「实际绑定到本机」不等价（多网卡 / 解析结果会变）；不做解析的方向是 fail-safe——误报多一条提示，漏报才会让人误以为没对外暴露。实测：`[::1]` 也能真实绑定（socket 层接受该写法），判定与之一致。
2. **告警两条通道、刻意冗余**：CLI 一行 stderr（`LOG_LEVEL=ERROR` 也保证有提示）+ 服务端一条 `event=exposed` 日志（可被日志采集系统抓取）。默认配置下 stderr 出现两行，已在测试 docstring 与本 story 里写明，不隐瞒。
3. **观测故障的保证边界（评审 C-1）**：入口层插桩全部经 `_safe_log` ⇒ 日志设施抛异常时 `agent_error` 不会被改写成 `server_error`。但**运行栈**（`agent`/`engine`/…）自身的 `logger.*` 若命中*在 `emit` 里抛异常*的 handler 仍会传播——实测 `logging.raiseExceptions=False` **也拦不住**（`Handler.handle` 不捕获 `emit` 异常），故不做该无效改动，改为如实记入 frame 五、已知缺口。
4. **`id` 有界 + 禁控制字符（评审 W-4）**：`id` 是客户端可控且原样进 3 个日志点的字段；实测换行可**伪造一条完整 `completed` 记录**，超长可把日志放大约 3 倍请求体。128 字符足够表达 UUID / 序号组合，边界值有测试。

**Critical review fixes（对抗式评审发现并已修）：**

- **C-1（Critical，真阳性）**：`cli_tcp` 的两处异常分支用裸 `logger.*` ⇒ 日志抛异常时兜底 `except` 把 `agent_error` 改写成 `server_error`（实测复现）。已修（`_safe_log`）+ 回归测试；运行栈部分作为已知缺口记录。
- **7 条 Warning 全部处置**：W-1 告警条数措辞与测试声明不符 → 措辞如实化并写明两通道分工；W-2 rollout 是「死开关」（TCP 入口从不构造 `JsonlSink`）→ 文档改为「仅 CLI 单次模式」+ 端到端测试改为**钉住该现状**；W-3 取消路径无终态日志 → 补 `event=cancelled`；W-4 `id` 无界可伪造日志 → 协议层加约束；W-5 同一 oversized 违规两种 reason → 归一 `oversized_line`；W-6 `agent_error` message 是上游原文透传（无路径净化）→ 在 `_client_error_message` docstring 写明边界与净化位置；W-7 契约表漏 `heagent.goal` → 补入并同步收紧其余条目。
- 评审同时**核实无问题**的项：回环判定与零告警、`[::1]` 绑定口径一致、5 条 rejected 的 reason+code、完成/失败路径的 id+elapsed_ms、prompt 正文与工具输出不入日志、客户端对未知异常只收固定文案、socket 单行 + stdout 零写入、**不连 MCP（类级炸弹 + 标记文件 + 注册表三重验证，构造 0 次）**、`network/` 运行期导入面（AST）。

## Review Status

实现、对抗式评审（独立子代理，46 轮）与定向/全量验证均已完成：评审 **1 Critical + 7 Warning 全部处置**（5 修 2 记边界），4 个新增护栏 + 3 个原有护栏共 7 个变异体全部精确红。**未提交 Git**；状态 `done`。

## Deviation / 已知边界

- **运行栈日志不在「观测故障免疫」范围内**：见上文决策 3；CPython `Handler.handle` 不捕获 `emit` 抛出的异常。已在 `docs/frame.md` 五、已知缺口登记，全局收口（给运行栈加安全日志）属后续工作。
- **TCP 日志会含工具调用摘要**（评审 C-2）：入口复用 `EngineContainer.default` 的默认 `LoggingObserver`（INFO，`tool=… target=…`），而 `shell` 的 target 不截断 ⇒ 文件路径与命令原文（可能含凭证串）会进日志。属既有引擎行为，本 Story 的保证是「prompt 正文与工具**返回**内容不入日志」；已在 README 提示「不要把凭证写进命令或路径」，并在 frame 五登记「日志脱敏属后续工作」。
- **TCP 入口不写 rollout**：`EVENTS_ROLLOUT_ENABLED` 目前只影响 CLI 单次模式；本 Story 的 AC 只要求「响应不混入 rollout 行」，已用端到端测试钉住现状（要接入属后续工作）。
- **CI 等价 Linux 复跑已完成**（2026-09-22）：`git clone --depth 1` + `git apply` 在途补丁 + `uv venv --python 3.12` + `pip install -e ".[dev]"`（无 `.env`）→ **2197 passed / 17 skipped / 18 deselected / 0 failed**（skip 差异为平台标记；Windows 口径 2210 / 9）。
- **`agent_error` 的 message 不做路径净化**（评审 W-6）：上游 `HeAgentError.message` 当前全为固定串，评审未找到可达反例；已在 `_client_error_message` docstring 标明「若出现带路径的上游文案，净化必须加在这里」。


