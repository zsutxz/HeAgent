---
title: 'Story 63.7 建立测试数据管理机制'
type: test
ticket: 7
created: '2026-11-18'
status: built
baseline_revision: '0df59ad'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'tests/fixtures/'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `tests/` 树内静态测试数据散落三处、无统一宿与守卫：
`tests/contract_baselines/`（4 份契约基线 JSON，脚本/测试/变异脚本三面钉死）、
`tests/js/`（node 探针 + 真浏览器验收驱动）、`tests/fixtures/ws_tls/`（唯一已
集中的域）。引用面存在裸 CWD 相对字符串（`"tests/fixtures/ws_tls/cert.pem"`）——
pytest 从非仓库根启动即断。

**Verify：数据文件集中存放、相对路径引用、命名与文档清晰。**

## Design

**单一数据宿裁定**：`contract_baselines/` 与 `js/` 一并 `git mv` 进
`tests/fixtures/`（保留历史），fixtures/ 成为唯一数据宿，不留例外台账：

- **钉死点同步 7 处**：`scripts/contract_snapshot.py` BASELINE_DIR、
  `scripts/mutation/mutate_contract_snapshot.py`（copytree 源 + 基线路径 2 处）、
  `tests/test_contract_baselines.py` BASELINE_DIR、`tests/test_http_web_ui.py`
  `_PROBE`、`tests/fixtures/js/console_acceptance.mjs` 自述用法行、
  `docs/frame.md` §已知缺口路径行。CI 不受影响（ci.yml 直调脚本，路径在脚本内）。
- **引用约定**：全部裸 CWD 相对字符串改 `Path(__file__)` 仓库根锚定
  （ws_auth / ws_e2e / ws_server 三文件含故意不存在的 TLS 失败路径）；
  conftest 新增 session 级 `fixtures_dir` fixture 供测试体内注入。
- **机制守卫**：新增 `tests/test_fixtures_contract.py` 三判据——① tests/ 下非
  `.py` 文件必须住 fixtures/（`.heagent`/`__pycache__`/`.pytest_cache` 运行期
  产物排除），散落即红并点名；② `fixtures/README.md` 登记全部数据域；③
  `fixtures_dir` 解析正确且 ws_tls 材料在位。
- **机制文档**：`tests/fixtures/README.md`——三数据域（内容/消费方/再生方式）、
  新增数据流程、引用约定、残留排除口径。

**统计**：迁移数据文件 6 个（4 JSON + 2 JS）；改引用面 10 文件；新增 2 文件
（README + 契约测试）。

## Outcome

- `test_fixtures_contract + test_contract_baselines + test_http_web_ui`：
  150 passed。
- `tests/network`：503 passed + 1 红（`test_build_ws_server_config_maps_settings_
  and_overrides` 期望 9201 实得 9202——stash 对照干净 HEAD 同红，属本机 .env
  端口泄漏环境失败集，非回归）。
- 变异脚本真跑：2/2 变异体检出，VERDICT PASS（路径迁移后判据仍活）。
- ruff check / format / mypy 全绿。全量回归结论见提交附注。

</frozen-after-approval>
