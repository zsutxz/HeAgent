# tests/fixtures/ — 测试数据集中宿

`tests/` 树内所有**静态测试数据**的唯一存放点。守卫：`tests/test_fixtures_contract.py`
（`tests/` 下任何非 `.py` 文件必须住 `fixtures/` 内，散落即红并点名）。

## 数据域

| 目录 | 内容 | 消费方 / 再生方式 |
|------|------|------------------|
| `ws_tls/` | 自签 TLS 证书/私钥（**测试专用，非凭证**；CN=localhost） | `tests/network/test_ws_e2e.py`、`test_ws_auth.py`、`test_ws_server.py`；详情见 `ws_tls/README.md` |
| `contract_baselines/` | 四份契约基线 JSON（public_exports / transport_routes / exception_types / transport_errors） | `scripts/contract_snapshot.py --check`（CI 直跑）+ `tests/test_contract_baselines.py`；再生：`python scripts/contract_snapshot.py --write` |
| `js/` | node 探针（最小 DOM 替身）与真浏览器验收驱动 | `tests/test_http_web_ui.py`（探针进 CI）；`console_acceptance.mjs` 仅手动跑（裁定见 `docs/frame.md` §已知缺口） |

## 约定

- **新增数据**：一律放 `tests/fixtures/<域>/`，域目录小写，配 `README.md` 说明来源与再生方式（`ws_tls/` 为先例）。
- **引用方式**：模块级常量经 `Path(__file__)` 锚定（如 `Path(__file__).resolve().parents[2] / "tests" / "fixtures" / ...`）；测试体内优先注入 conftest 的 `fixtures_dir` fixture。禁止裸的 CWD 相对字符串（`"tests/fixtures/..."`）——pytest 从其他目录启动即断。
- **运行期残留不是数据**：`tests/.heagent/`（goal 测试运行产物，gitignore 覆盖）与 `__pycache__/` 不进 fixtures/，契约测试已排除。
