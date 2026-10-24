# Story 54-2 · 依赖与配置面

状态：**planned**

## 范围

按 `epics.md` Story 列表行交付；冻结决策见 `../brief.md` D4 / D6 / D7 / D9。只交付依赖声明、配置旋钮与
uvicorn 参数接线——**不注册 WS 路由**（端点属 54-3）。

## 交付物

- `pyproject.toml`（`http` extra，当前 `:64-67`）：追加 `websockets>=13.0,<18`。
  - 下界取 uvicorn `standard` extra 自身 floor（`Requires-Dist: websockets>=13.0`，2026-10-23 实测其 METADATA），
    上界按仓库口径「下一大版本」；
  - 仍是**直接声明**（AD-11 同口径），不依赖 uvicorn 的传递依赖；
  - 注释写清用途：uvicorn 的 WS 协议实现需要它；缺它时 WS 升级回 404（探针实测），HTTP 不受影响。
- `src/heagent/config/__init__.py`：新增 `http_ws_max_connections: int = Field(default=16, ge=1)`，
  注释记录 D6 的两条依据：① WS 连接**不受** uvicorn `limit_concurrency` 约束（该额度只在 HTTP 协议实现里判）；
  ② 独立于 `http_max_subscribers` —— 共享池会让 WS 吃掉 SSE 额度并污染 `subscriber_count` 语义。
- `src/heagent/network/http_server.py`：`HttpServerConfig` 增 `ws_max_connections: int = Field(default=16, ge=1)`。
- `src/heagent/cli/http.py` 四处接线（对标 `--max-subscribers` 的既有形状）：
  `build_server_config(..., ws_max_connections=None)`（`:66-120`）、`HttpServerConfig(...)` 传参、
  `http_server_cmd` 形参（`:360-380`）、click 选项 `--ws-max-connections`（`:290` 旁）。
  **默认值取自 `Settings`**，CLI 显式值优先（`build_server_config` 不写回 Settings 单例，既有口径不变）。
- uvicorn 接线（`HttpServer.start()` 的 `uvicorn.Config(...)`，`http_server.py:1888` 附近）：
  `ws_max_size=WS_MAX_FRAME_BYTES`（64 KiB，D9）、`ws_ping_interval=WS_PING_INTERVAL_SECONDS`（15.0，D7）、
  `ws_ping_timeout=WS_PING_TIMEOUT_SECONDS`（20.0）；常量从 `ws_protocol` 导入，不在 `http_server` 里写裸数字。
- 缺依赖留痕：`start()` 后若 `server.config.ws_protocol_class is None`，记一条
  `WARNING http event=ws_unavailable`（含安装提示），每个进程一次；**不得**因缺 `websockets` 而拒绝启动 HTTP。
- `.env.example`：补 `HTTP_WS_MAX_CONNECTIONS`（注释说明「per-run WS 连接上限；超额收 `rate_limited` 错误帧」）。

## 验收标准（每条都要有判据）

1. `pyproject` 的 `http` extra 含 `websockets`，且上下界 **双向断言**（`>=13.0` / `<18`）；断言它不在
   `dev` / 其它 extra 里被重复声明。
2. `Settings.http_ws_max_connections` 默认 16、`ge=1`；`HttpServerConfig.ws_max_connections` 默认与 `Settings`
   **相等**（判据直接比较两处默认值，防漂移）；`0` / 负数被拒。
3. `build_server_config(settings)` 无参调用时取 `Settings` 值；显式传参覆盖；`Settings` 单例**不被写回**
   （既有判据 `test_build_server_config_does_not_mutate_settings` 同口径，若不存在则新增）。
4. `--ws-max-connections` 出现在 `heagent http-server --help` 里，`type=click.IntRange(min=1)`；CLI 值最终进
   `HttpServerConfig`（用 CliRunner + 替身断言，不真起服务）。
5. `catalog.classify("HTTP_WS_MAX_CONNECTIONS")` → `listening_surface` / 不可写（既有 `HTTP_*` 模式行覆盖）：
   判据同时断言它**不在** `whitelist()`、**不在** `RESOURCE_CEILINGS`（`HTTP_*` 面不进配置写白名单的既有立场）。
6. `.env.example` 文档判据全绿：`tests/test_config.py` 的「每个 Settings 字段都在 `.env.example` 里」用例通过。
7. uvicorn 参数接线判据：读出 `HttpServer` 内部的 `uvicorn.Config`，断言 `ws_max_size == 64 * 1024`、
   `ws_ping_interval == WS_PING_INTERVAL_SECONDS == SSE_HEARTBEAT_SECONDS == 15.0`、`ws_ping_timeout == 20.0`。
8. 缺依赖不崩：用替身把 `server.config.ws_protocol_class` 置 `None`，断言 `start()` 正常完成、`/api/health` 可服务、
   且日志里出现**一条** `ws_unavailable`（不重复刷）。
9. `src/` 内**零** `import websockets`（服务端走 uvicorn；客户端库只允许测试用）——防止把可选依赖变成模块级硬依赖。
10. 变异体精确变红（脚本 `.heagent/tmp/epic54/neg_54_2.py`）：① 默认值改成与 SSE 池共享（判据 2 红）；
    ② CLI 传参不覆盖 Settings（判据 3/4 红）；③ `ws_max_size` 用 uvicorn 默认 16 MiB（判据 7 红）；
    ④ 缺依赖时抛异常（判据 8 红）；⑤ 把 `websockets` 加进 `dev` 而非 `http`（判据 1 红）。

## 任务

- [ ] `tests/network/test_http_ws_config.py`（判据 1–3、5、7–9）+ 扩 `tests/test_cli_http.py`（判据 4）
- [ ] 改 `pyproject.toml` / `config/__init__.py` / `http_server.py` / `cli/http.py` / `.env.example`
- [ ] `pip install -e ".[dev,http]"` 后实跑判据；登记安装后 `websockets` 版本
- [ ] 变异体脚本实跑并记录

## 验证命令（规划，执行时亲跑并登记实测）

```bash
pip install -e ".[dev,http]"
pytest tests/network/test_http_ws_config.py tests/network/test_http_server.py tests/test_cli_http.py \
       tests/test_config.py tests/test_config_catalog.py -q
ruff check src tests && ruff format --check src tests
mypy src
```

## 风险与口径

- **不把 `websockets` 加进基础依赖**：基础安装（库用法 / 其它子命令）不需要它；只有提供 WS 服务时才需要。
- uvicorn 的 `ws=` 选择保持默认 `auto`（实测选中 `websockets-sansio`）：**不钉 `ws="websockets"`**（该实现已
  `UvicornDeprecationWarning`，且关闭握手信封能力不是本 epic 依赖的路径，见 brief D4）。
- 若未来 uvicorn 把 `auto` 改指向别家实现（`wsproto` 等），握手拒绝形态仍应保持「裸 403 / 错误帧」两条路径可用：
  54-3 的判据不得假设 `send_denial_response` 可用。
