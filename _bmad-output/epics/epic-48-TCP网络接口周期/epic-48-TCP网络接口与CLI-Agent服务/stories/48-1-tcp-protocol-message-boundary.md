---
id: 48-1
title: TCP 协议模型与消息边界
status: ready-for-dev
parent_epic: E48
priority: P0
depends_on: []
created: '2026-09-22'
---

# Story 48-1：TCP 协议模型与消息边界

## 用户故事

作为 TCP 客户端开发者，我希望 HeAgent 提供稳定、严格且有界的 JSON Lines 协议，以便请求和响应能够被可靠分帧、校验与关联，而不会因 TCP 半包或恶意超长输入破坏服务。

## 范围

- 新建 `heagent.network` 包和协议模块。
- 定义 Pydantic 请求、成功响应、失败响应及错误模型。
- 定义 UTF-8 JSON Lines 编解码。
- 拒绝未知字段、空 id、空 prompt、非法 JSON 和超长消息。
- 固定稳定错误码，不暴露 Python 异常实现细节。
- 本 Story 不启动 socket，不调用 AgentLoop。

## 边界与约束

**Always**

- 请求和响应跨模块使用 Pydantic 模型。
- 线上响应固定为单行 UTF-8 JSON + LF。
- 请求顶层只能是 JSON object，第一版只允许 `id`、`prompt`。
- 未知字段 fail-closed，不静默忽略。
- CRLF 输入可接受；输出统一 LF。

**Never**

- 不导入 `cli.py`、`wiring.py`、AgentLoop、Provider、Engine 或 ToolRegistry。
- 不读取 Settings、`.env`、文件系统或网络。
- 不实现 session、stream event、system prompt 或客户端运行时配置。

## I/O 与边界矩阵

| 场景 | 输入 | 期望 |
|---|---|---|
| 合法请求 | `{"id":"r1","prompt":"你好"}\n` | `TcpRequest(id="r1", prompt="你好")` |
| 半包 | 两段 bytes，合并后才出现 LF | 编解码函数不自行假设单次 read 等于整条消息 |
| CRLF | JSON + `\r\n` | 合法解析 |
| 空 prompt | `"prompt":"   "` | `empty_prompt` |
| 未知字段 | 含 `system`/`provider` | `invalid_request` |
| 非 object | `[]` / `null` | `invalid_request` |
| 非 UTF-8 | 非法字节 | `invalid_request` 或固定协议错误，不泄露 traceback |
| 超限 | bytes > 配置上限 | `request_too_large` |
| 成功响应 | result 含换行/中文 | JSON 内转义，物理输出仅一行并以 LF 结束 |

## 任务

- [ ] 新建 `src/heagent/network/__init__.py`，只导出稳定协议面。
- [ ] 新建 `src/heagent/network/protocol.py`：请求、响应、错误 Pydantic 模型。
- [ ] 定义错误码 Literal/StrEnum 或等价封闭类型。
- [ ] 提供 bytes→request 与 response→JSONL bytes 的纯函数。
- [ ] 对 `id`、`prompt` 做非空校验，对未知字段使用 `extra="forbid"`。
- [ ] 保证成功/失败响应互斥不变量。
- [ ] 新增 `tests/network/test_protocol.py` 覆盖正反例和字节边界。
- [ ] 如跨模块协议模型放在 `types.py`，须证明它被多个非 network 模块稳定消费；否则留在 network 域内。

## 验收标准

- Given 合法 UTF-8 JSON Lines，when 解码，then 得到严格类型的 `TcpRequest`。
- Given 请求被拆成多个 TCP 片段，when 上层凑齐完整行后交给协议层，then 只解析一次且字段无损。
- Given 未知字段、空 prompt、非法 JSON 或非法 UTF-8，when 解码，then 返回稳定协议错误且不抛泄露实现细节的响应。
- Given 超过最大请求字节数，when 校验，then 返回 `request_too_large`，不构造请求模型。
- Given result 含换行或非 ASCII 字符，when 序列化，then 输出仍是一条合法 JSON Lines 消息并以 LF 结束。

## Definition of Done

- 协议模块无网络和 Agent 依赖。
- 请求/响应字段和错误码有逐字节测试。
- 覆盖空值、未知字段、Unicode、CRLF、非法 UTF-8 和超限。
- `ruff check`、`ruff format --check`、`mypy` 和定向 pytest 通过。

## 代码地图

- `src/heagent/network/__init__.py`：协议公共导出。
- `src/heagent/network/protocol.py`：协议模型与纯编解码。
- `tests/network/test_protocol.py`：黄金协议测试。
- `src/heagent/types.py`：仅在真正需要共享 `TokenUsage` 时引用，不移动既有模型。

## 验证命令

```text
pytest tests/network/test_protocol.py -q
ruff check src/heagent/network tests/network
ruff format --check src/heagent/network tests/network
mypy src --platform linux
```
