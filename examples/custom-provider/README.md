# 示例：扩展 Provider

演示 Provider 扩展点的最小完整实现：**不继承**任何基类，只实现 `send` / `stream` / `get_metadata`
三个方法，就能被 `Agent` 接受。

## 运行

```bash
python examples/custom-provider/main.py
```

不需要网络、不需要 API key。

## 期望输出

```text
isinstance(BaseProvider): True
metadata: {'name': 'echo', 'model': 'echo-1', 'supports_streaming': True, 'supports_tools': False}
send 路径: [echo] 你好，HeAgent
stream 块数: 1
```

（若本机 `SANDBOX_BACKEND` 指向不可用后端，最前面会多一行 fallback 提示，与本示例无关。）

## 三个方法各自的契约

| 方法 | 必须做什么 | 常见坑 |
| --- | --- | --- |
| `async send(messages, *, tools=None)` | 返回完整 `ProviderResponse` | `usage` 必须给且 `total_tokens > 0`，否则运行统计与 token 校准拿不到样本 |
| `stream(messages, *, tools=None)` | 返回 `AsyncIterator[ProviderResponse]` | 声明成 `async def` + `yield`；**不要**写成返回 coroutine 的普通函数（协议按 async generator 匹配） |
| `get_metadata()` | 返回 `ProviderMetadata` | `name` / `model` 会被 `/provider` 列表与状态行读取，别留空 |

`send` 的 `messages` 是 **pydantic 的 `Message` 列表**（不是 dict）：用 `message.role` /
`message.content` 属性访问。

## 接到真实后端

把 `send` 里的构造换成一次 HTTP 调用即可，返回同样的 `ProviderResponse`。若要复用本仓的
OpenAI 兼容实现，直接构造现成 Provider 更省事：

```python
from heagent import OpenAIProvider

provider = OpenAIProvider(api_key="<your-key>", base_url="https://your-endpoint/v1", model="your-model")
```

注意：

- 新增 Provider 文件**不得**从 `heagent.agent` 导入（架构硬约束：下层不得反向依赖入口/循环层）。
- 多 Provider 自动回退用 `ProviderChain`，见 [`examples/provider-chain/`](../provider-chain/)。
- 认证失败的语义在不同组合里不同：`ProviderChain` 会换下一家，路由池内换档只对限流/瞬时错误
  （判据见 `providers/retry.py`，本示例不涉及）。
