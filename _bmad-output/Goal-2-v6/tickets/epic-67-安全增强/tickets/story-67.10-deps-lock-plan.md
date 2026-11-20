---
title: 'Story 67.10 增加依赖锁定'
type: feature
ticket: 10
created: '2026-11-18'
status: done
baseline_revision: '0b1b156'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'scripts/lock_requirements.py'
  - 'requirements.lock'
---

## Intent

`pyproject.toml` 只有区间约束（如 `pydantic>=2.13,<2.14`），没有可复现的完整锁定文件。

**Approach：** 新增 `scripts/lock_requirements.py`：从当前已安装环境导出（`pip freeze --exclude-editable`）
生成 `requirements.lock`（含传递依赖的精确版本），并写清更新流程（升级 → 重生成 → 提交）。

## Verify

- `requirements.lock` 存在、每行是 `name==version`（无环境标记外的杂项），可 `pip install -r` 解析；
- 脚本幂等（连跑两次内容一致）；
- 文档写清更新流程（`docs/frame.md` 或 `docs/testing.md` 的指针节）。

## Boundaries

- 不引入 pip-tools / uv（仓库当前无这两个工具）。
- lock 只是「参考锁定」，不接管 CI 安装（CI 仍用 pyproject extras）。

## Implementation（实测）

- 落点：`scripts/lock_requirements.py`（`pip freeze --exclude-editable` → 只保留合法 `name==version` 行，
  丢弃 `-e` / `-r` / 直接 URL；`--check` 校验幂等）+ `requirements.lock`（102 行）+ `docs/testing.md` 更新流程节。
- 实测：连跑两次生成内容逐字节一致；锁文件无本机路径、无 `-e` 行。
