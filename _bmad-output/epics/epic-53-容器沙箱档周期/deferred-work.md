# Epic 53 · Deferred Work

> 本 epic 内挂起项；跨周期条目仍归 `implementation-artifacts/deferred-work-archive.md` 总账。

## 状态总览

| ID | 条目 | 状态 | 闭合者 |
|----|------|------|--------|
| D53-1 | 期二：MCP stdio server 进容器 | 挂起待触发（期一闭合后由用户裁定是否开期二） | — |
| D53-2 | 期二：审批降级接入 PolicyEngine | 挂起待触发（同 D53-1） | — |
| D53-3 | docker.io 直连 digest 验证（网络恢复后补验基座 pin） | 挂起待触发（网络环境限制，非代码缺口） | — |

## D53-1 期二：MCP stdio server 进容器

- **来源**：AGENTS.md 活动缺口「MCP stdio server 子进程不经沙箱（中-高）」；frame.md:1271 裁定「不单独开缝、须整体 OS 级沙箱兜底」——容器档落地后该兜底首次成为可实施项。
- **前置**：期一（DockerRunner）闭合。
- **触发条件**：期一 stories 全部闭合且用户裁定开期二。
- **要点**：stdio server 拉起进同一镜像的容器（长命双向 JSON-RPC 管道，非 `sh -c` 短命形状——需要新缝，勿复用 CommandRunner）；网络档沿用 D2。

## D53-2 期二：审批降级接入 PolicyEngine

- **来源**：FR-2 预留的 `can_relax_approval` 从未接入 `PolicyEngine` 裁决（frame.md:1278）。
- **前置**：期一闭合 + D53-1 或与它同批。
- **触发条件**：同 D53-1。
- **要点**：仅 container 档生效（NFR-2 冻结边界）；降级语义须先出设计再实施。

## D53-3 docker.io 直连 digest 验证

- **来源**：53-3 交付时 `auth.docker.io` 30s 超时不可达（本机网络对 docker.io 直连断流）；基座 digest 维持 daocloud 镜像源交叉验证口径（与 docker.io manifest 字节一致）。直连补验挂起。
- **触发条件**：出现可用直连通道。
- **要点**：直连复核 `python:3.11-slim` 基座 pin 值与本地 `heagent-sandbox:3.11` 的 repo digest。

> **2026-10-24 retro 更正**：当日 walkthrough Detail Pass 曾误报「运行期 digest 校验与资源限额的装配链未接线」（据此短暂立过 D53-4，已撤销）。经 HEAD 复核不成立——`Settings.sandbox_docker_digest` / `sandbox_memory_limit_mb` / `sandbox_nproc_limit` 三字段齐全（`config/__init__.py:320,348,357`），resolver 全链透传（`engine/container.py:80-86`），integration 7/7 含限额触发实证。误报根源：只看 review 前 range（`f0943fd`）的 diff，未读 53-3「审查修复批」记录（该批在入 review 后落地并接全链）。
