# Changelog

本文件记录 HeAgent 的对外可见变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号使用纯 `X.Y.Z`（0.x 阶段 **minor 即破坏性变更**，发布流程见 `deploy/README.md`）。

约定：

- `## [Unreleased]` 段常驻，下一个版本的改动先写这里；
- 每个已发布版本一节，标题形如 `## [0.9.0] - 2026-11-11`；
- 发布前先 bump `pyproject.toml` 与 `src/heagent/__init__.py`（两处必须一致），
  再把 `Unreleased` 的内容落成版本节 —— 这三点由 `tests/test_release_workflow_contract.py` 守住。

## [Unreleased]

### Added

- `RunStore.close_stale_running`：把陈旧 running 快照收尾为 FAILED（崩溃进程遗留的 running 不再污染统计；`updated_at` 保持末次真实活动时刻，不回填时钟）。已接线：新 run 启动时自动触发一次（去重），阈值 `RUN_STALE_IDLE_HOURS`（默认 6h，0=禁用）。

### Fixed

- `ProviderChain` / `KeyRotatingProvider` / `SwitchableProvider` 的 `send` 不再持锁跨网络 I/O（与 stream 同口径：锁内快照索引，调用不持锁），并发 LLM 调用不再被串行化。
- `RunStore.build_run_tree` 改为单次线程卸载批量读取、只校验 `context`，万级快照下运行树查询不再逐个解析整份快照。
- 池内回退纳入 404 model 不可用：失效档位由池内兄弟模型接管（判据 `is_pool_fallback_error`；同步覆盖 OpenAI 兼容端点的 "does not exist" 措辞）。

## [0.9.0] - 2026-11-11

### Changed（破坏性）

- **斜杠命令硬改名**：`/route` → `/model`（路由池档位切换），`/model` → `/provider`（provider 切换）。
  两个旧名**都不注册、无别名** —— 输入旧名不会报错，会被当作普通 prompt 交给 `AgentLoop`
  （静默多花一次 LLM 调用）。迁移时把脚本与笔记里的 `/route` 改成 `/model`、旧 `/model` 改成 `/provider`。
- **`config/catalog.py` 拆为子包**：1350 行单文件 → `config/catalog/` 9 个文件（最大 307 行）。
  公共名 `heagent.config.catalog` 与 `__all__` 的 34 项**零变化**，子模块属内部实现细节。

### Added

- **契约基线第四份** `tests/contract_baselines/transport_errors.json`：35 个错误码的
  `status` / `code` / `keys`，配套「错误码只增不减」（INV-8）与信封键集冻结守卫。
- **WS 路由进快照**：`transport_routes.json` 从 21 条增至 25 条，补上 `/api/runs/ws`、
  `/api/runs/{run_id}/ws`、`/api/cli/ws`、`/api/notifications/ws`。
- `scripts/contract_snapshot.py --print --only <kind>`：打印当前快照、不落盘、不比对。
- **文档构建严格门**：新增 `mkdocs.yml`，CI 的 `lint` job 加 `mkdocs build --strict` step（不新建 job）。
- **发布契约断言** `tests/test_release_workflow_contract.py`：release job 的触发面 / `environment: release` /
  `id-token: write`、job 数恒 8，以及**版本号单一真源**（`__version__` == `pyproject.toml`，
  HEAD 带 `v*` tag 时 tag 必须等于版本）。
- **传输层零文档 URL 守卫** `tests/network/test_transport_no_doc_links.py`：`src/heagent/network/**`
  的字符串常量不得出现 `/docs/`、`mkdocs`、`readthedocs`。
- `deep-research` 技能：特定主题深度调研。
- WS 连接首帧 `hello` 下发服务器版本。

### Fixed

- 契约基线的描述措辞跟上第四份快照（`scripts/quality_gate.py` 第 0 门注释、`tests/test_contract_baselines.py` docstring）。

### 未回填说明

**0.9.0 之前的历史版本未逐条回填**：本文件 2026-11-11 才建立，早期版本的发布日期与条目分类无法从仓库
可靠重建（记错日期或臆造分类比留白更糟）。需要追溯时用 git 历史，它才是那些版本的权威记录：

```bash
git log v0.3.0..HEAD --oneline          # 自最后一个 tag 起的全部提交
git log --oneline --grep="!:"           # 破坏性变更
git log --oneline --grep="^feat"        # 新特性
```
