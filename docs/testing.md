# 测试与门禁判读说明

> 目的：让「门禁红了」这件事有**可执行的分诊流程**，而不是每轮靠记忆判断「这条大概是环境噪声」。
> 归属：`tests/` 的组织与标记口径见 `AGENTS.md`「扩展与测试约束」；本文件只讲**怎么跑、怎么判**。

## 一、本地全门

```bash
python scripts/quality_gate.py     # 六门：goal 冒烟 → 全量回归 + 覆盖率 87% → ruff lint →
                                   #       ruff format --check → mypy → bandit -ll（fail-fast）
```

分项复跑（定位失败时用）：

```bash
pytest -q --ignore=tests/test_cli_http_lifecycle.py   # 全量回归（快，不带覆盖率）
pytest --cov --cov-report=term-missing                # 覆盖率
ruff check src tests && ruff format --check src tests
mypy src && mypy src --platform linux                 # 本地双跑：CI 在 ubuntu 上跑，平台相关告警不同
bandit -r src/ -ll
```

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

## 五、容器 / 沙箱环境下取证

- 本仓可能在容器沙箱里被驱动（`shell` 的每条命令是独立一次性容器）：临时产物放工作区的
  `.heagent/tmp/`（宿主盘、跨命令持久），**不要**放 `/tmp`（每条命令都会丢）。
- 缺依赖时用项目自己的 dev 环境或一次性 venv（`pip install -e ".[dev,http,gui]"`），不要用系统 Python
  硬跑后把 `ImportError` 当作「测得绿」。
- 需要真实 LLM / 外部网络的用例走 `-m integration`，不进基线。
