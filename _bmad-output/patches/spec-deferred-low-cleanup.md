---
title: '收尾 deferred-work.md 剩余 LOW defer 项'
type: 'chore'
created: '2026-07-11'
status: 'done'
route: 'one-shot'
---

# 收尾 deferred-work.md 剩余 LOW defer 项

## Intent

**Problem:** deferred-work.md 仍有几项未关闭 LOW defer（`_unregister_all` 防御快照、`test_disconnect_isolated_to_one_server` 测试保真度、进程组 kill；另有 `_watch` TimeoutError 同名异义已「保持现状」、`_watch` except 过宽 future），需收尾清账。

**Approach:** (1) `_unregister_all` 核实当前已是 `for name in list(self._registered): self._unregister_server(name)`——`list()` 快照 + `pop`，原描述（「迭代 `.values()` 后 `.clear()`」）已过时，标 Resolution 关闭，**无代码改动**；(2) 增强 `test_disconnect_isolated_to_one_server`——`tracking_transport` 用 try/finally 设 `closed` 标志，断言断连 server transport `__aexit__` 已执行、另一 server transport 仍持有、手动注册的非 server 命名空间「内置」工具保留（覆盖 FR-3 review defer 项 a/b/c）；(3) 进程组 kill——Linux-only 且 Windows 开发环境无法验证、`FirejailBackend` 路径下 firejail 自身 session/namespace 交互需 Linux 实证，标 Resolution defer、归 CLAUDE.md / frame.md 已知缺口。`_watch` 两项不动（已接受现状 / future）。

## Suggested Review Order

- 本节 **Intent** —— 核实三项 Resolution 措辞与 defer 立场（尤其进程组 kill 不盲改的理由）
- `../../tests/test_mcp_manager.py` —— 增强断言：`tracking_transport` closed 标志 + `_builtin` 内置工具保留
- `./deferred-work.md` —— 三条 Resolution：`_unregister_all`（已隐式解决）、进程组 kill（defer to Linux env）、测试保真度 a/b/c（随测试增强覆盖，2026-07-11 补写）。注：7131cd0 执行时本 review order 仅列前两项，漏写测试保真度 Resolution，本次（2026-07-11）补齐
