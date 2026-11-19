---
title: 'Story 72.2 退役对外 listener 与 WS_EXTERNAL_* 配置族'
type: feature
ticket: 2
created: '2026-11-19'
status: done
baseline_revision: '9eb9410'
route: full
route_source: auto
risk: high
review: thorough
review_source: auto
lenses_ran: []
review_loop_iteration: 0
context:
  - 'src/heagent/config/__init__.py'
  - 'src/heagent/cli/http_config.py'
  - 'src/heagent/cli/http.py'
  - 'src/heagent/cli/doctor.py'
  - 'src/heagent/config/validation.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 第二 listener（`WS_EXTERNAL_*`，端口 `9301`）与第一步「`9201` 唯一内网入口」的形态冲突：
`.env` 里同时挂着 `WS_EXTERNAL_HOST=192.168.2.226`，同一地址出现两个入口，运维无从判断该连哪个。

**Approach:** 硬删除（无别名、无兼容层）：5 个配置键、3 个 CLI 选项、`build_external_ws_server_config` /
`_external_tls_files`、2 条 validation 判据、3 条 doctor findings、`scripts/setup_ws_external.py` 与其测试；
老 `.env` 的残留键由 `Settings` 的 `extra="ignore"` 静默吞掉，但 `doctor` 给一条 `doctor.retired_key` 提示。

## Boundaries & Constraints

**Always:**
- 老 `.env` 不得因残留键而启动失败（`extra="ignore"` 保持不动）。
- 残留键必须**可见**：`doctor.retired_key`（INFO）+ 迁移改法（`WS_HOST` + `WS_LAN_NO_AUTH` / `WS_AUTH_TOKEN`）。
- 文档与代码同批：`docs/frame.md` §4.17/§4.17.1/§4.18、`deploy/README.md`、`docs/faq.md`、`docs/errors.md`、
  `.env.example`、`CHANGELOG.md` 的 `## [Unreleased]`。

**Never:**
- 不留 `--ws-external-*` 别名、不做「配了就告警但仍生效」的兼容期。
- 不把 `readonly`（只读旁观）能力删掉——它退化为程序化装配字段，不再有配置键。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| OLD_ENV | `.env` 仍含 `WS_EXTERNAL_HOST` | 启动正常；doctor 给 `doctor.retired_key` INFO | 不阻断 |
| OLD_CLI | `--ws-external-host x` | usage error（未知选项），`--help` 不含该组选项 | exit 2（click） |
| SETTINGS | 反射 `Settings.model_fields` | 无任何 `ws_external_*` | 口径守卫测试红 |
| PORT | 运行期监听 | 无 `9301`（`.devcontainer` forwardPorts 同步去掉） | — |

</intent-contract>

## Code Map

- `src/heagent/config/__init__.py` — 删 5 个 `ws_external_*` 字段与注释块。
- `src/heagent/cli/http_config.py` — 删 `_external_tls_files` / `build_external_ws_server_config`；`build_ws_servers` 去掉三个参数与第二 listener 装配分支（注释同步为「恒 1 条」）。
- `src/heagent/cli/http.py` — 删 `--ws-external-*` 三选项与透传、`__all__` 里的 re-export；启动公告抽成 `_announce_ws_listeners()`（同时消掉 `http_server_cmd` 的 C901 16>15）。
- `src/heagent/config/validation.py` — 删 `_external_ws_host` / `_gate_ws_external_binding` / `_judge_ws_external_binding` 与 `REQUIRED_CHECK` 条目；`ws_auth_token` / `ws_tls_pair` 的对外分支删除。
- `src/heagent/cli/doctor.py` — 删三条对外 findings、`WS_EXTERNAL_PORT` 端口候选、`WS_EXTERNAL_TLS` 半配对；新增 `_RETIRED_WS_EXTERNAL_KEYS` + `doctor.retired_key`，并从通用 `doctor.env_unknown_keys` 里排除（避免重复报）。
- `src/heagent/cli/wizard.py` — 向导键 `WS_EXTERNAL_HOST` → `WS_LAN_NO_AUTH`。
- `.env.example` / `CHANGELOG.md` / `.devcontainer/devcontainer.json` / `deploy/README.md` / `docs/*` — 见上。
- 删除 `scripts/setup_ws_external.py`、`tests/test_setup_ws_external.py`。
- 测试改写：`tests/network/test_ws_server.py`（删 10 例外对用例）、`tests/test_cli_http.py`（删 3 例 CLI 覆盖用例 + help 断言）、`tests/test_cli_doctor.py`（删 3 例 → 换 lan/retired 用例）、`tests/test_config_validation.py`（对外判据换 lan 判据）、`tests/test_security_posture_contract.py`（谓词组 + 退役键不得回归）、`tests/test_architecture_contracts.py`（`test_dual_listener_docs_stay_in_sync` → `test_ws_entry_docs_stay_in_sync`）、`tests/test_cli_cron_echo.py`、`tests/test_cli_init_wizard.py`、`tests/test_devcontainer_contract.py`、`tests/test_cli_error_format.py`。

## Evidence

- `rg "WS_EXTERNAL" src/ scripts/` 仅命中 `doctor.py` 的退役键表与迁移文案（设计如此）；`rg "9301" src/` 空。
- 全量 `pytest -q` → 5466 passed / 52 skipped / 30 deselected / 1 xfailed（既有环境红 5 例随 `setup_ws_external` 测试一并消失）。
- `ruff check` / `ruff format --check` / `mypy src` / `bandit -r src/ -ll` / `mkdocs build --strict` 全绿。
