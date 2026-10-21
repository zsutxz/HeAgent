# Story 53-3 · 文档、契约与质量门

状态：**review**（2026-10-21）——全量质量门亲跑全绿，文档与契约同步完成，另闭合两笔**既有**
契约失守（台账计数 + 端口顺延用例，均经 HEAD 干净态复测确认先于本 story 存在）；
docker.io 直连 digest 验证因本机网络不可达如实挂起（见残余）。

## 交付物

- **判据 11（53-2 挂账闭合）**：`tests/test_sandbox_docker.py::test_sandbox_decision_full_chain_docker`
  ——`Settings → resolver → DockerRunner → SandboxDecision → executor 注入 → run 上下文元数据`
  全链替身判据：可用链（effective docker / 双隔离 True / 元数据同源）、bridge 档（网络隔离翻转 False）、
  不可用链（诚实降级 passthrough / 双隔离 False）。
- **`docs/frame.md` 同步（8 处）**：§4.4 新增 DockerRunner 段（形状 / 镜像 pin / 网络档 D2 /
  探测降级 / kill 清理 / 非绝对边界）；FR-2 分级行（container 档预留 → DockerRunner 落地，
  审批降级仍未接入=期二 D53-2）；配置表 3 行（`sandbox_backend` 增 docker 选档、新增
  `sandbox_docker_image`、`sandbox_network` 双后端语义）；已知缺口表 3 行（MCP/engine 边界行、
  Z-D24 行 2026-10-21 注、分级行更名「沙箱后端分级」）；目录树 sandbox/ 清单补 docker.py。
- **AGENTS.md 同步（3 处）**：裸跑声明补「容器档已落地、`--sandbox docker` 显式启用、默认链路
  未启用」；MCP 风险行补「Docker 后端不覆盖 MCP stdio——期二 D53-1」；核心立场行补兜底实施项口径。
- **「须 OS 级沙箱兜底」表述逐行复核**：立场行（4.6 dream / MCP 围栏 / approval / path_safety /
  env 豁免 / SandboxSession / HTTP 入口 / GUI 拉起面等）**维持原文不改**——要求仍真、事实未变，
  不扩大宣称；修订只落在事实变化处（上列 8+3 处）。
- **台账契约对齐（全量门逮住的既有失守，非 53-3 原计划）**：
  - `0e8a330`（2026-10-20）在总账活动区登记 A34–A36（挂起待裁定/待触发）后，四份文档仍宣称
    「活动 0 条」、契约测试仍强制恒零——政策已变、契约滞后。`tests/test_deferred_id_registry.py`
    改造：恒零判据 → **计数真实性**（各声明点声明值 == 活动区实际行数；actual≠0 时禁 0 声明）；
    活动区表形判据（4 列 + 表头计数诚实）；epic 台账计数 10 → 11。
  - epic-53 `deferred-work.md` 补 状态总览 表（D53-1/D53-2 挂起待触发）——44c5363 立项时缺表。
  - 四处计数声明刷新为 3 条：`consolidated-overview.md` `§17.4-A`（标题 + 正文）、
    `_bmad-output/README.md`、`retrospective-all-cycles.md` `§5.1`（标题 + 叙事补 2026-10-20 段）、
    `implementation-artifacts/README.md`。
- **端口顺延契约测试对齐（既有失守之二，a545613 漏改）**：
  `test_cli_http_lifecycle.py::test_bind_failure_fails_the_command_without_entering_the_cli`
  以 **env 端口**期待 fail-loud——那是 2026-10-15 端口顺延契约修订**之前**的语义。现行契约：
  env/自动端口被占时**顺延**继续服务；fail-loud 保留给显式 `--port`
  （`test_cli_http.py::test_explicit_port_is_never_silently_replaced` 钉住，默认 CLI 入口本无
  `--port`）。用例改写为 `test_env_port_conflict_drifts_instead_of_failing`：占用端口 → exit 0、
  run 正常完成、实际监听端口 > 被占端口。HEAD 干净态复测确认失败先于本 story 存在。
- **skills.py 格式化漂移（chore 单列）**：`tools/builtins/skills.py` 两处换行口径随本机
  ruff 0.16.6 漂移（上次落库 2026-10-13，与本 epic 无关），`ruff format` 机械修正。

## 验收证据（2026-10-21 亲跑）

- 全量 `pytest`（跳过 integration/benchmark）：**3740 passed / 14 skipped / 0 failed**（156.2s，
  本地 Py3.13 不带 cov——cov 组合 bug 见仓库既有记录）。
- 静态：`ruff check src tests` 全绿；`ruff format --check` 326 files 全绿；`mypy src`
  Success: no issues in 168 source files。
- 契约：`tests/test_architecture_contracts.py` 30 passed **零改动**（docker.py 未新增跨包依赖）。
- 判据：`tests/test_sandbox_docker.py` 12/12（判据 11 新增）。

## 残余（如实标注）

- **docker.io 直连 digest 验证未完成**：`auth.docker.io` 30s 超时不可达（本机网络对 docker.io
  直连断流，与既有网络环境记录一致）。基座 digest 维持 53-2 的镜像源交叉验证口径
  （daocloud 与 docker.io manifest 字节一致）；直连补验挂起，触发条件=出现可用直连通道。
