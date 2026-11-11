# 测试与门禁判读说明

> 目的：让「门禁红了」这件事有**可执行的分诊流程**，而不是每轮靠记忆判断「这条大概是环境噪声」。
> 归属：`tests/` 的组织与标记口径见 `AGENTS.md`「扩展与测试约束」；本文件只讲**怎么跑、怎么判**。

## 一、本地全门

```bash
python scripts/quality_gate.py     # 七门：契约快照 → goal 冒烟 → 全量回归 + 覆盖率 87% → ruff lint →
                                   #       ruff format --check → mypy → bandit -ll（fail-fast）
```

> 第 0 门 `contract snapshot`（2026-11-11 起）守 INV-1/INV-2/INV-3/INV-8：公共导出面、传输路由表
> （HTTP `Route` **与** WS `WebSocketRoute`）、异常类型集合、传输错误码与错误信封键集共四份基线的漂移；
> 单次约 0.4 s。红了先跑 `python scripts/contract_snapshot.py --check` 看 diff。
>
> 四份基线：`public_exports.json` / `transport_routes.json` / `exception_types.json` /
> `transport_errors.json`。`transport_errors.json` 每个错误码一项（`status` / `code` / `keys`），
> `status` 有值为「能静态确定」（来源见 `status_source`：集中表 `_CONSOLE_ERROR_STATUS` 或
> `_json_error(..., status_code=N)` 调用点），`null` + `status_source="unmapped"` 表示枚举里有、
> 网络层无静态可确定出口 —— **不猜值**，该清单即 `unmapped_codes`。
> `--print --only <kind>` 打印当前快照不落盘，供子集/棘轮类守卫读现状。

分项复跑（定位失败时用）：

```bash
pytest -q --ignore=tests/test_cli_http_lifecycle.py   # 全量回归（快，不带覆盖率）
pytest --cov --cov-report=term-missing                # 覆盖率
ruff check src tests && ruff format --check src tests
mypy src && mypy src --platform linux                 # 本地双跑：CI 在 ubuntu 上跑，平台相关告警不同
bandit -r src/ -ll
```

### 实测耗时基线（2026-11-11 起维护）

> `scripts/quality_gate.py:10` 的 `GATE_TIMEOUT_SECONDS = 900` 是**门限常量**，不是实测耗时。
> 下表记录真实墙钟，用于判断「这次是不是异常变慢」。

| 日期 | HEAD | 命令 | wall clock | 备注 |
|---|---|---|---|---|
| 2026-11-11 | `ec387f0` | `python scripts/quality_gate.py`（PATH 前置 py311 venv） | **316 s** | 七门全绿（含第 0 门契约快照）；bandit Medium 0 / High 0、Low 8；覆盖率门通过 |
| 2026-11-11 | `ec387f0` | `pytest tests/test_agent_loop.py -q` ×5 取中位数 | **20.8 s** | 曳光弹；单次区间 20.6–21.2 s |
| 2026-11-11 | `ec387f0` | `pytest -m "not integration and not benchmark" -q` | **200 s** | 全量回归单独跑：4296 passed / 50 skipped / 25 deselected |

判读口径：

- 全门 310 s 相对 900 s 门限余量约 **2.9×**；某次显著超过 ~600 s 时，先怀疑环境（9p 挂载 / 容器冷启动 / 依赖重装）而非回归。
- 曳光弹 20.8 s 是「改一轮代码后最快拿到反馈」的时间尺度；单条 story 的验证优先跑它而不是全门。
- 容器内跑必须 `export PATH=<venv>/bin:$PATH`，否则 `quality_gate.py` 在 ruff 门直接失败（`ruff: not found`）。

## 二、红了怎么办：先证明「是不是我弄红的」

**先跑基线复跑脚本**，而不是先读代码：

```bash
python scripts/verify_baseline.py tests/test_cli_http_lifecycle.py -q
```

它做的事：`git worktree add --detach <临时目录> HEAD` → 在**干净的 HEAD 副本**上用当前解释器跑同一批
用例 → 打印两边结论 → 清理 worktree。判读规则：

| 现象 | 结论 | 处置 |
|---|---|---|
| 工作区红 + 基线**同样红** | 环境产物（与本次改动无关） | 在汇报里写明「基线复跑同样红」并钉住命令与数字；不要改代码去迁就 |
| 工作区红 + 基线**绿** | 本次改动引入的回归 | 必须修，不能靠 marker / skip 掩盖 |
| 基线跑不起来（缺依赖 / worktree 失败） | 脚本自身失败（exit 2） | 先解决取证环境，**不得**把「跑不起来」当成「基线绿」 |

为什么用 worktree 而不是 `git stash`：本仓可能被多个会话并发编辑（见 `AGENTS.md` 与
`_bmad-output/implementation-artifacts/deferred-work-archive.md`），`stash` 会动工作区、影响别人；
`worktree add --detach` 只读 HEAD，用完即删。

## 三、标记（marker）口径

| marker | 含义 | 默认是否运行 |
|---|---|---|
| `embedded_http_service` | 用**真实** HTTP/WS 服务与随机端口（退出 `tests/conftest.py` 的默认替身） | 运行 |
| `integration` | 真实外部依赖 E2E（需凭据 / 网络） | 不运行（`pytest -m integration` 显式） |
| `benchmark` | 性能基准 | 不运行（`pytest -m benchmark --benchmark-autosave …`） |
| `no_auto_workspace` | 路径安全测试不自动设 workspace root | 运行 |

写「端口已释放」类断言时用 **connect 判据**（未监听 ⇒ `ECONNREFUSED`），不要用 `bind`：服务关闭后
同四元组的 TIME_WAIT 会让 `bind` 报 `EADDRINUSE`（Linux 要 `SO_REUSEADDR` 才能立刻重绑，Windows 的
`SO_REUSEADDR` 又会允许抢占别人的端口 ⇒ 两头都不可靠）。历史实例见下节。

## 四、历史噪声记录（已修，勿重复归因）

| 日期 | 现象 | 根因 | 处置 |
|---|---|---|---|
| 2026-10-24 | `tests/test_cli_http_lifecycle.py` 三条「端口已释放」探针在 WSL2 / 容器上恒红（`OSError: [Errno 98] Address already in use`） | 探针用 `bind` 判定，撞上关停后的 TIME_WAIT（正常 OS 行为，不代表端口仍被监听） | 探针改为 `connect` 判据（`_assert_port_free`）；修复后该文件 **10 passed**。此前三个周期都把它当环境噪声，属**判据缺陷**而非环境限制 |

## 五、用例分层（L0–L3，2026-11-11 起）

> 目的：让「改一轮代码该跑哪一层」有统一口径，而不是每次凭感觉决定跑全量还是只跑一个文件。
> 各层耗时取自 `docs/testing.md` 上文的实测基线。

### L0 契约守卫（秒级，改任何代码都先跑）

```bash
python scripts/contract_snapshot.py --check          # 四份基线：公共导出面 / 传输路由 / 异常类型 / 传输错误码
pytest tests/test_contract_baselines.py tests/test_architecture_contracts.py -q
```

判据：全绿才继续；快照红了先看 diff 判断「有意变更（重生基线）」还是「意外漂移（改代码）」。

### L1 快速单文件（10–30 秒）

```bash
pytest tests/test_agent_loop.py -q      # 曳光弹，实测中位数 20.8 s
pytest <你改动对应的测试文件> -q
```

判据：单条 story 的实现循环默认停在这一层。

### L2 全量回归（约 200 秒）

```bash
pytest -m "not integration and not benchmark" -q
```

判据：一个 Sprint 收口、或改动触及跨模块契约时必跑。

### L3 重活（分钟级，默认不进基线）

```bash
pytest -m integration -q        # 需真实 LLM / 外部网络
pytest -m benchmark -q          # pytest-benchmark
python scripts/quality_gate.py  # 七门全门，实测 316 s
```

判据：提交前、或改动了门禁/依赖/覆盖率相关文件时必须跑；容器内需先把 venv 的 `bin` 前置进 `PATH`。

## 六、容器 / 沙箱环境下取证

- 本仓可能在容器沙箱里被驱动（`shell` 的每条命令是独立一次性容器）：临时产物放工作区的
  `.heagent/tmp/`（宿主盘、跨命令持久），**不要**放 `/tmp`（每条命令都会丢）。
- 缺依赖时用项目自己的 dev 环境或一次性 venv（`pip install -e ".[dev,http,gui]"`），不要用系统 Python
  硬跑后把 `ImportError` 当作「测得绿」。
- 需要真实 LLM / 外部网络的用例走 `-m integration`，不进基线。
