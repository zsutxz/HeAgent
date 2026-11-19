---
epic: epic-67-安全增强
date: 2026-11-18
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# Epic 67 Retrospective

> 路径约定：`tickets/story-67.*` 均相对 `_bmad-output/initiative-heagent/tickets/epic-67-安全增强/`；
> 其余路径相对仓库根。实测为收口现场取证（2026-11-18，容器内 `.heagent/tmp/py311-venv-linux/bin/python`）。

## Epic summary

**Epic**：epic-67-安全增强（R14 / R15 / R16；10 story，全部新建）

**票态**：10/10 `done`，无 `dropped`。

| Entry | 交付 | 提交 |
|---|---|---|
| 67.1 统一输入验证框架 | `pub/validation.py`（`Rule` / `collect_issues` / `validate` / `InputValidationError`），接入 `config/write.py::guard_reason` | `218dd9b` |
| 67.2 工具执行审计 | `pub/audit.py`（追加式 JSONL + 脱敏）+ `heagent audit list\|export\|verify`，`ToolExecutor.execute` 包围 | `218dd9b` |
| 67.3 敏感操作留痕 | `record_operation` + `prev`/`digest` 哈希链 + `verify_chain`；会话删除 / 技能删除归档 / 网页配置写入 | `218dd9b` |
| 67.4 密钥轮换提醒 | `config/rotation.py` + `KEY_ROTATION_REMIND_DAYS`（默认 90，0 关闭） | `68c1ee2` |
| 67.5 keyring 读取 | `config/keyring_store.py` + `KEYRING_ENABLED`（`Settings.secret()` 为唯一收敛点） | `68c1ee2` |
| 67.6 依赖漏洞扫描 | CI `pip-audit --strict -r requirements.lock --format json --output pip-audit.json` + artifact | `c50ce28` |
| 67.7 端点安全测试 | `tests/network/test_endpoint_security.py`（覆盖表 == `transport_routes.json` 集合，11 例） | `b4d0e79` |
| 67.8 沙箱逃逸测试 | `tests/test_sandbox_escape.py`（7 向量 / 17 例，3 例 `integration`） | `b4d0e79` |
| 67.9 依赖精简 | `mcp` 移出核心依赖（7 → 6，-14.3%），`tools/mcp/sdk.py` 收口 SDK 导入 | `c50ce28` |
| 67.10 依赖锁定 | `scripts/lock_requirements.py` + `requirements.lock`（102 行） | `c50ce28` |

## 判据看点（不是「有测试」而是「拒在哪一层」）

- **67.1**：框架只补「跨字段/业务级规则」，不重造类型系统；唯一接入点是仓库里唯一非 pydantic 的手写校验面
  （`config/write.py::guard_reason`），对外原因文案逐字不变（`must be one of …` / `must be at least N` /
  `must be a number` / `must be a finite number`）。
- **67.2 / 67.3**：审计是 observability 事件总线的**旁路消费者**，不改事件契约；写失败只 WARNING（fail-soft）；
  `run_context` 是鸭子契约（缺 `session_id` / `workspace_root` 的替身按「无该归属」处理）。
- **67.7**：本地模式**没有 HTTP 认证**，所以「未认证」这一类落在外层防线上（Host 伪装 403），
  而不是伪造一个 401；WS 侧按真实认证门（`accept` 之前 close 1008）与只读路由可见性分别测。
- **67.8**：每个向量三段式（攻击动作 → 拒绝层 → 断言），并尽量带**正面控制**（证明「什么都没发生」
  不是因为路径不存在）。

## 收口实测

```text
pytest tests/test_input_validation.py tests/test_audit_log.py tests/test_sensitive_trace.py \
       tests/test_key_rotation.py tests/test_keyring_store.py -q      → 98 passed
pytest tests/network/test_endpoint_security.py -q                     → 11 passed
pytest tests/test_sandbox_escape.py -q                                → 17 passed（3 integration deselected）
pytest -q -k mcp                                                      → 223 passed
pytest -q                                                             → 5208 passed / 51 skipped / 30 deselected / 1 xfailed
```

## 决策与刻意不做的事

- **不替换 pydantic 模型校验**，也不引入新依赖（框架零 heagent 运行时依赖，只 stdlib + pydantic + 同层 `pub`）。
- **哈希链只做「篡改可检出」**，不做密码学不可篡改（不加外部密钥管理）；碰撞面属自证范畴，如实写进 plan。
- **不换扫描器**（不引 safety）、**不把联网扫描放进默认本地门**（`--with-audit` 显式开启）。
- **不动 `openai` / `anthropic` / `httpx`**：前两个是主用途依赖、移出会破坏默认安装可用性，
  `httpx` 是代码直接 import 的真实依赖。
- **不给审计文件加轮转**：哈希链让「简单截断」变成断链，retention 需要先定语义（登记 A61）。

## Open questions / 残留（全部已登记台账）

1. **A60｜keyring 未声明可选 extra**：`pyproject.toml` 没有 `[keyring]`，诊断给裸 `pip install keyring`，
   而 67.5 的 plan 写的是「可选 extra」。闭合动作 = 加 extra + 诊断改 `heagent[keyring]`。
2. **A61｜审计面无 retention**：每次工具执行一行，无条数/字节上限，`audit list/export/verify` 整文件读入。
3. **A62｜留痕只覆盖网页写通道**：CLI 的 `heagent init` / 配置向导写 `.env` / `setting.md` 不入链。
4. **A63｜缺 mcp 的诊断无判据**：`McpSdkMissingError` 的类名只出现在契约基线里，
   `pytest -k mcp` 全绿是因为开发环境装了 mcp。
5. **A66｜依赖锁与扫描口径未定**：`requirements.lock` 是从本机**全量环境**（dev/gui/http/mkdocs）
   导出的，不是纯运行时锁；无 pyproject 漂移门；pip-audit 已阻塞但没有 CVE 白名单/复核期限。
6. **「输入验证统一」的覆盖面**：框架目前只在配置写入一个入口生效（HTTP 体仍是 pydantic、CLI 仍是 click）。
   这是 67.1 Boundaries 的自觉取舍（不重造类型系统），但 Epic Outcome 的措辞比实际宽——
   若后续要扩接入面，应按入口逐个立项，而不是把框架当成已全覆盖。
