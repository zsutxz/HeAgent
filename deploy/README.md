# HeAgent 部署说明

HeAgent 是 CLI 工具 + Python 库，**不是常驻 HTTP 服务**。部署即安装，通过命令行或容器使用。

## 使用方式

### pip install（推荐）

```bash
pip install heagent

# 需要 MCP 桥接时加装可选 extra（核心依赖不含 MCP SDK；缺它只影响 MCP 能力）
pip install "heagent[mcp]"

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

`heagent http-server` 起的是**同进程 2 个 listener**（HTTP + **单条** WS；Epic 72 起第二条 WS listener 已退役）：

| listener | 默认地址 | 内容 | 开关 |
|---|---|---|---|
| HTTP+SSE | `127.0.0.1:9101` | 网页控制台、REST、SSE；**不含任何 WS 路由** | `HTTP_HOST` / `HTTP_PORT` |
| WebSocket | `127.0.0.1:9201` | 提交 + 订阅 + 通知流（中枢注入时）+ CLI 旁路（仅回环、需开关），零 HTTP 路由 | `WS_HOST` / `WS_PORT` / `WS_LAN_NO_AUTH` |

> ⚠ **端口迁移（Epic 56 的唯一 breaking change）**：Epic 56 之前 WS 端点挂在 HTTP 端口 8766 下；
> 现在在 **9001**（2026-10-29 起默认 9901，**2026-11-04 起默认 9201**），路径不变。旧客户端只需把连接 URL 的端口从 8766 改成启动公告里的实际端口。

> **连接首帧（56-9 起）**：全部 WS 端点在 `accept()` 后、任何配额/游标/关停判定前下发首帧 `{"type":"hello","version":"…"}`——客户端可据此做版本兼容判断；按「可忽略类型」处理（不认识的类型跳过）即可，不处理也不影响后续帧语义。被认证/Origin 拒绝的连接不经 hello（拒绝发生在 accept 之前）。

### 四种部署姿态

1. **单机自用（默认，推荐）**：两个 listener 都绑回环，token 与 TLS 都不需要；本机客户端连
   `ws://127.0.0.1:9201/...`。
2. **对外只读订阅**：`WS_HOST=0.0.0.0` + `WS_AUTH_TOKEN`（用户级 `~/.heagent/setting.md`）——客户端必须
   带 `Authorization: Bearer <token>`；缺 token **拒绝启动**（fail-closed）。
3. **对外且加密（生产形态）**：在姿态 2 基础上配 `WS_TLS_CERT_FILE` / `WS_TLS_KEY_FILE`（PEM，二者必须同时给），
   listener 走 `wss://`。材料用 `heagent tls init` + `heagent tls issue` 生成（默认 `.heagent/tls/`），
   客户端**不导证书**：只 pin 服务端身份密钥的 SPKI-SHA256（`heagent tls fingerprint` 打印，
   重签叶证书不改 pin，`heagent tls rotate-key` 是唯一改 pin 的动作）。不配 TLS 时启动会打
   `event=plaintext_external` 告警（明文运行可见）。
4. **内网调试入口（明文 + 免 token，Epic 72）**：`WS_HOST=<本机私有 IPv4>` + **`WS_LAN_NO_AUTH=true`**——
   同一局域网内直接 `ws://<私有 IPv4>:9201/...`，客户端不必带 token、也不必导证书。这是**显式放宽**：
   只接受私有地址字面量（`0.0.0.0` / 公网地址 / 主机名一律拒绝启动），且同网段任何设备都能驱使代理。
   该形态与第二步（`wss://` + token）**互斥**：`WS_LAN_NO_AUTH=true` 与 `WS_TLS_*` 同开会直接拒绝启动，
   需要认证就回到姿态 2/3。

```dotenv
# 姿态 4 示例：内网调试入口（明文、无 token）；宿主回环不再监听 9201
WS_HOST=192.168.2.226
WS_PORT=9201
WS_LAN_NO_AUTH=true
WS_MAX_CONNECTIONS=16
```

**配置约束**（不满足即拒绝启动，fail-loud）：

- **CLI 旁路 `/api/cli/ws` 只挂在回环（`local`）listener 上**：`lan` / `external` 绑定不注册该路由（终端事件
  可能含文件内容）。若 `WS_HOST` 非回环且打开了 `WS_CLI_BYPASS_ENABLED`，旁路会被**跳过**并打
  `ws event=cli_bypass_skipped reason=non_loopback_listener` 告警。
- **cron 结果通知流 `/api/notifications/ws` 随 listener 注册**（Epic 58 D2）：`local` / `lan` / `external`
  都有。该端点只在 `CRON_PUSH_ENABLED=true` 时存在（默认关 ⇒ 路由不注册，客户端拿裸 403）；在 `lan` 上
  它意味着宿主 cron 的 LLM 输出对同网段可见（启动 WARNING 已写明）。
- `WS_LAN_NO_AUTH=true` 的三条准入：绑**私有地址字面量**、不得与 `WS_LOCAL_AUTH_ENABLED` 同开、
  绑回环时无意义（拒绝启动并说明改法）；此外**不得与 `WS_TLS_*` 同开**（`wss` + 免 token 拒绝启动）。
- `WS_TLS_CERT_FILE` / `WS_TLS_KEY_FILE` **成对**给或都不给（只给一半拒绝启动）；两份材料读得出时还要求
  它们真的是同一对（`heagent tls verify` 可查），否则每次握手都失败。

```dotenv
# 姿态 2/3 示例：单个对外 listener（不带 TLS 时明文，启动告警）
WS_HOST=0.0.0.0
WS_PORT=9201
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

- HTTP 入口（9101）**无认证、无 TLS**，回环绑定不等于可信——**不要**把它绑到非回环地址后直接暴露公网，
  也不要在它前面套反向代理（`forwarded-*` 头会被直接拒绝，反向代理部署不在支持范围）。
- WS 对外模式的 token 认证**不是绝对边界**：token 会泄露、明文可被中间人观察；限速只挡同一来源的
  暴力尝试。需要更强的隔离就在前面加 TLS，并把整个进程放进容器 / VM。内网免认证档（姿态 4）更弱一层：
  没有 token 这一道门，同网段任何设备都能驱使代理（仍是单用户语义：能提交 run 就能让 Agent 执行
  `shell`），只能靠网络侧兜底（不映射公网、不在不可信网络长期监听）。
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
git tag v<X.Y.Z>
git push origin v<X.Y.Z>
```

`v<X.Y.Z>` 必须与 `pyproject.toml` 和 `src/heagent/__init__.py` 的版本一致；发布 = 两处真源同步 bump + CHANGELOG 的 `Unreleased` 内容落成版本节（`tests/test_release_workflow_contract.py` 钉死）。当前状态：`0.10.0` 已于 2026-11-18 发布，`Unreleased` 已积累 Epic 72/73（含破坏性变更，按 0.x「minor 即破坏性变更」口径下版为 `0.11.0`）。Docker Hub 推送还依赖 CI secrets `DOCKERHUB_USERNAME` 与 `DOCKERHUB_TOKEN`，未配置时该步骤不可用。

CI release job 自动：
1. `twine check` → PyPI（Trusted Publisher OIDC）
2. `docker buildx` → GHCR + Docker Hub（multi-arch: amd64 + arm64）
