---
ticket: 4
ref: 76.4
code: E76-S04
epic: epic-76-remote-surface-closeout
risk: low
hitl: false
covers: ["R6"]
status: done
---

# E76-S04 · external 档非 docker 沙箱启动 WARNING：恰 1 条锚点、不改变启动成败

## Tasks & Acceptance

- [x] `cli/http_config.py` 新增 `_warn_external_without_sandbox(config, sandbox_backend) -> str | None`（紧跟 `_check_tls_identity`，同属启动自检族）：仅当 `config.mode == "external"` 且后端不是 `docker` 时返回一条正文，其余情况 `None`。判据取**启动期实际生效**的后端（`auto` / daemon 不可用会降级）。
- [x] `build_ws_servers` 新增 `sandbox_backend: str | None = None` 形参（缺省回落到 `settings.sandbox_backend`），在装配点打**一条** `ws event=external_without_sandbox listener=external sandbox=<backend> host=<host>…`（`safe_log`）。
- [x] `cli/http.py`：`_ws_access_note(config, sandbox_backend=None)` 在对外 + 非 docker 时**收尾括号前**追加 `; sandbox=<backend>: remote runs execute on the HOST`（既有三段文案逐字不变）；`EmbeddedHttpService` 记住注入的生效后端并在两处公告带上它。
- [x] 两条装配路径都注入生效后端：`build_http_service` 用 `_effective_sandbox_backend(executor) or executor.sandbox_backend`；`http_server_cmd` 用 `_effective_sandbox_backend(handler) or sandbox or settings.sandbox_backend`。
- [x] 判据（`tests/test_cli_http_lifecycle.py` 新增 3 例）：external + `passthrough` ⇒ 该锚点 WARNING **计数 == 1** 且行内含 `listener=external` 与 `sandbox=passthrough`；external + `docker` ⇒ **0 条**；两例 `build_ws_servers` 都正常返回 listener（不是闸门）。第三例钉 `_ws_access_note` 的追加口径（既有文案逐字不变、本地 listener 不追加）。
- [x] 写集严守票面：`src/heagent/cli/http_config.py` / `src/heagent/cli/http.py` / `tests/test_cli_http_lifecycle.py` + 本 plan。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_cli_http_lifecycle.py -q` | **17 passed**（原 14 + 新 3） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network tests/test_cli_http_lifecycle.py tests/test_cli_http.py tests/test_architecture_contracts.py -q` | **836 passed, 1 warning** |
| `grep -c "listener=external"`（告警正文） | 1（单条锚点，行内同时含 `sandbox=`） |
| `.heagent/tmp/py311-venv-linux/bin/python -m ruff check src tests` / `ruff format --check src tests` / `mypy src` | 全绿（506 files / 240 source files） |

## Code Map

| 文件 | 改动 |
|---|---|
| `src/heagent/cli/http_config.py` | 新增 `_DOCKER_BACKEND` / `_warn_external_without_sandbox()`；`build_ws_servers(sandbox_backend=…)` 形参 + 装配点单条 `safe_log`；docstring 补口径 |
| `src/heagent/cli/http.py` | `_ws_access_note(config, sandbox_backend=None)` 追加句；`EmbeddedHttpService.__init__(sandbox_backend=…)` + 两处公告传参；两条装配路径注入生效后端 |
| `tests/test_cli_http_lifecycle.py` | +3 例：外部非 docker 恰 1 条 / docker 0 条 / 访问口径追加 |

## Design Notes

1. **提示不是闸门**（R6 / NG7）：只在启动期喊一条，退出码与启动成败不变——用例把「`build_ws_servers` 正常返回 listener」写进断言，防止后来者把告警升级成拒绝启动。
2. **判据取生效后端，不取请求值**：`--sandbox` / `SANDBOX_BACKEND` 只是请求（`auto` 或 daemon 不可用会降级成 `passthrough`）。入口层用 `_effective_sandbox_backend(executor|handler)` 取引擎构造期定下的 `effective_backend`，取不到才回落配置值——与状态面（`/api/status` 的 `sandbox_backend`）同源。
3. **为什么同时改访问口径公告**：日志里的 WARNING 只有运维看，stderr 的访问说明是使用者第一眼看到的。只讲「Bearer token required」不讲「跑在宿主」会漏掉真正决定风险等级的那一半（容器是唯一 OS 级边界，`docs/framework.md` §4.18）。
4. **测试怎么造对外配置**：`WS_AUTH_TOKEN` 只读用户级 `setting.md`（项目 `.env` 不参与，D3 的 fail-closed 设计），所以用 `monkeypatch.setattr(Settings, "_user_setting_file", tmp_setting_md)` 指一份带 frontmatter 的临时文件，再 `reset_settings()`；不真绑定端口（只构造 listener）。
