# Epic 53 · Deferred Work

> 本 epic 内挂起项；跨周期条目仍归 `implementation-artifacts/deferred-work-archive.md` 总账。

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
