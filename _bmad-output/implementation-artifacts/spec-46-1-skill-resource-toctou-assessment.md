---
title: 'Story 46.1 技能资源 TOCTOU 威胁评估与决策记录'
type: 'feature'
created: '2026-09-01'
status: 'done'
baseline_commit: '44a77e4b307f88699bf114b4b2166c5231ee21ff'
review_loop_iteration: 0
context:
  - 'E:\\AI\\HeAgent\\docs\\frame.md'
  - 'E:\\AI\\HeAgent\\_bmad-output\\epics\\epic-43-46-目标级工作流周期\\epics.md'
  - 'E:\\AI\\HeAgent\\_bmad-output\\epics\\epic-42-BMad技能包运行时周期\\epics.md'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** `SkillPackage` 在包根解析、符号链接校验和 `read_text` 之间存在并发替换窗口。当前围栏能阻止普通路径穿越，却不能把用户态路径检查变成可信的文件身份保证。

**Approach:** 以现有实现为基线建立明确威胁模型和可重复的竞态/特征测试，比较文件描述符、目录句柄、复制快照和 OS 沙箱四类候选方案，记录条件、成本、兼容性与残余风险。评估不直接改变运行时语义；若需要加固，另立实现 story。

## Boundaries & Constraints

**Always:** 保留 `resolve_under_root` 的现有路径围栏语义；将技能内容和本地文件系统视为不可信；测试必须能证明“校验后替换”与符号链接替换的攻击窗口；文档明确这是 defense-in-depth 而非 OS 安全边界。

**Ask First:** 若结论建议修改 `SkillPackage` 公共 API、引入平台专用依赖或改变导入物化策略，停止并请求单独授权。

**Never:** 不在本 story 中实现文件描述符级加固、重写导入器、改变 `/goal` 或 `SkillStore` 行为；不声称竞态已被消除；不使用仅依赖时间睡眠的脆弱并发测试作为唯一证据。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal read | Root-relative regular file | Existing content is read and current fence remains unchanged | Existing package errors remain unchanged |
| Symlink replacement | Valid link is swapped to an outside target after resolution | Characterization test demonstrates the window or documents platform limitation; no false claim of prevention | Evidence includes skill id, resource and operation boundary |
| Candidate unavailable | Descriptor/handle primitive unavailable on a supported platform | Decision records fallback and residual risk | No silent claim of protection |

</frozen-after-approval>

## Code Map

- `src/heagent/memory/skill_packages.py:99-123, 151-160` -- `read_entry`/`read_resource` resolve a `Path` and then read it, defining the check/use boundary under assessment.
- `src/heagent/tools/path_safety.py:54-70` -- shared `resolve_under_root` fence; resolves symlinks with `strict=False` but does not hold an OS file identity.
- `tests/test_skill_packages.py:32-160` -- existing package, symlink escape, missing-resource and diagnostic coverage to preserve as regression evidence.
- `src/heagent/memory/skill_importer.py:70-170` -- imported package materialization and hash lock; relevant to snapshot/immutable-copy option, but out of implementation scope.
- `docs/frame.md` and `_bmad-output/epics/epic-42-BMad技能包运行时周期/epics.md` -- current security-boundary wording and FR4/NFR3 contract that must cite one conclusion.
- `_bmad-output/deferred-work.md` -- existing deferred item for this assessment; update it with the decision and any follow-up story.

## Tasks & Acceptance

**Execution:**
- [x] `tests/test_skill_packages_toctou.py` -- add deterministic characterization tests for resolve-then-read replacement and symlink replacement, plus platform capability notes -- provide reproducible evidence without changing runtime behavior.
- [x] `_bmad-output/patches/memory/spec-skill-resource-toctou-assessment.md` -- write the threat model, affected resources, current controls, attack preconditions, candidate comparison, decision, and residual-risk statement -- make the assessment independently reviewable.
- [x] `docs/frame.md`, `_bmad-output/deferred-work.md`, `_bmad-output/epics/epic-42-BMad技能包运行时周期/epics.md`, `_bmad-output/consolidated-overview.md` -- align references to the same conclusion and identify any future implementation story -- prevent contradictory security claims.

**Acceptance Criteria:**
- Given `SkillPackage` path resolution, symlinks and resource reads, when the characterization tests run, then the check/use window, affected entry/step/reference/template/asset/script resources, current fence, and OS boundary are explicitly evidenced.
- Given descriptor-relative open, directory handle, copy snapshot and OS sandbox candidates, when the assessment is reviewed, then each has correctness conditions, platform feasibility, performance/compatibility cost and residual risk, followed by one decision.
- Given no candidate is proven universally suitable, when planning is updated, then current path-fence behavior remains unchanged, no TOCTOU-complete claim is made, and any hardening work is named as a separate story.
- Given the assessment is complete, when maintainers inspect the referenced docs, then `deferred-work.md`, `docs/frame.md` and Epic 42 security text point to the same decision without duplication or contradiction.

## Design Notes

The default decision is expected to be “assessment only; no cross-platform runtime change yet.” Descriptor-relative APIs can reduce the race on supported OSes but require platform-specific code and careful symlink policies. Copy/snapshot materialization is practical for trusted import boundaries but does not protect a package already controlled by an attacker. OS sandboxing remains the only boundary that addresses hostile filesystem/process context, and must be described as external defense-in-depth.

## Verification

**Commands:**
- `pytest tests/test_skill_packages.py tests/test_skill_packages_toctou.py` -- expected: all package and characterization tests pass.
- `ruff check src tests` -- expected: no lint violations.
- `mypy src` -- expected: no type errors.

## Suggested Review Order

**Threat model and decision**

- Start with the assessment conclusion and residual boundary.
  [`assessment:1`](../../_bmad-output/patches/memory/spec-skill-resource-toctou-assessment.md#L1)

- Confirm architecture wording preserves defense-in-depth limits.
  [`frame.md:646`](../../docs/frame.md#L646)

**Evidence and planning traceability**

- Check cross-reader replacement characterization coverage.
  [`test_skill_packages_toctou.py:33`](../../tests/test_skill_packages_toctou.py#L33)

- Check symlink replacement evidence and capability handling.
  [`test_skill_packages_toctou.py:58`](../../tests/test_skill_packages_toctou.py#L58)

- Verify deferred follow-up remains explicitly tracked.
  [`deferred-work.md:16`](../../_bmad-output/deferred-work.md#L16)
