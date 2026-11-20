---
title: 'Story 66.4 实现技能包按需懒加载'
type: perf
ticket: 4
created: '2026-11-18'
status: done
baseline_revision: '0a70447'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/skills/skill_packages.py'
  - 'tests/test_skill_packages.py'
---

## Intent

`SkillPackage` 的资源读取已经是懒的（`read_resource` 只读一个文件，`metadata` 首次访问才读
`SKILL.md`），但 `SkillCatalog._index_package()` 对每个包**读两次 entry**：
先 `provisional.read_entry()` 取 canonical_id，再 `package.read_entry()`——第二次的返回被丢弃。
技能根有 47+ 个包时，这就是启动期双倍 entry IO（每个 entry 还带 `meta.yaml` 解析与完整性校验）。

**Approach：**

- `_index_package` 只读一次 entry：把首次解析出的 `SkillPackageMetadata` 直接注入正式
  `SkillPackage` 的私有 `_metadata`（复用同一次解析结果），不再第二次 `read_entry()`；
- 保持 `SkillPackage` 的其余懒语义不变：构造不读文件，`metadata` / `read_resource` 按需读。

## Verify

- 计数断言：`SkillCatalog([...]).scan()` 对一个包只触发 1 次 entry 读取（现状 2 次），
  多包目录下总读取次数 = 包数（现状 2×包数）。
- 懒加载断言：`SkillPackage(...)` 构造后未发生任何文件读取；首次访问 `metadata` 才读 1 次；
  再次访问不重复读。
- `pytest tests/test_skill_packages.py tests/test_skill_package_integrity.py tests/test_skill_roots.py -q` 全绿。

## Boundaries

- 不改完整性校验口径（`manifest.json` / `manifest.lock` 比对逻辑保持）。
- 不做「包目录延迟发现」（`scan()` 仍需枚举目录与读 entry 才能定 canonical_id）。
- 不引入全局包缓存。

## Implementation（实测）

- 落点：`SkillCatalog._index_package` 先 `entry = provisional.read_entry()`，再
  `package.adopt_entry_text(entry.text, provisional.entry_meta)` —— entry 只读一次，`meta.yaml` 解析结果经
  `_load_meta()` 实例缓存复用；`name` 回落按 canonical id 重算（与 `read_entry()` 逐字段一致）。
- 实测：`pytest tests/test_skill_lazyload.py -q` → 单包 `scan()` 的 entry 读取 1 次（改前 2 次）、多包 = 包数；
  `SkillPackage` 构造 0 读、首次 `metadata` 1 读、二次 0 读；注入结果与重新读 entry 的 `model_dump()` 相等。
