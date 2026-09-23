# Epic 49 架构脊柱对抗性审查

审查对象：`ARCHITECTURE-SPINE.md`（2026-09-23）。以下问题都可以在不明显违反现有 AD 规则的情况下出现；因此需要在进入 Story 实现前把契约补成可测试的行为，而不是依赖实现者自行解释。

## 发现

### F1（P0）：run、session projection 与共享运行时没有唯一事实源

**依据：** AD-3 规定 HTTP service 持有 run records、event buffers 和 subscriptions；Story 49-3 又规定 session projection，以及“服务级 Provider/Engine/Memory 按现有入口共享”。但没有定义 session 快照由哪一个对象、在什么事件、以什么顺序更新，也没有定义 run record 与 `AgentLoop` 的最终答案/usage/model 的一致性规则。

**两个都合规但会分叉的实现：**

1. 实现 A 在收到 `completed` 后才把 prompt/answer 写入 service 的 `session.messages`；中途刷新只能看到上一次已完成 run。
2. 实现 B 在消费 `text_delta` 时实时投影到 session，并让共享 Memory 在 loop 内追加消息；异常或取消时保留部分增量。

两者都能声称“service owns session projection”“每个 run 独立 AgentLoop”，但 `/api/session`、刷新恢复、下一次 run 的上下文，以及 completed SSE 中的答案会不同；若共享 Engine/Memory 本身可变，还可能把不同 run 的 usage/model 或半成品消息混入。仅有“同一时刻一个 in-flight run”并不能解决完成后历史和失败回滚语义。

**需要补的契约/测试：** 指定唯一权威状态（建议 run record 先落最终结果，再由同一事务式 reducer 更新 session projection），明确 `queued/running/completed/failed/cancelled/timed_out` 各状态是否进入 session、取消/失败是否保留增量、usage/model 的来源和快照时点；用两次连续 run、取消后刷新、Provider 失败后刷新测试不变量。

### F2（P0）：SSE `Last-Event-ID`、终止和 resync 的边界不具备互操作性

**依据：** AD-4 只规定“单调 per-run IDs”“bounded ring buffer”“从 buffer replay”“窗口外返回稳定 resync error”。没有规定 ID 是从 0/1 开始、`Last-Event-ID=N` 是发送 `>N` 还是 `>=N`、终态事件被淘汰后的行为、终态订阅是否立即关闭、心跳格式/超时，以及 resync 的 HTTP 状态和错误代码。

**两个都合规但会分叉的实现：**

1. 实现 A 将 header 解析为游标，返回严格 `id > N`；run 已结束且没有新事件时立即发送终态（或空流结束）。
2. 实现 B 将 N 当作“最后已处理事件”并从 N 开始 replay，导致重复一条；run 已结束但终态不在 buffer 时保持订阅直到连接超时。

两者都可声称支持重放和“终止后 SSE 清理”，但浏览器会出现重复答案、永不结束的 EventSource 或无法判断需要重新拉 session 的状态。窗口外也可能一个实现返回 `409` JSON，另一个在 SSE 内发送 `resync_required` 后 `200`，客户端无法稳定处理。

**需要补的契约/测试：** 固定 ID 起点、严格大于语义、终态事件不可在 run 可重连窗口内淘汰（或明确终态缺失规则）；规定 terminal SSE 的最后一帧和关闭时机、heartbeat、`resync_required` 的 HTTP 状态/JSON envelope；覆盖 N=0、N=latest、N=oldest-1、终态后重连和重复重连。

### F3（P0）：CLI 自动 HTTP 的生命周期所有权与 shutdown 顺序未定义

**依据：** AD-5 要求 `start()/serve()/close()`，Story 49-2 要求同一 asyncio 生命周期、启动失败显式传播和 bounded close；但没有规定谁拥有 `serve()` task、何时算 ready、单次 CLI run 结束时是否等待 SSE 订阅者、Ctrl+C 的取消顺序，以及 `close()` 是否仍允许发送 terminal/cancelled 事件。

**两个都合规但会分叉的实现：**

1. 实现 A 在 CLI 初始化后创建后台 `serve()` task；Agent 结束后先 `close()` HTTP，再打印最终 CLI 输出。
2. 实现 B 让 HTTP server 作为主 task、REPL/单次 run 作为子 task；Agent 结束后先发布 terminal 事件并 drain SSE，再关闭 listener。

前者可能让浏览器只收到半截流或在 readiness 前看到连接拒绝，后者可能让命令在无浏览器连接时额外等待 drain。端口绑定成功但 ASGI task 尚未 ready 时，两者对“启动成功”的判断也不同；异常传播、Ctrl+C 返回码和残留 task 会随之分叉。

**需要补的契约/测试：** 指定 composition root 的唯一 lifecycle owner；定义 `start` 的 readiness barrier、`serve` task 的取消/异常传播、单次 run 的关闭顺序（停止新请求 → 终态/取消事件 → 关闭订阅 → listener → residual-task timeout）和 CLI 返回码；用 bind failure、startup race、Ctrl+C、无订阅者/有慢订阅者四类测试验证无 orphan task。

### F4（P1）：Host/Origin 校验的缺省值和规范化规则不明确，安全效果可互相矛盾

**依据：** AD-6/Story 49-5 要求对 state-changing 请求校验 Host/Origin、禁止 broad CORS，但没有定义允许的 Host 集合（端口、IPv6、`localhost` 与 `127.0.0.1`）、缺失 `Origin` 的处理、代理头是否可信、SSE/读取请求是否同样校验。

**两个都合规但会分叉的实现：**

1. 实现 A 对浏览器请求强制要求 `Origin`，只允许规范化后的 `http://127.0.0.1:8766`；curl、同源导航和 `Origin: null` 全部拒绝。
2. 实现 B 将缺失 Origin 视为非浏览器客户端，只校验 Host；同时接受 `localhost`、IPv6 loopback 或任意配置端口。

两者都能声称“validate Host/Origin”，但会分别破坏 CLI/自动化客户端或扩大 CSRF/跨主机 DNS rebinding 面。非回环绑定下若把 `X-Forwarded-Host` 当可信来源，风险更大。

**需要补的契约/测试：** 固定 canonical origin 生成规则和允许集合；明确缺失/`null` Origin、Host 端口、IPv6、代理头的拒绝矩阵，并规定状态码/错误码；至少覆盖浏览器同源、curl、恶意 Origin、Host 重绑定和非回环监听。

### F5（P1）：资源/限额契约只有“有界”描述，无法保证部署一致性

**依据：** AD-8 要求 Pydantic settings 和 bounded limits，AD-2 要求 wheel 包含 `src/heagent/web`；但没有给出具体字段、默认值、单位、超限错误码，也没有规定 package-resource 的唯一读取方式或 HTTP extra 缺失时的命令行为。

**两个都合规但会分叉的实现：**

1. 实现 A 用 `importlib.resources.files("heagent.web")`，把静态资源作为 package data；源码 checkout 正常、wheel 也正常，但缺少 Starlette 时仅 `http-server` 报安装诊断。
2. 实现 B 用 `Path(__file__).parent / "web"` 和构建工具的 `include` 配置；源码测试正常，但 wheel 中遗漏资源时根路由在安装环境返回 404；同时把缺少依赖表现为导入时错误或命令时错误。

两者都满足“提供静态资源/可选依赖/显式诊断”的文字要求，却给用户不同的安装结果。限额同样可能选择不同的 prompt 字节数、事件条数、SSE 连接数和 shutdown 秒数，导致 API 客户端无法依赖稳定行为。

**需要补的契约/测试：** 列出每个 `HTTP_*` 字段的默认值、单位、上限和稳定错误码；规定 HTTP 依赖只在 HTTP 命令路径加载；规定 wheel 资源的 package-resource API 和构建清单，并在干净 wheel 安装中执行 health/root/API 验收，而非只检查源码目录。

## 结论

在实现 Story 49-1 前，至少先关闭 F1-F3；它们会改变用户可见的状态、流和进程退出行为。F4-F5 可在同一轮把测试矩阵和配置表补齐，否则后续 Story 的“验收通过”仍可能代表互不兼容的实现。
