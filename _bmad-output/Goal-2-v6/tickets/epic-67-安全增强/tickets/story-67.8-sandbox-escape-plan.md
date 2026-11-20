---
title: 'Story 67.8 编写沙箱逃逸测试'
type: feature
ticket: 8
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
  - 'tests/test_sandbox_escape.py'
---

## Intent

沙箱有多个测试文件，但缺一份**按攻击向量组织**的逃逸测试（票面要求 ≥5 个向量）。

**Approach：** 新增 `tests/test_sandbox_escape.py`，逐向量断言被拒或无法影响宿主：
① `../` 路径穿越；② 绝对路径写入；③ 符号链接指向宿主目录；④ 读宿主敏感文件
（`/etc/passwd` 或宿主 home 下的密钥）；⑤ 环境变量泄漏宿主密钥；⑥ 容器内 PID/挂载逃逸探测。
不依赖 docker daemon 的向量用 path_safety / 沙箱后端单测覆盖；需要容器的向量标 `integration`。

## Verify

- ≥5 个向量，每个都有「攻击动作 + 期望拒绝 + 判据断言」；
- 非 integration 向量全绿（默认门）；integration 向量在无 daemon 时 skip 且说明原因；
- 现有沙箱测试不删不减。

## Boundaries

- 只加测试；发现真逃逸只登记为安全缺口（不改沙箱实现）。
- 测试内不真的破坏宿主文件（用 tmp_path 与只读探测）。

## Implementation（实测）

- 落点：`tests/test_sandbox_escape.py`（17 例，7 个向量）：`../` 穿越、绝对路径、符号链接、读宿主敏感文件
  （`/etc/passwd` / 宿主 home 下的密钥）、环境变量泄漏、容器挂载表、容器 PID 命名空间。
- 每个向量三段式（攻击动作 → 拒绝层 → 断言），并尽量带正面控制（证明「什么都没发生」不是因为路径不存在）。
- 需 docker 的向量标 `@pytest.mark.integration`（无 daemon 时 skip 并给原因）；其余在默认门内。
- 实测：`pytest tests/test_sandbox_escape.py -q` → 17 例（含 3 例 integration deselected）全绿。
