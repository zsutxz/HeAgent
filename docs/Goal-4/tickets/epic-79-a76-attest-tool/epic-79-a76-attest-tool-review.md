---
type: review
code: E79-R
epic: epic-79-a76-attest-tool
lenses: ["规格对账", "不变量与守卫反脆弱", "三镜头对抗（契约 / 并发 / 文档）"]
reviewed_at: 2026-11-24
head: 767f54b2
verdict: 通过
---

# E79 收口三审（单文档 · 三镜头）

> 形态：用户 2026-11-24 裁定「三审合并为一个文档」⇒ 三镜头写在同一份报告里（与 E78 同形）。
> 本轮**不新增 A 号**、不动台账计数：A76 仍是一件事（客户端 pin 未交付），E79 只把它服务端侧机器化。

## 范围

对象 = **未提交工作树**（`HEAD 767f54b2` + 8 项改动）：E79 两条 entry 的脚本 / 判据 / 台账操作卡 /
`AGENTS.md` 工具链指针，以及票树与 `progress.md` 的记账。

| 命令 | 结果 |
|---|---|
| `pytest tests/test_ws_tls_attest_script.py -q` | **11 passed**（三审前 7 → 落改后 +4） |
| `pytest -q`（全量，带 node v20.18.1） | **5924 passed / 17 skipped / 30 deselected / 1 xfailed / 0 failed**（336s） |
| `pytest tests/test_deferred_id_registry.py tests/test_docs_links.py tests/test_architecture_contracts.py tests/test_ws_tls_attest_script.py tests/test_release_workflow_contract.py -q` | **72 passed / 1 skipped** |
| `ruff check src tests scripts examples` / `ruff format --check`（553 files） | All checks passed / already formatted |
| `mypy src`（242 files） | Success: no issues found |
| `bandit -r src/ -ll` | 无新增（仅 4 处已知 `nosec` 伴生噪声） |
| `python scripts/contract_snapshot.py --check` | 五份全 `[OK]`（零基线漂移） |
| `python -m mkdocs build --strict` | exit 0（7.48s，0 WARNING） |
| `python scripts/ws_tls_attest.py`（默认生产姿态） | ①②③④ `[OK]` + ⑤ 跳过，**exit 0** |
| `python scripts/ws_tls_attest.py --self-check --cert tests/fixtures/ws_tls/cert.pem --key tests/fixtures/ws_tls/key.pem` | 四段 `[OK]`，**exit 0** |

## 镜头一 · 规格对账

| 规格条目 | 判据 | 实测 | 判定 |
|---|---|---|---|
| R1 四段逐段 `[OK]/[FAIL]` | 真跑 + 自检 | 生产姿态四段 `[OK]`；自检四段 `[OK]` | ✅ |
| R1 ① 绑定面 + 「默认在被测地址非回环时加 `127.0.0.1:<port>`」 | 真跑 | `192.168.2.226:9201 OPEN` + `127.0.0.1:9201 REFUSED（如预期）` | ✅ |
| R1 ② 握手不校链不校主机名 | 代码 | `CERT_NONE` + `check_hostname=False`（信任锚是 pin） | ✅ |
| R1 ③ 三格式 pin | 真跑 | `247a8b…fd301` / `ER5I-WJUT-A7JP` / `sha256/JHqLJpMH…UP0wE=`，与 `heagent tls fingerprint` 同源（同一 `certificate_info`） | ✅ |
| R1 ④ 无 token 期望 403；`--token` 追加验 101 | 真跑 + 自检 | 生产姿态 `无 token → HTTP/1.1 403 Forbidden`；自检 `带 token → 101` | ✅（真机 101 见 L-4） |
| R1 ⑤ 可选 `--status-url` 比对 `tls.spki_sha256` | 判据 + 字段对读 | `StatusResponse.listeners[].tls.spki_sha256`（`http_protocol.py`）与脚本读法逐字一致；缺指纹判红 | ✅ |
| R1 退出码 `0/1/2` | 子进程实测 | 自检 0 / pin 漂移 1 / 材料缺失 2 / 未监听 2 / 暴露面漂移 1 / 非法参数 2 | ✅ |
| R1 token 只进请求头 | 静态断言 + 真跑 | `--token SELFSECRET-DO-NOT-PRINT` 全输出 0 命中，只报「已提供（长度 23）」 | ✅ |
| R1 stdlib only、只读探针 | 代码 + 行为 | 仅 `ssl`/`socket`/`urllib` + 仓内 `network.*`；不建会话、不提交 run、不落盘 | ✅ |
| R2 A76 操作卡收成一条命令 | 正文对读 | 卡片三行关键期望输出与真跑逐字一致（`REFUSED（如预期）` / `对端 SPKI == 本地 cert.pem：247a8b…` / `无 token → HTTP/1.1 403 Forbidden`） | ✅ |
| R2 `AGENTS.md` 工具链补该脚本 | 正文对读 | `heagent tls` → `ws_tls_attest.py` → `ws_manual_probe.py` 顺序正确 | ✅ |
| R2 不新增 A 号 / 计数与速读节不变 | 台账守卫 | `test_deferred_id_registry.py` 全绿；仍 4 条 / `A55 A65 A67 A76` | ✅ |

**镜头一发现：0 条**（无「规格说要、代码没做」的空洞；四处实质问题由镜头二的反证挖出）。

## 镜头二 · 不变量与守卫反脆弱

### 发现 M-1（Medium，已落改）暴露面漂移被误报成「服务未在监听」

- 位置：原 `scripts/ws_tls_attest.py::_run`——`if not bind_seg.ok:` 一律 `exit 2` + 「未在监听」文案。
- 后果：`_Segment.fail` 同时承担「连不上」与「期望拒绝却 OPEN（暴露面漂移）」两种语义，后者被报成
  **前提缺失**——而这正是本工具存在的理由（生产姿态下回环腿必须消失）。真出现漂移时，使用者会收到
  「服务没起，先启动服务」的误导文案与错的退出码。
- 处置：`_segment_bind` 返回 `(seg, reachable)`；`_run` 只把 `reachable=False` 当 `2`，漂移落回统一
  `all(ok)` → `1`。新判据 `test_bind_drift_is_a_judgement_failure_not_a_missing_precondition`。

### 发现 M-2（Medium，已落改）IPv6 脱括号自写第四份实现

- 位置：原 `_split_host_port` 的 `host.strip("[]")`。
- 违的线：`network/exposure.py::unbracket_host` 的 docstring 明写「脱括号规则只有这一处实现」，
  且语义不同——`unbracket_host("[localhost]")` 保留原样，`strip("[]")` 会剥成 `localhost`（随后
  既不算回环也不算非法，按暴露处理）。配置面 / SAN 判定都走前者，脚本走后者即口径分叉。
- 处置：改走 `unbracket_host`；IPv6 判据追加 `[localhost]:9201 → ("[localhost]", 9201)` 一条断言。

### 发现 M-3（Medium，已落改）第 ⑤ 段从渲染文案反解析指纹

- 位置：原 `_run` 的 `expected = pin_seg.details[0].rsplit("：", 1)[-1] if pin_seg.ok else ""`。
- 后果：① 改一句人读文案（例如把 `：` 换成 `:`）就静默比对错值；② 无叶证书时 `expected=""`，
  `"" in seen` 的空串语义让判据形状可疑（且这段完全没有判据覆盖）。
- 处置：`_segment_pin` 显式返回 `(seg, remote_sha)`；`_segment_status` 新增「没拿到指纹 → 判红」
  早退。新判据 `test_the_status_segment_compares_the_pin_passed_in`（本地 `http.server` 供 JSON，
  覆盖命中 / 漂移 / 缺指纹三种形态）。

### 发现 M-4（Medium，已落改）材料不可解析与参数非法都退化成 traceback

- 实测：`--cert tests/fixtures/tls/not-a-cert.pem` → `TlsIdentityError` 未捕获、栈回溯、**rc=1**
  （应 `2`）；`--refused no-port` → `ValueError` 未捕获、栈回溯、**rc=1**（应 `2`）。
- 后果：退出码契约被破坏，使用者看到的是 Python 栈而不是「材料坏了 / 参数写错了」。
- 处置：`_local_spki_sha()` 兜 `TlsIdentityError`/`OSError`；`_run`/`_run_self_check` 前置解析材料，
  `--refused` 解析失败打印「参数错误」并 `2`。新判据两条（材料不可解析 / `--refused` 非法），
  均断言输出无 `Traceback`。

### 记录不改（Low）

- **L-1（已落改，顺手）** `_tls_handshake` 的 `tls.cipher()[0] if tls.cipher() else "?"` 双调且丢收窄
  （`mypy scripts/` 报 `index`）；改为局部 `cipher_info`。
- **L-2（已落改，顺手）** `_segment_status` 的 `payload.get("ws_listeners")` 是不存在的别名
  （`StatusResponse` 只有 `listeners` 且 `extra="forbid"`）⇒ 幻影第二真源，删 fallback。
- **L-3（记录不改）** `EXPIRY_WARNING_DAYS = 7` 与 `cli/http_config.py::TLS_EXPIRY_WARNING_DAYS` 重复。
  导 `cli` 会把 click / settings 拖进「宿主裸 `python` 可跑」的脚本入口，权衡下保留常量 + 注释互指。
- **L-4（记录，环境限制）** 真机「带**正确** token → 101」在本容器不可验：`WS_AUTH_TOKEN` 在用户级
  `~/.heagent/setting.md`，容器内不可见；用假 token 实测 403（判红路径成立），101 分支由 `--self-check`
  的 stub 覆盖 ⇒ 服务端侧无未验分支，只差一次宿主带真 token 的复跑。
- **L-5（记录不改）** 工具只打印协议版本、不判下限。下限由 uvicorn 的默认 SSLContext（OpenSSL 策略
  ≥ TLS 1.2）兜底，仓内没有第二处版本配置可漂移；给工具加下限判定等于把 uvicorn 默认值抄成第二真相。

### 注入反证（七条，逐条「红 → 复原 → 绿」）

| # | 守卫 | 注入 | 结果 |
|---|---|---|---|
| A | `test_ipv6_literal_addresses_are_split_without_the_brackets` | `_split_host_port` 退回 `strip("[]")` | **1 failed** |
| B | `test_bind_drift_is_a_judgement_failure_not_a_missing_precondition` | `if not reachable:` 改回 `if not bind_seg.ok:` | **1 failed** |
| C | `test_unparseable_local_material_exits_with_the_precondition_code` | 去掉 `_local_spki_sha` 的 `try/except` | **1 failed** |
| D | `test_a_bad_refused_argument_exits_with_the_precondition_code` | 去掉 `--refused` 的 `try/except` | **1 failed** |
| E | `test_the_status_segment_compares_the_pin_passed_in` | 删掉「缺指纹判红」早退 | **1 failed** |
| F | `test_the_token_is_never_interpolated_into_an_output_line` | 段 ④ 的 note 改成 `{token}` | **1 failed** |
| G | `test_self_check_passes_against_the_fixture_material` | stub 的 `if b"authorization:" in data.lower():` 改 `if True:` | **1 failed** |

复原后 `pytest tests/test_ws_tls_attest_script.py -q` → **11 passed**。

## 镜头三 · 三镜头对抗（契约 / 并发 / 文档）

- **契约面**：不新增错误码、不动帧面、不动 `/api/status` 字段——脚本只**读**
  `listeners[].tls.spki_sha256`（与 `http_protocol.py` 的 `StatusResponse` / `TlsIdentityInfo` 逐字对读，
  `extra="forbid"` 保证不会读出不存在的键）；`contract_snapshot --check` 五份 `[OK]`、零 diff。
  新增的 `_local_spki_sha` 等属脚本内部函数，不进 `heagent` 包面 ⇒ 无需同步 pub 白名单或基线。
- **并发面**：① 自检 stub `bind(("127.0.0.1", 0))` 取临时端口，测试并行不撞固定端口；② stub 线程
  daemon，`listener.close()` 后 accept 抛 `OSError` 即退，最坏情况随进程退出（不阻塞 CLI）；
  ③ 探针「一次连接 → 读状态行 → 关闭」，不进帧循环，不制造残留连接；④ 测试里的
  `_closed_port()` 绑后即放，与被测进程无共享状态；⑤ `--timeout` 同时管连接与读，最坏路径有界。
- **文档面**：`AGENTS.md` 工具链一句与脚本 `--help` 的四段描述对读一致；A76 操作卡三行关键
  期望输出与真跑逐字一致（见镜头一）；`docs/tls-connect-guide.md` 经 `git check-ignore -v` 确认仍被
  `.gitignore:64` 排除 ⇒ 不入库、票面 write_set 不含它；epic 容器 `in-progress` / 两 entry `built`
  与 `progress.md` 记账一致。

### 发现 L-6（Low，记录不改）`_start_stub` 的 accept 线程不随 `listener.close()` 立刻退出

- 现象：关闭后线程可能仍阻塞在 `accept()`，直到进程退出（daemon）。
- 判定：自检是进程级一次性动作，退出即收；为「干净退出」再加唤醒机制会把 30 行的 stub 复杂化成
  另一个小服务器。记录不改。

## 落改清单（本轮 8 处）

1. `scripts/ws_tls_attest.py`：`_split_host_port` 改走 `network.exposure.unbracket_host`（M-2）。
2. `scripts/ws_tls_attest.py`：`_segment_bind` 返回 `(seg, reachable)`，`_run` 按可达性判 `2`、漂移判 `1`（M-1）。
3. `scripts/ws_tls_attest.py`：新增 `_local_spki_sha`，`_run` / `_run_self_check` 前置解析本地材料并区分
   「文件缺失」与「解析失败」（M-4）。
4. `scripts/ws_tls_attest.py`：`--refused` 预解析 + 「参数错误」→ `2`（M-4）。
5. `scripts/ws_tls_attest.py`：`_segment_pin` 返回 `(seg, remote_sha)`；第 ⑤ 段用显式值，缺指纹判红（M-3）。
6. `scripts/ws_tls_attest.py`：删 `ws_listeners` 幻影别名（L-2）；`tls.cipher()` 单次调用（L-1）。
7. `tests/test_ws_tls_attest_script.py`：+4 例（漂移判 `1` / 材料不可解析 / `--refused` 非法 / ⑤ 段显式指纹）
   + IPv6 例扩 `[localhost]` 口径断言 + `_module()` 复用取模块。
8. 记账：本 review 文档、epic Notes 指针、s01 的 Verification 计数（7 → 11）、`progress.md` 决策日志。

## 结论

| 镜头 | Critical | High | Medium | Low | 结论 |
|---|---|---|---|---|---|
| 一 · 规格对账 | 0 | 0 | 0 | 0 | 通过 |
| 二 · 不变量与守卫反脆弱 | 0 | 0 | **4** | **2 + 3** | 有条件的通过（4 条 Medium 当轮落改，2 条 Low 顺手落改，3 条记录不改；7 条注入反证全红→绿） |
| 三 · 三镜头对抗 | 0 | 0 | 0 | **1** | 通过（Low 记录不改） |

**总体：通过**。R1/R2 全部成立；四处 Medium 都是「工具会给出误导结论 / 破坏退出码契约」的实质缺陷，
已在提交前落改并有判据兜住；真跑生产姿态四段 `[OK]`、exit 0，与 A76 操作卡的期望输出逐字一致。
