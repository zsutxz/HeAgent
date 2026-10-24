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

`heagent http-server` 起的是**同进程两个 listener**（Epic 56 D1 起）：

| listener | 默认地址 | 内容 | 开关 |
|---|---|---|---|
| HTTP+SSE | `127.0.0.1:8766` | 网页控制台、REST、SSE；**不含任何 WS 路由** | `HTTP_HOST` / `HTTP_PORT` |
| WebSocket | `127.0.0.1:9001` | 三条 WS 端点（提交 / 订阅 / CLI 旁路），零 HTTP 路由 | `WS_HOST` / `WS_PORT` |

> ⚠ **端口迁移（Epic 56 的唯一 breaking change）**：Epic 56 之前 WS 端点挂在 HTTP 端口 8766 下；
> 现在在 **9001**，路径不变。旧客户端只需把连接 URL 的端口从 8766 改成 9001。

### 三种部署姿态

1. **单机自用（默认，推荐）**：两个 listener 都绑回环，token 与 TLS 都不需要；本机客户端连
   `ws://127.0.0.1:9001/...`。
2. **对外只读订阅**：`WS_HOST=0.0.0.0` + `WS_AUTH_TOKEN`（用户级 `~/.heagent/setting.md`）——客户端必须
   带 `Authorization: Bearer <token>`；缺 token **拒绝启动**（fail-closed）。
3. **对外且加密**：在姿态 2 基础上配 `WS_TLS_CERT_FILE` / `WS_TLS_KEY_FILE`（PEM，二者必须同时给），
   listener 走 `wss://`。不配 TLS 时启动会打 `event=plaintext_external` 告警（明文运行可见）。

```dotenv
# 示例：项目 .env 里只放绑定与限额；token 不放这里（见下）
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
  暴力尝试。需要更强的隔离就在前面加 TLS，并把整个进程放进容器 / VM。
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
git tag v0.8.2
git push origin v0.8.2
```

`v0.8.2` 是当前待创建的发布 tag；发布前应确认它与 `pyproject.toml` 和 `src/heagent/__init__.py` 的版本一致。Docker Hub 推送还依赖 CI secrets `DOCKERHUB_USERNAME` 与 `DOCKERHUB_TOKEN`，未配置时该步骤不可用。

CI release job 自动：
1. `twine check` → PyPI（Trusted Publisher OIDC）
2. `docker buildx` → GHCR + Docker Hub（multi-arch: amd64 + arm64）
