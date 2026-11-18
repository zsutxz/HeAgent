# 示例：ProviderChain 故障转移

演示 `ProviderChain` 的语义：按顺序尝试，前者抛**可回退**错误时切下一个；全部失败则重置并抛出。

## 运行

```bash
python examples/provider-chain/main.py
```

不需要网络。

## 期望输出

```text
回答: [healthy] 我接住了这次调用（第 1 次）。
当前生效 Provider: BrokenProvider
broken 尝试次数: 1
healthy 调用次数: 1
```

此外 stderr 上会有一行回退日志（`Provider broken failed (transient): broken is down`）
——它由 `logging` 输出、是否显示取决于日志级别，不属程序的标准输出，所以不列在上面。
若你的 `.env` 指向本机不可用的沙箱后端，还会多一行 fallback 提示。

## 三个要点

1. **只有特定错误才回退**。`BrokenProvider` 抛 `ProviderError(status_code=503)`
   ——`TRANSIENT`，会被回退。把它换成 `RuntimeError("down")` 就不会回退（分类为 `NON_TRANSIENT`），
   因为「换一家 Provider 不会让坏请求变好」。

   | 类别 | 触发 | `ProviderChain` 是否回退 |
   | --- | --- | --- |
   | `RATE_LIMITED` | 429 / 消息含 rate | 是 |
   | `AUTH_FAILED` | 401 / 403 | 是（换一家凭据能救） |
   | `TRANSIENT` | 5xx / timeout / connection | 是 |
   | `NON_TRANSIENT` | 400 / 422 等 | **否**，立即抛出 |

2. **index 不粘性**：成功一次后索引复位到链首（输出里
   `当前生效 Provider: BrokenProvider` 就是这个语义——本次调用成功了，但下次仍先试第一家）。
   想要「粘住可用的一家」是另一种策略（`SwitchableProvider` 的 `/provider`），不属于本示例。

3. **异常统一包装**：链上抛出的任何异常最终都以 `ProviderError` 形式离开 `send()`，
   调用方不必 catch 各家 SDK 的异常类型。

## 变体

- 只想按顺序试固定几家真实 Provider：`ProviderChain([deepseek, openai, anthropic])`
  （构造真实 Provider 见 [`examples/custom-provider/`](../custom-provider/)）。
- 想在同一批凭据里换**档位**（fast/mid/pro）：那是 `ROUTING_POOLS` 的 `RoutingProvider`，
  回退判据不同（认证失败不换档，因为那是配置问题）。
