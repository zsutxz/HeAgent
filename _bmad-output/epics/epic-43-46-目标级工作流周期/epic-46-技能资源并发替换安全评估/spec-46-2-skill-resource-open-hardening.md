---
title: 'Story 46.2 鎶€鑳借祫婧愬畨鍏ㄦ墦寮€鍔犲浐'
type: 'feature'
created: '2026-09-01'
status: 'done'
baseline_commit: 'c7349a5a3c6ea1c9559dd38e2c14c657137f65b5'
review_loop_iteration: 0
context:
  - 'E:/AI/HeAgent/docs/frame.md'
  - 'E:/AI/HeAgent/_bmad-output/patches/memory/spec-skill-resource-toctou-assessment.md'
  - 'E:/AI/HeAgent/_bmad-output/epics/epic-43-46-鐩爣绾у伐浣滄祦鍛ㄦ湡/epic-46-鎶€鑳借祫婧愬苟鍙戞浛鎹㈠畨鍏ㄨ瘎浼?stories/46-1-skill-resource-toctou-assessment.md'
---

<frozen-after-approval reason='human-owned intent - do not modify unless human renegotiates'>

## Intent

**Problem:** `SkillPackage` 褰撳墠鍏堟鏌ヨ矾寰勫啀璋冪敤 `read_text()`锛涙敾鍑昏€呭彲鍦ㄦ鏌ュ悗鎶婃渶缁堟枃浠舵浛鎹负鎸囧悜鍖呭鐨勭鍙烽摼鎺ャ€侲pic 46.1 宸茶瘉鏄庤绐楀彛瀛樺湪锛屼絾娌℃湁杩愯鏃跺姞鍥恒€?
**Approach:** 璧勬簮璇诲彇缁熶竴閫氳繃宸叉墦寮€鐨勬枃浠舵弿杩扮瀹屾垚锛屽苟鍦ㄦ敮鎸佺殑骞冲彴涓烘渶缁堣矾寰勭粍浠跺惎鐢?`O_NOFOLLOW`銆佹牎楠?descriptor 鎸囧悜鏅€氭枃浠讹紱涓嶆敮鎸佽鑳藉姏鐨勫钩鍙颁繚鐣欏吋瀹瑰洖閫€锛屽悓鏃跺湪娴嬭瘯鍜屾枃妗ｄ腑鏄庣‘娈嬩綑绔炴€佷笌 OS 娌欑杈圭晫銆?
## Boundaries & Constraints

**Always:** 澶嶇敤鐜版湁 `resolve_under_root`锛涗繚鎸?`SkillPackage` 鍏叡鏂规硶鍜?`SkillPackage*Error` 閿欒璇箟锛涘叆鍙ｃ€乻tep銆乺eference銆乼emplate銆乤sset銆乻cript 鍏ㄩ儴璧板悓涓€璇诲彇杈呭姪锛涘叧闂枃浠舵弿杩扮锛涗笉鎶?best-effort 淇濇姢鎻忚堪涓哄畬鏁?TOCTOU 鎴?OS 瀹夊叏杈圭晫銆?
**Ask First:** 鑻ラ渶瑕佹敼鍙橀粯璁ゅ紓甯哥被鍨嬨€佹嫆缁濅笉鏀寔 `O_NOFOLLOW` 鐨勫钩鍙帮紝鎴栧紩鍏ュ钩鍙颁笓鐢ㄧ洰褰曞彞鏌?API锛屽厛鏆傚仠骞惰姹傜‘璁ゃ€?
**Never:** 涓嶄慨鏀?`SkillResolver`銆乣SkillRunner`銆乣/goal` 鎴?importer 鐨勫叕鍏辫涓猴紱涓嶅垹闄ょ幇鏈夌珵鎬佺壒寰佹祴璇曪紱涓嶄緷璧?`/proc`銆佸閮ㄥ畧鎶よ繘绋嬫垨鐪熷疄 LLM銆?
## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| --- | --- | --- | --- |
| Regular read | Root-relative regular UTF-8 file | Reads content through one opened descriptor | Existing package error mapping remains |
| Final symlink race | Final resolved file becomes a symlink before open | Protected platforms reject the open; no outside content returned | Map to `SkillPackageResourceError` / entry error with cause |
| Unsupported capability | `O_NOFOLLOW` unavailable | Compatibility read works, residual risk is documented and tested | No silent claim of complete protection |
| Non-regular target | FIFO/device/directory | Read is rejected | Explicit resource read error |

</frozen-after-approval>

## Code Map

- `src/heagent/memory/skill_packages.py:99-123` -- `read_entry`/`read_resource` currently perform `is_file()` then `read_text()`; add one shared descriptor-based reader and preserve error translation.
- `src/heagent/tools/path_safety.py:54-70` -- authoritative `resolve_under_root` fence; do not duplicate or weaken it.
- `tests/test_skill_packages.py:32-160` -- package read/error regression coverage that must remain green.
- `tests/test_skill_packages_toctou.py:14-95` -- current replacement characterization; extend it to prove final-symlink rejection when the platform exposes `O_NOFOLLOW`, and explicit fallback behavior otherwise.
- `docs/frame.md:646-656` -- current TOCTOU and non-boundary wording; update only to describe the best-effort open hardening and residual risk.

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/memory/skill_packages.py` -- implement a shared binary descriptor reader with optional `O_NOFOLLOW`, regular-file validation, UTF-8 decoding, and existing exception mapping.
- [x] `tests/test_skill_packages.py`, `tests/test_skill_packages_toctou.py` -- cover normal reads, missing/invalid targets, final symlink replacement, unsupported capability fallback, and descriptor cleanup without network access.
- [x] `docs/frame.md` and `_bmad-output/deferred-work.md` -- record the implemented protection, supported-platform condition, and remaining intermediate-component/hostile-process risk.

**Acceptance Criteria:**
- Given a valid package resource, when it is read, then content and public errors match existing behavior and no descriptor leaks.
- Given the final resolved file is replaced by a symlink before open, when `O_NOFOLLOW` is available, then the read fails explicitly and never returns outside content.
- Given a platform without `O_NOFOLLOW`, when the same read occurs, then compatibility behavior is preserved and documentation states the protection is unavailable.
- Given a non-regular target, when a resource is read, then it fails explicitly rather than consuming a device, FIFO, or directory.

## Design Notes

`O_NOFOLLOW` protects only the final opened component. It does not eliminate races in intermediate directories, malicious mounts, or a hostile process with stronger privileges. Descriptor-relative directory walking and OS sandboxing remain separate future work.

## Verification

**Commands:**
- `pytest tests/test_skill_packages.py tests/test_skill_packages_toctou.py` -- expected: all package and race-hardening tests pass.
- `ruff check src tests` -- expected: no lint violations.
- `mypy src` -- expected: no type errors.

## Suggested Review Order

**读取边界**

- 统一 descriptor 读取与回退
  [`skill_packages.py:116`](../../../../src/heagent/memory/skill_packages.py#L116)

- 保留根目录路径围栏
  [`path_safety.py:54`](../../../../src/heagent/tools/path_safety.py#L54)

**竞态与异常证据**

- 验证最终符号链接拒绝
  [`test_skill_packages_toctou.py:102`](../../../../../tests/test_skill_packages_toctou.py#L102)

- 验证兼容回退与 FIFO 拒绝
  [`test_skill_packages_toctou.py:143`](../../../../../tests/test_skill_packages_toctou.py#L143)

- 检查残余安全边界声明
  [`frame.md:646`](../../../../../docs/frame.md#L646)
