# Provider 层（`providers/`）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.3** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.3」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.3 Provider 层 (`providers/`)

### base.py — Protocol 定义

```python
class BaseProvider(Protocol):
    async def send(messages, *, tools) -> ProviderResponse
    async def stream(messages, *, tools) -> AsyncIterator[ProviderResponse]
    def get_metadata() -> ProviderMetadata
```

使用 `typing.Protocol`（结构化子类型），无需继承。

### composition.py — 装配规则真身（批次 9 卡 B 迁入）

- 从 `Settings` 读配置 → 造 provider 栈（6 条目 × 单模型/声明式路由池、named 插入序契约、Ollama 准入）——原 `cli/wiring.py` 组合根，2026-11-07 迁入 providers 层
- 致命配置错误抛 `ProviderConfigError`；终端呈现（`click.echo(err=True)` + `SystemExit(1)`）由 `cli/wiring.py` 呈现薄壳完成——搬规则不搬呈现
- `settings` 参数注入；`Settings` 仅 TYPE_CHECKING 引用，运行期零 config 依赖

### openai.py — OpenAI 兼容 Provider

- 支持自定义 `base_url`（DeepSeek、智谱 AI 等）
- 消息/工具调用格式转换：HeAgent ↔ OpenAI API
- **本地 Ollama**：`ollama_enabled=true` 时 CLI 构建 `ollama` 条目（`OpenAIProvider`，`base_url` 指向 Ollama `/v1`）。Ollama 不校验 API Key，故以**显式开关**（而非密钥存在性）判定是否构建——默认关闭，避免默认向 localhost 发请求、也避免「装了没启动」混进回退池；`ollama_model` 未配置时 fail-fast（不猜模型名）

### anthropic.py — Anthropic Provider

- 提取系统消息（`_extract_system()` 合并为 Anthropic 顶层 `system` 字段）
- 消息/工具调用格式转换：HeAgent ↔ Anthropic API
- **提示词缓存（FR-3）**：两处 `cache_control: {"type": "ephemeral"}` 断点——system prompt 末块
  （`_build_system_param()`）与**最后一个工具定义**（`_to_anthropic_tools()`）。Anthropic 的缓存前缀
  按 `tools → system → messages` 累计，断点落在 tools 末尾即可把整段工具 schema（通常比 system 还大）
  一起纳入；断点必须是块边界，只打这两个，多打既无收益也会被 API 拒。
  由 `anthropic_prompt_caching` 开关控制（默认开启；使用不支持 cache_control 的代理时应关闭）

### chain.py — Provider 回退链（**外层**）

有序 Provider 列表，失败时自动切换下一个。**回退精度（FR-4）**：仅对
`RATE_LIMITED` / `AUTH_FAILED` / `TRANSIENT` 错误回退；`NON_TRANSIENT`（400/422 等客户端错误）
立即抛出——切换 Provider 不会让坏请求变好，回退只会浪费配额并掩盖真实问题。
所有抛出异常经 `_raise_provider_error()` 统一为 `ProviderError`（已是 ProviderError 则原样
抛出保留既有 cause 链，否则包装并保留原始 cause 与状态码），避免裸 SDK 异常穿透到 CLI。

```
ProviderChain([deepseek, KeyRotatingProvider([anthropic×N])])
  │
  ├── 当前 Provider → 失败(可回退) → _advance() 切下一个 Provider
  ├── 任一 NON_TRANSIENT → 立即抛出 ProviderError（不回退）
  └── 全部失败 → _current_index 恢复到起始位，抛出最后的 ProviderError
```

### key_rotation.py — 密钥池轮换（**中层**）

同一 Provider 类型的多实例包装（每个实例使用不同 API Key）。`429/401/403`
（或消息含 rate/auth/forbidden 关键词）时自动切换到下一个密钥重试；密钥池全部耗尽后
恢复原索引并抛出异常，交由上层 `ProviderChain` 回退到其他 Provider 类型。
`get_metadata()` 名称带 `+keypool` 后缀以便日志区分。`send()`/`stream()` 双路支持轮换。

### retry.py — 错误分类与重试（**内层** + 共享分类器）

`classify_exception()` / `classify_error()` 将错误分为四类，供三层共用：

```
错误分类（优先级：429 > 401 > 5xx > 其他）：
  RATE_LIMITED (429)      → ProviderChain 回退 / KeyRotating 轮换；retry 中间件不重试
  AUTH_FAILED (401/403)   → ProviderChain 回退 / KeyRotating 轮换；retry 中间件不重试
  TRANSIENT (5xx/超时/过载) → retry 中间件指数退避 + 随机抖动重试；也触发 ProviderChain 回退
  NON_TRANSIENT (400/422) → 各层均不重试/不回退，立即抛出
                           （唯一例外：404 model 不可用仍触发池内换档回退，判据见 is_pool_fallback_error）
```

`retry_with_backoff()` 仅对 `TRANSIENT` 错误重试；`make_retry_middleware()` 将其包装为
Middleware 接入 `AgentLoop.middlewares`。

**三层故障转移组装**（cli.py `_build_provider()`）——由内到外依次接管可恢复错误：

```
AgentLoop
  ├─ provider = ProviderChain([                    # 外层：跨 Provider 类型回退（NON_TRANSIENT 不回退）
  │     deepseek,                                   #   单 key
  │     KeyRotatingProvider([anthropic k1, k2, ...])# 中层
  │   ])
  └─ middlewares = [make_retry_middleware()]         # 内层：仅 TRANSIENT 指数退避重试
```

### switchable.py — 运行时多 vendor 切换（**外层选择层**）

`SwitchableProvider` 持有 `{名称: provider}` 池（每个命名 provider 独立 key/base_url/model），实现 `BaseProvider` 协议、对 `AgentLoop` 透明。与 `ProviderChain` 的全自动按序回退不同，它以**用户当前选择**为默认起点，自动回退仅作「当前选择不可用时的应急接管」：

- **手动切换**：`switch(name)` 经交互模式 `/provider` 命令触发（cli.py）。
- **自动回退**：当前 provider 抛 `RATE_LIMITED`/`TRANSIENT`（429/5xx/超时）或 404 model 不可用（`is_pool_fallback_error`，2026-11-12 起）时自动切到池中下一个；`AUTH_FAILED`/其余 `NON_TRANSIENT` 不回退（与 chain 同精度）。
- **粘性停留**：成功回退后 `_active` 更新为新 provider，后续不再重试已限流的旧 provider。
- **流式约束**：`stream()` 已下发 chunk 则不回退，防重复前缀。

可包住 `ProviderChain` 等任意 provider，与三层容错叠加：用户选择（switchable）→ 跨类型回退（chain）→ 多 key 轮换（key_rotation）→ 重试（retry）。

### router.py — 智能路由（按任务特征选模型，**主动选择层**）

`RoutingProvider` 持有 `{名称: provider}` 池，每次 `send`/`stream` **调用前**由 `Router`
根据请求内容（消息历史 + 工具列表）**主动**决定用哪个 provider——与 `SwitchableProvider`/
`ProviderChain` 的「出错才切换」正交（本类在无错误的正常路径上做主动选择）。对 `AgentLoop`
透明（实现 `BaseProvider` 协议）。

- `HeuristicRouter`：**默认尽量用 fast（只按当前请求判定）**，决策顺序 = ① **推理链续接**
  （**默认关闭**，`continuity=True` / `ROUTING_REASONING_CONTINUITY=true` 时启用：**上一轮
  实际选中 pro** 且历史里仍有 ASSISTANT 的 `reasoning_content` → 继续 pro；默认关是因为它
  会把会话钉在 pro，与「尽量 fast」冲突）→ ② **复杂度关键词**（扫描**最近一条 USER
  消息**，反向查找以跳过尾部 ASSISTANT/TOOL，命中 `DEFAULT_REASONING_KEYWORDS` 或自定义词
  → pro）→ ③ **中档关键词**（配置 mid 档时，同样只看最近一条 USER 消息 → mid）→ ④ 兜底
  fast。关键词范围是「最近一条 USER 消息」而非「全部历史」——历史命中过关键词不会让后续
  轮次（含简单追问）持续走 pro；反向查找则保证同一轮 tool 调用后（尾部是 TOOL 结果）仍
  能取到本轮请求，不漏判。判据 ① 以「上一轮是否 pro」而非「历史有无
  `reasoning_content`」为准——DeepSeek v4 的 flash/pro 都是思考模型、都返回该字段，按后者
  会让走过一次 flash 后永久锁死 pro；`RoutingProvider._pick` 经可选钩子 `note_selection`
  回传实际选中项（供判据 ①）。内置复杂度表不含「为什么」「解释」「why」「explain」等纯疑问词
  （pro 主要误判源），需要时用该池 `ROUTING_POOLS` 的 `keywords` 追加回来。纯启发式（非安全机制）。
- `RoutingProvider.send/stream`：`_pick()` 决策 → 未知名称回退 `default` → 委托。
- `last_decision`（`RouteDecision`）记录最近一次决策，供日志/`/model` 命令观测。
- **决策可见性**：`active_route_reason()` / `annotate_route()` 把最近一次决策的 reason 附到
  状态行模型名后（如 `deepseek-v4-pro←keyword:分析`），使「**为什么**是这个模型」当场可解释
  ——关键词命中、推理链续接、`/model` 强制、池外名称回退四种来源在状态栏上原本完全同形，
  只能靠猜或翻日志。未启用路由 / 尚未决策时 `annotate_route` 原样返回模型名（展示串逐字节
  不变）；CLI 状态行（`cli.display._format_status`）与 GUI 状态栏共用该标注。兜底理由
  `default_fast`（「没命中关键词、用默认档」）**不进展示层**——状态行不贴、`/model` 的
  `last decision` 行不显示括号内理由（`display_reason()` 是唯一白名单入口，两处共用）。
  它不解释任何东西，还易被误读成模型名；需要观测时看日志（`active_route_reason()` 仍
  原样返回 `default_fast`）。
  `/model <name>` 的强制与 `last_decision` **同步刷新**（`set_force` 即时写入 `forced`；
  清空强制时置空决策）——否则命令之后、下一次 LLM 调用之前，提示符会显示「新模型 +
  旧理由」的混合态（模型已换 luna、理由还是上一次的 `keyword:分析`），据此无法判断
  到底强制了没有。
- CLI：路由池是**声明式**的——`ROUTING_POOLS`（JSON）按 provider 条目名声明池：
  档位（池内名 → 模型名）、角色映射（fast/mid/pro → 池内名）、默认档、各档追加关键词、
  `base_url` 覆盖。`_build_provider` 对每个条目查 `Settings.routing_pool_map`：命中即构建
  `RoutingProvider`（规格由 `RoutingPoolSpec` 校验，`pub/types.py`），否则单模型条目；两种情况
  都照常放入 `SwitchableProvider` 池（Multiple providers Choose / `/provider` 切换不受影响）。
  **新增/调整档位、模型名、角色、关键词全部只改配置，无需改代码**（新增 provider 条目仍需
  代码接入凭据）。路由池**只有这一个入口**：条目出现在 `ROUTING_POOLS` 里即为启用该池；
  旧版按 provider 的开关（`ROUTING_ENABLED` / `ROUTING_FAST_MODEL` / `ROUTING_PRO_MODEL` /
  `ROUTING_REASONING_KEYWORDS` / `GPT_ROUTING_*`）已移除。全局仅保留
  `ROUTING_REASONING_CONTINUITY`（所有池的续接默认值，可在池内覆盖）。
  `/model <池内名>` 命令解包嵌套路由、展示当前生效池与最近决策；状态行同一决策另见
  `active_route_reason`。
