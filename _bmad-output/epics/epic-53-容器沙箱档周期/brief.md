# Epic 53 · 容器沙箱档周期 · Brief

> 立项：2026-10-20（会话评估 + 用户拍板）。本文是唯一决策记录；stories 由周期会话走 bmad 流程另行生成。

## 背景

`docs/frame.md` 五约有 12 处缺口以「非真正安全边界，须 OS 级沙箱兜底」收尾；`SandboxTier.CONTAINER` 自 FR-2（2026-08-26）起仅为预留枚举、无实现后端。`epic-S1-S4-沙箱硬化周期`（已归档）曾裁定 MCP stdio 不单独开缝、以整体 OS 沙箱兜底——**本 epic 即该兜底的落地**，推翻 S1-S4「不实施」的结论（依据：本机 Docker 底座现成 + `CommandRunner` 接缝零改造，工程前提已变）。

## 冻结决策（2026-10-20 用户拍板，变更须经用户）

| # | 决策 | 冻结值 |
|---|------|--------|
| D1 | 路线 | **A = Docker 容器后端**（弃 WSL2 发行版当边界、弃完整 VM） |
| D2 | 网络档 | `--network=none` 默认；bridge 须显式配置开启，失败显性报错 |
| D3 | 期一范围 | **仅 shell 工具进容器**（走 `CommandRunner` 缝）；文件工具仍走围栏（非边界立场不变） |
| D4 | 镜像基 | `python:3.11-slim` + 项目依赖（与 CI 同版本），镜像 pin digest |

## 接缝事实（勘察结论，2026-10-20）

- `tools/sandbox/contracts.py:59` `CommandRunner` Protocol：`tier` + `available` + `async run(command, timeout) -> str`
- 注入 slot `configure_command_runner` / `bind_command_runner` 现成（`process.py:311`）
- `SandboxTier.can_relax_approval` 已钉死「仅 container 档」（NFR-2，测试锁定）
- Protocol 既有约定：后端不可用时优雅降级 Passthrough
- 既有后端形状：短命命令捕获（`sh -c` 收尾），DockerRunner 沿用同形状（`docker run --rm … sh -c <command>`）

## 本机底座（2026-10-20 探明）

Docker Desktop 28.5.2 运行中（Linux 容器）+ WSL2 Ubuntu 运行中；无 VirtualBox / VMware / Hyper-V。

## 期一范围（stories 待 bmad 流程拆分）

1. `DockerRunner` 实现 + 注入接线 + 不可用降级（判据含变异体）
2. 镜像构建 + pin digest + 配置面（网络档开关挂 `Settings`）
3. 文档同步（frame.md 五 container 行、AGENTS.md 安全声明）+ 契约测试

## 期二（见 `deferred-work.md`）

MCP stdio server 进容器（收 AGENTS.md 最后一个「中-高」暴露面）+ `can_relax_approval` 接入 `PolicyEngine` 裁决。

## 冻结边界

- 弱后端（passthrough/job/firejail）一律不得审批降级（NFR-2 既有锁，不动）
- 容器档亦**不得**宣称绝对边界（宿主内核 / Docker daemon 自身的逃逸风险仍在）；文档表述保持「OS 级强隔离兜底」口径
- D2–D4 任一变更须经用户裁定并回写本文件
