---
title: '57-2 port_finder 测试环境敏感性修复'
type: 'test'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
baseline_commit: '54aa99e9a988839b1c4cd05b200069f1b350e9c9'
context: []
---

<!-- 闭环 sprint-status：epic-52-retro-item-2。 -->

## Intent

**Problem:** `tests/cli/test_port_finder.py::test_respects_max_attempts` 在 epic-52 期（2026-10-09）稳定失败且 stash 基线复现，2026-10-26 复跑又全绿——典型的环境敏感：测试硬编码固定端口段（55000-55065），隐含假设「该段恰好处于测试预期的占用/空闲状态」。两类真实干扰源：本机 HeAgent 多开实例端口顺延（a545613 起默认开启）恰好漂到测试段；Windows 动态排除端口区间（Hyper-V/WSL/Docker 保留段，`netsh excludedportrange`）覆盖 55xxx 时 bind 直接 PermissionError。

**Approach:** 测试文件内新增 `_reserve_block(count)` helper——以 OS 临时口（bind 0）为起点探测连续 count 个可绑定端口并占住，碰撞即换起点重试（有界）；所有真实 socket 测试改用动态基端口替代硬编码段。**测试意图不变**：max_attempts 语义（N 次内必失败/第 N+1 个成功）、顺延日志文案、host 参数透传全部照旧断言，只是不再依赖「世界上 55010-55015 恰好是空的」。纯 mock 测试（`test_handles_os_errors_gracefully`）不动。

## Acceptance Criteria

1. 文件内不再有硬编码端口断言（`550xx` 字面量仅允许出现在 mock 测试）。
2. 全文件 7 测试绿，且连续复跑 3 次无 flake。
3. 并发干扰模拟：预占测试段任一端口（模拟多开实例）后复跑仍绿——即测试对端口段状态不再敏感。
