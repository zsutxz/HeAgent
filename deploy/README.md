# HeAgent 部署说明

HeAgent 是 CLI 工具 + Python 库，**不是常驻 HTTP 服务**。部署即安装，通过命令行或容器使用。

## 使用方式

### pip install（推荐）

```bash
pip install heagent

# 单次执行
heagent "你的问题"

# 交互模式
heagent
```

### Windows exe（免 Python 环境）

```bash
# 单次执行
heagent.exe "你的问题"

# 交互模式
heagent.exe

# 终端 UI（textual 扩展）
heagent.exe gui
```

exe 为 PyInstaller one-file 单文件产物，含内置工具 / MCP SDK / textual GUI，无需安装 Python 与依赖。

### Docker

```bash
docker compose build
docker compose run --rm heagent "你的问题"   # 单次执行
docker compose run --rm heagent               # 交互模式
```

### 定时任务

HeAgent 内置 cron 调度器（交互模式内 `/cron` 命令或 `cron_add` 工具），进程退出后不持久。生产级定时任务建议外层系统 cron 触发单次执行：

```bash
# crontab -e
0 9 * * * cd /path/to/project && docker compose run --rm heagent '每日任务 prompt'
```

## 仓库部署资产

| 文件 | 用途 | 状态 |
|------|------|------|
| `Dockerfile` | 多阶段构建，非 root 用户，OCI labels | ✅ 就绪 |
| `docker-compose.yml` | `docker compose run --rm` CLI 一次性/交互用法 | ✅ 就绪 |
| `deploy/deploy.sh` | 一键部署脚本（docker / host 两种模式） | ✅ 就绪 |
| `deploy/heagent.spec` | Windows exe 打包 spec（PyInstaller） | ✅ 就绪 |
| `deploy/README.md` | 本文件 | ✅ 当前 |

`deploy/heagent.service` 已移除（交互式 CLI 不适合作为 systemd 守护进程）。

## Windows exe 构建

前置：Windows + Python 3.11+，已安装本项目（含 `[gui]` extra）与 PyInstaller：

```bash
pip install -e ".[gui]"
pip install pyinstaller typer   # typer 仅供 mcp.cli 收集，非运行时依赖

# 构建（在 deploy/ 目录下执行，spec 内相对路径以 deploy/ 为基准）
cd deploy
..\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean heagent.spec
```

产出：`deploy/dist/heagent.exe`（one-file，约 31 MB）。

验证：

```bash
deploy/dist/heagent.exe --help     # CLI 可用
deploy/dist/heagent.exe gui --help # textual GUI 已打包
```

spec 要点：

- `console=True`：heagent 是 CLI 工具（交互式聊天 / 单次执行），非 GUI 窗口程序。
- `collect_all("mcp")`：MCP SDK 含动态子模块导入（stdio/http transport、类型注册），静态分析会漏，须整体收集。
- `collect_all("textual")`：GUI（textual 扩展）含动态 widget/screen 加载，整体收集。
- openai / anthropic / httpx / pydantic 为常规静态导入，由 Analysis 自动追踪。

## 网络入口（`heagent http-server`）

`heagent http-server` 起的是**同进程 2–3 个 listener**（Epic 56 D1 起；期二 D8 加了可选的第二条 WS）：

| listener | 默认地址 | 内容 | 开关 |
|---|---|---|---|
| HTTP+SSE | `127.0.0.1:8766` | 网页控制台、REST、SSE；**不含任何 WS 路由** | `HTTP_HOST` / `HTTP_PORT` |
| WebSocket（主 / 本地） | `127.0.0.1:9001` | 提交 + 订阅 + CLI 旁路（旁路需开关），零 HTTP 路由 | `WS_HOST` / `WS_PORT` |
| WebSocket（对外，可选） | 无（`WS_EXTERNAL_HOST` 非空才启用，端口默认 `9002`） | **只有**提交 + 订阅；token 强制 | `WS_EXTERNAL_HOST` / `WS_EXTERNAL_PORT` |

> ⚠ **端口迁移（Epic 56 的唯一 breaking change）**：Epic 56 之前 WS 端点挂在 HTTP 端口 8766 下；
> 现在在 **9001**，路径不变。旧客户端只需把连接 URL 的端口从 8766 改成 9001。

### 四种部署姿态

1. **单机自用（默认，推荐）**：两个 listener 都绑回环，token 与 TLS 都不需要；本机客户端连
   `ws://127.0.0.1:9001/...`。
2. **对外只读订阅**：`WS_HOST=0.0.0.0` + `WS_AUTH_TOKEN`（用户级 `~/.heagent/setting.md`）——客户端必须
   带 `Authorization: Bearer <token>`；缺 token **拒绝启动**（fail-closed）。
3. **对外且加密**：在姿态 2 基础上配 `WS_TLS_CERT_FILE` / `WS_TLS_KEY_FILE`（PEM，二者必须同时给），
   listener 走 `wss://`。不配 TLS 时启动会打 `event=plaintext_external` 告警（明文运行可见）。
4. **本机免 token + 对外带 token 同时服务（期二双监听）**：主 listener 保持回环（姿态 1 的体验不变），
   另配 `WS_EXTERNAL_HOST` 起第二条对外 listener。客户端从 9001（本机）或 9002（对外，带 token）连
   **同一个** run；两条 listener 共享运行状态机，因此 9001 提交的 run 可以从 9002 订阅（反之亦然）。
   对外那条可用 `WS_EXTERNAL_TLS_CERT_FILE` / `WS_EXTERNAL_TLS_KEY_FILE` 单独上 TLS（不给则整对继承
   `WS_TLS_*`），于是「本地明文 + 对外 wss」可配。
   若对外只给「看」不给「下命令」，加 **`WS_EXTERNAL_READONLY=true`**（或 `--ws-external-readonly`）：
   那条 listener 不再注册提交端点 `/api/runs/ws`，已订阅连接上的 `cancel` 被拒绝（不断连、运行不受影响）。

```dotenv
# 姿态 4 示例：主 listener 回环免 token；对外的第二条 listener 带 token（token 仍只在 setting.md）
WS_HOST=127.0.0.1
WS_PORT=9001
WS_MAX_CONNECTIONS=16
WS_EXTERNAL_HOST=0.0.0.0
WS_EXTERNAL_PORT=9002
WS_EXTERNAL_TLS_CERT_FILE=/etc/heagent/tls/fullchain.pem
WS_EXTERNAL_TLS_KEY_FILE=/etc/heagent/tls/privkey.pem
# WS_EXTERNAL_READONLY=true    # 只读旁观：不让远程客户端提交 run / 取消 run
```

**双监听的配置约束**（不满足即拒绝启动，fail-closed）：

- `WS_EXTERNAL_HOST` **必须非回环**——回环已由主 listener 承担；
- 主 listener 自己已是非回环（姿态 2/3）时**不要**再配 `WS_EXTERNAL_HOST`（两个对外入口只会让运维无从选）；
- `WS_EXTERNAL_TLS_*` **成对**给或都不给（只给一半拒绝启动）——绝不 A 的证书配 B 的私钥；
- **CLI 旁路 `/api/cli/ws` 只挂在本地 listener 上**：对外 listener 不注册该路由（终端事件可能含文件内容，
  token 只降低风险、不消除风险）。若主 listener 本身是对外模式（姿态 2/3）且打开了
  `WS_CLI_BYPASS_ENABLED`，旁路会被**跳过**并打 `ws event=cli_bypass_skipped` 告警。

```dotenv
# 姿态 2/3 示例：单个对外 listener（不带 TLS 时明文，启动告警）
WS_HOST=0.0.0.0
WS_PORT=9001
WS_MAX_CONNECTIONS=16
WS_TLS_CERT_FILE=/etc/heagent/tls/fullchain.pem
WS_TLS_KEY_FILE=/etc/heagent/tls/privkey.pem
```

```yaml
# ~/.heagent/setting.md（用户级，优先级低于项目 .env；但 WS token 只从这里读）
---
WS_AUTH_TOKEN: <随机长串，建议 openssl rand -hex 32 生成>
---
```

**为什么 token 只认用户级文件**：项目 `.env` 常常被仓库 / CI / 其他人写，若它也能供给 token，
仓库作者就能预置一个「攻击者已知」的凭证让对外监听器照单全收。写在项目 `.env` 里**不生效**，
启动时会有显式告警，配置面板也会把它列为未知键。

### 安全前置（必读）

- HTTP 入口（8766）**无认证、无 TLS**，回环绑定不等于可信——**不要**把它绑到非回环地址后直接暴露公网，
  也不要在它前面套反向代理（`forwarded-*` 头会被直接拒绝，反向代理部署不在支持范围）。
- WS 对外模式的 token 认证**不是绝对边界**：token 会泄露、明文可被中间人观察；限速只挡同一来源的
  暴力尝试。需要更强的隔离就在前面加 TLS，并把整个进程放进容器 / VM。双监听（姿态 4）不改变这一点：
  两条 listener 共享同一运行状态机，对外那条的 token 只保护「谁能连上它」，不隔离「连上后能做什么」
  （仍是单用户语义：能提交 run 就能让 Agent 执行 `shell`）。
- 经 HTTP 或 WS 提交的 run 会真的执行 Agent（含 `shell` 工具）⇒ **容器沙箱档（`--sandbox docker`）
  强烈建议**（`.env` 里 `SANDBOX_BACKEND=docker`）；它仍不是绝对边界，见 `docs/sandbox.md`。
- 浏览器 WebSocket API 无法自定义请求头 ⇒ 对外模式面向 IDE 插件 / 桌面客户端；浏览器侧仍用 HTTP 控制台。

## 生产前检查项

- **API Key**：通过 `.env.production` 或环境变量注入，勿硬编码。
- **工作目录**：`.heagent/` 含技能、记忆、会话、快照、Cron 数据，确保持久化（Docker 用 volume）。
- **OS 级沙箱**：`shell` / MCP 工具执行不可信代码，须容器或 firejail 等 OS 级隔离（`SafetyGuard` 非真正安全边界）。
- **网络权限**：限制出站到必需的 LLM API 端点即可。
- **备份**：`.heagent/` 定期备份。
- **日志**：生产环境建议 `LOG_LEVEL=WARNING`。

## 版本发布

```bash
# 打与 pyproject.toml 一致的版本 tag 触发 CI release（PyPI + GHCR + Docker Hub）
git tag v0.8.3
git push origin v0.8.3
```

`v0.8.3` 是当前待创建的发布 tag；发布前应确认它与 `pyproject.toml` 和 `src/heagent/__init__.py` 的版本一致。Docker Hub 推送还依赖 CI secrets `DOCKERHUB_USERNAME` 与 `DOCKERHUB_TOKEN`，未配置时该步骤不可用。

CI release job 自动：
1. `twine check` → PyPI（Trusted Publisher OIDC）
2. `docker buildx` → GHCR + Docker Hub（multi-arch: amd64 + arm64）
