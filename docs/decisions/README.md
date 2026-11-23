# decisions/ — ADR 决策记录

已被批准的架构/工程决策，一条一文件：`adr-<4位编号>-<decision-slug>.md`（一段式：Context / Decision / Why，并点名 plan 与 commit；编号四位零填充，按批准顺序递增）。

| ADR | 决策 | 来源 commit | 状态 |
|-----|------|-------------|------|
| [ADR-001](adr-0001-benchmark-regression-gate.md) | CI 基准回归强制门禁（`--benchmark-compare-fail=mean:10%`） | `cab4552` | accepted |
| [ADR-002](adr-0002-test-data-single-home.md) | 测试数据唯一宿 `tests/fixtures/` + 三条可执行判据 | `b75075a` | accepted |
| [ADR-003](adr-0003-parametrize-coverage-scope.md) | 参数化覆盖率口径 = touched-scope | `abf96d9` | accepted |
| [ADR-004](adr-0004-ws-tls-install-time-trust.md) | WS TLS 信任锚 = 服务端身份公钥（安装期 SPKI pin，证书可轮换而 pin 不变） | Epic 73 立项批 | accepted |
| [ADR-005](adr-0005-ws-remote-project-channel.md) | 远程多项目控制 = WS 单通道 + 项目编址（提交帧可选 project_id，HTTP 面不动） | 设计访谈批（2026-11-23，实现未排期） | accepted |

写入门槛（来自 `bmad-retrospective` 方法）：难以回退 + 脱离上下文会显得意外 + 真实权衡的产物，且仓库内无既有记录。一次性裁定（如「某票 dropped」）不写 ADR，留在该票 plan 的 `<frozen-after-approval>` 块内。
