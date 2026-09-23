---
id: 49-6
title: 浏览器体验、打包与回归收口
status: backlog
parent_epic: E49
priority: P0
depends_on: [49-4, 49-5]
created: '2026-09-23'
---

# Story 49-6：浏览器体验、打包与回归收口

## 用户故事

作为 HeAgent 用户和维护者，我希望网页聊天体验在源码和安装包中都能稳定工作，并有完整回归证据，以便可以实际使用和维护 HTTP MVP。

## 范围

- 完成内置聊天页：消息列表、多行输入、提交/停止、运行状态和空状态。
- 展示 SSE 文本增量、工具活动、结果、错误、取消、冲突、重连和服务关闭状态。
- 确保提示词、回答和工具目标按纯文本渲染，页面不加载第三方脚本。
- 配置 wheel/源码包正确包含静态资源和可选 HTTP 依赖。
- 补充 README、docs 索引、`docs/frame.md`、配置示例和 MVP 安全边界。
- 执行 HTTP、网络、CLI、GUI、Agent、ruff、format 和 mypy 回归。

## 边界与约束

**Always**

- UI 与 API 同源，使用现有 HTTP 端点，不复制 Agent 运行逻辑。
- 页面状态映射服务端状态，断线/错误/取消显式呈现。
- 验证安装包，不只验证源码目录运行。
- 文档以 `src/` 和本 Epic 当前实现为准，明确不支持未经认证的远程使用。

**Never**

- 不引入与 MVP 无关的管理后台、配置编辑、多用户或持久会话。
- 不通过 innerHTML 或 Markdown 原样注入不可信 Agent 输出。
- 不用“测试能启动”替代 SSE、取消、重连、资源清理和打包验证。
- 不修改现有 CLI/TCP/GUI 的行为来迁就网页 UI。

## 任务

- [ ] 完成 `src/heagent/web/` 静态 HTML/CSS/JS 聊天界面。
- [ ] 映射运行、工具、取消、错误、重连和 session 状态。
- [ ] 更新 pyproject 打包配置与可选 HTTP extra，并验证 wheel 内容。
- [ ] 更新 README、`docs/README.md`、`docs/frame.md` 和配置示例。
- [ ] 增加浏览器/HTTP 集成测试与静态资源加载测试。
- [ ] 运行定向 pytest、全量回归、ruff、format、mypy 和必要的手工浏览器验收。

## 验收标准

- Given 用户打开内置网页，When 页面加载，Then 能看到消息列表、多行输入、提交/停止操作和清晰的空状态。
- Given 用户提交 prompt，When SSE 推送文本和工具事件，Then 页面按顺序更新回答、工具目标、工具结果和终态，不渲染不可信 HTML。
- Given 页面处于运行、重连、取消、失败、冲突或服务关闭状态，When 状态发生变化，Then 页面显示对应可理解反馈，并避免重复提交。
- Given 项目构建 wheel 并在干净环境安装，When 启动 HTTP 服务并请求根路径，Then 静态资源和 API 均可用，不依赖源码目录或开发机绝对路径。
- Given 执行 HTTP 定向测试、现有网络测试、ruff 和 mypy，When 质量门禁运行，Then 新增功能通过且现有 CLI、GUI、TCP 和 Agent 回归不受影响。

## Definition of Done

- 内置网页覆盖 UX-DR1–UX-DR6 的主要状态和交互。
- 源码运行、wheel 安装、浏览器手工验收和自动化测试均有记录。
- README、docs 索引、docs/frame.md、配置示例和 HTTP MVP 边界保持一致。
- Epic 49 的 FR1–FR10、NFR1–NFR10 与 UX-DR1–UX-DR6 都能追溯到实现和测试。

## 代码地图

- `src/heagent/web/`：HTML/CSS/JS 静态聊天界面。
- `pyproject.toml`：可选 HTTP 依赖和静态资源打包配置。
- `README.md`、`docs/README.md`、`docs/frame.md`：启动、架构和安全边界文档。
- `tests/test_http_web_ui.py`：静态资源和 API/UI 契约测试。
- `tests/test_http_integration.py`：StubProvider 浏览器流程模拟。
- `scripts/quality_gate.py`：质量门禁入口。

## Review Status

Story 范围与验收标准已确认，待实现验证。

## Requirement Traceability

FR3–FR9; NFR3, NFR5, NFR6, NFR7, NFR9, NFR10; UX-DR1–UX-DR6。
