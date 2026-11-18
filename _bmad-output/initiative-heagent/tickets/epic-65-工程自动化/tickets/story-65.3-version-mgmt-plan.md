---
title: 'Story 65.3 实现自动化版本号管理'
type: chore
ticket: 3
created: '2026-11-18'
status: done
baseline_revision: 'ae831fe'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/__init__.py'
  - 'pyproject.toml'
  - 'tests/test_release_workflow_contract.py'
---

## Intent

**Problem（勘差结论：票面 description 已被用户裁决作废）：** 票面写「merge 到 main 触发语义化版本号自动管理」，
而 Step 04 决策 **Q2 明确作废了「merge 自动发版」这条验收标准**——`release` job 只由 `v*` tag 或
`workflow_dispatch` 触发（守卫：`test_release_workflow_contract.py::test_release_job_triggers_only_on_tags_or_manual_dispatch`）。
「merge 即自动 bump」因此**没有可验收的语义**，只剩 verify 的后半句：版本符合 semver 且两处同步。

这半句现状已闭合，且是**可执行判据**而非手工约定：

- `test_version_is_plain_semver`：`src/heagent/__init__.py::__version__` 必须是纯 `X.Y.Z`；
- `test_package_version_has_a_single_source`：模块常量与 `pyproject.toml::project.version` 必须相等
  （AST + `tomllib` 取值，不 import 包）；
- `test_head_tag_matches_version_when_present`：HEAD 恰好带 `v*` tag 时校验 tag 与版本一致；
- 发布侧：`release` job 的 `Extract version` step 优先取 tag、回退读 `pyproject.toml`，两条路径都指向同一真源。

**Approach：** **不新增实现**，按勘误口径把本 entry 收敛为「真源 + 守卫已达」。

## 为什么不加一个 bump 脚本

`scripts/bump_version.py` 可以直接消掉「两处手工同步」这个失误面，但：

- 验收标准已被 Q2 作废，脚本没有可验收的对象（写成什么样都算「完成」，属自证）；
- 两处不一致**已经有秒级判据**（契约测试在每次 `pytest` 与 CI 上跑），风险敞口已被覆盖；
- 发版动作本身还包含 CHANGELOG 归节与打 tag，脚本只覆盖三分之一，反而给了「跑完脚本就发完了」的错觉。

结论：新增未请求的脚本 = 增加维护面而不降低已被覆盖的风险，刻意不做。若日后用户要求一键发版，
再按「bump + CHANGELOG 归节 + tag 建议」三件事一起设计。

## Verify

- `pytest tests/test_release_workflow_contract.py -q` → 10 passed / 1 skipped（含上述三条版本断言）。
- 现状实测：`src/heagent/__init__.py` 与 `pyproject.toml` 版本一致（契约测试绿即证）。

## Boundaries

- 不启用 merge 自动发版 / 自动 bump（Q2）。
- 不改版本真源位置（两处 + 契约测试是既有口径，WS hello 帧与打包元数据都依赖这两处）。
