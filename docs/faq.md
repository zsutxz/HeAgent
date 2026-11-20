# 常见问题（FAQ）

本页面向**已经动手、卡在某一处**的使用者：每条以问句开头，答案首句给结论，随后是可直接
执行的命令或可粘贴的配置片段。机制与设计动机不在本页展开——需要原理时见
[架构参考](framework.md)、[沙箱机制](sandbox.md)。

分三栏：[配置](#一配置) · [使用](#二使用) · [故障排查](#三故障排查)。

## 一、配置

### 至少要配置什么才能跑起来？

一个 Provider 凭据。其余全部有默认值。

```bash
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
```

```dotenv
DEEPSEEK_API_KEY=sk-...
```

凭据条目名（`/provider` 与 `ROUTING_POOLS` 都按这个名字）：`deepseek` / `claude`（Anthropic）/
`openai`（Responses API）/ `kimi` / `glm` / `ollama`（本地，无需 key）。构建顺序即上述顺序，
多条目时**先插入者赢**（可用 `ACTIVE_PROVIDER` 覆盖默认项）。一个都没配时启动会直接报错退出：

```text
Error: No API key configured. Set DEEPSEEK_API_KEY, KIMI_API_KEY, GLM_API_KEY,
OPENAI_RESPONSES_API_KEY or ANTHROPIC_API_KEY in environment, or enable the local
Ollama entry with OLLAMA_ENABLED=true.
```

### 不想手动写配置文件，有向导吗？

```bash
heagent init --interactive
```

- 逐项问常用配置（**45 项**常用键，按「凭据 → 模型与预算 → 路由池 → 上下文 → 记忆与技能 → MCP →
  HTTP/WS 入口 → 日志与事件 → 沙箱」的面顺序全覆盖），每项给一句说明 + 推荐值（推荐值就是
  `Settings` 字段默认，不另编一份）；
  凭证类输入隐藏回显。
- 写完先校验：逐键往返读回 → `Settings` 构造 → 结构体检（等价 `heagent doctor` 的 `.env` 诊断），
  校验不过就不写盘，并给「描述 + Try + Docs」形态的修复建议。
- **非 tty 调用会直接失败**（退出码 1）而不是把默认值静默写盘——CI / 管道里请改用环境变量或直接编辑文件。

### 配置文件有哪几层，谁覆盖谁？

四层，优先级从高到低：

1. 系统环境变量；
2. 项目 `.env`（当前工作目录）；
3. 用户级 `~/.heagent/setting.md`（全机默认值，`heagent init` 生成）；
4. 字段默认值（`src/heagent/config/catalog/`）。

```bash
heagent init            # 创建 ~/.heagent/setting.md 模板
heagent init --project  # 额外创建项目 .heagent/CONTEXT.md 模板
```

- `setting.md` 用 `KEY: value`（冒号 + 空格），**不要**在值后面写 `#` 注释——会被算进值。
- 旧的 `~/.heagent/.env` 会在 `heagent init` 时自动迁移为 `setting.md` 并重命名。
- 项目上下文文件优先级：`.heagent/CONTEXT.md` > `AGENTS.md` > `CLAUDE.md`。

### 怎么用本地 Ollama？

显式 opt-in，且必须写模型名。

```dotenv
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen3:8b
# OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
```

- `OLLAMA_ENABLED=true` 而 `OLLAMA_MODEL` 为空会启动即退出（报错里带列模型命令
  `curl http://127.0.0.1:11434/api/tags`）。
- 本地窗口通常远小于 `MAX_CONTEXT_TOKENS` 默认的 512000，务必按实际 `num_ctx` 下调，否则
  压缩阈值永不触发、先撞 API 400。

### 怎么切换 Provider？

交互模式用 `/provider`；启动默认条目由 `ACTIVE_PROVIDER` 决定。

```bash
heagent              # 交互模式，输入 /provider 选择
```

```dotenv
ACTIVE_PROVIDER=deepseek
```

条目构建顺序（也是多条目自动回退顺序）：`deepseek → claude → openai → kimi → glm → ollama`。

### 启动时问我「选哪个 Provider」，编号 1 是哪来的？

编号是池内顺序的 1-based 序号，默认项 = `ACTIVE_PROVIDER` 所在位置，并标 `<- default`。

```dotenv
ACTIVE_PROVIDER=deepseek   # 默认项就由这一键决定，改后需重启进程
```

- 回车即接受默认项；池里只有 1 个条目或 stdin 不是 tty 时整段提示被跳过。
- 没有 `--provider` 这类启动参数，切换只走交互模式的 `/provider`。

### `--model` 和 `/model` 有什么区别？

`--model` 定向覆盖这一次运行用的模型；`/model` 是**路由池档位**命令（参数 = 池内名或 `auto`）。

```bash
heagent run --model deepseek-v4-pro "写一个二分查找"
```

```text
> /model            # 查看当前档位与最近一次路由决策
> /model pro        # 钉在池内的 pro 档
> /model auto       # 交回启发式路由
```

已启用路由池时优先用 `/model`——`--model` 只改模型名，不改路由结构。

### 怎么配路由池（fast / mid / pro）？

用 `ROUTING_POOLS` 一个 JSON 声明，键 = 已配好凭据的条目名。

```dotenv
# 单档位池（fast + pro）：
ROUTING_POOLS={"glm":{"tiers":{"fast":"glm-5.3-flash","pro":"glm-5.3"},"keywords":{"pro":"分析,证明"}}}
# 三档位池（显式 roles）：整行替换上面那行，不要同时写两行同名键
# ROUTING_POOLS={"gpt":{"tiers":{"terra":"gpt-5.6-terra","luna":"gpt-5.6-luna","sol":"gpt-5.6-sol"},"roles":{"fast":"terra","mid":"luna","pro":"sol"},"default":"terra"}}
```

- `tiers` 必填且有序，池内名即 `/model` 接受的名字；`roles` 缺省时按名字推断（首档 = fast、
  末档 = pro）。
- 池声明了但无凭据 ⇒ 告警并跳过该池（不会静默降级成单模型）。
- 只有 `RATE_LIMITED` / `TRANSIENT` 会触发池内换档；换档会静默改掉实际模型，想固定就 `/model <池内名>`。
- 报 `404 Model "X" is not supported by any configured account in this group` 时，先看这个串：
  它说的是**该档位模型未在当前账号组开通**（`ROUTING_POOLS` 配置面问题），不是路由解析 bug，
  也不是认证/token 问题——例如 `claude-sonnet-5-5` 因限流回退到 `claude-haiku-5-5` 后撞到未开通。

### 上下文窗口怎么调？

改 `MAX_CONTEXT_TOKENS`，它必须 ≤ 所用模型的真实窗口。

```dotenv
MAX_CONTEXT_TOKENS=512000
COMPRESSION_THRESHOLD=0.8     # compressor 策略触发点（窗口占比）
CONTEXT_STRATEGY=compressor   # compressor=原地摘要；reset=清窗后 resume
WINDOW_RESET_THRESHOLD=0.6    # 仅 reset 策略生效
TOKENIZER=auto                # auto | estimate | tiktoken
```

阈值按「上报 token / 窗口」比值判断；窗口设得比真实窗口大，阈值就永不触发，先撞上游 400。

### shell 跑在什么沙箱里，怎么换后端？

四档后端：`auto` / `passthrough` / `firejail` / `winjob` / `docker`。

```dotenv
SANDBOX_BACKEND=auto              # 探测到 firejail 用 firejail，否则 passthrough（零隔离）
SANDBOX_MODE=workspace-write      # read-only | workspace-write | danger-full-access
SANDBOX_NETWORK=false             # 禁止子进程出站
```

```bash
heagent run --sandbox docker "…"
```

- `auto` **只**探 firejail，Windows 上会落 `passthrough`；容器档必须显式写 `docker`。
- 三层**都不是**真正的安全边界：`SafetyGuard` / `PolicyEngine` / sandbox 后端各自都可被绕过。
  真正能兜底的只有 OS 级隔离（`SANDBOX_BACKEND=docker`，默认未启用；启用后也非绝对边界）。
  对外（非回环监听）能提交 run 时强烈建议 `--sandbox docker`。详见[沙箱机制](sandbox.md)。

### 怎么关掉网页入口 / WS 监听？

`HTTP_ENABLED` / `WS_ENABLED` 是持久开关，`--no-http` / `--no-ws` 是单次覆盖。

```bash
heagent run --no-http "…"            # 只关本次 HTTP
heagent run --no-http --no-ws "…"    # 两个都关
heagent http-server --no-ws          # 只起 HTTP
```

```dotenv
HTTP_ENABLED=false
WS_ENABLED=false    # 两个都 false = 零监听，交互模式仍可用
```

注意默认 CLI 的选项挂在 `run` 子命令上：`heagent --no-http` 会被 click 报 `No such option`。

### WS 对外模式怎么配 token 与 TLS？

把 WS listener 绑到非回环地址即进入对外模式，此时**必须**先在用户级 `setting.md` 配 token。

```yaml
# ~/.heagent/setting.md
WS_AUTH_TOKEN: <一长串随机字符>
```

WS 只有**一条** listener（Epic 72 起第二 listener 退役），身份按绑定地址 + `WS_LAN_NO_AUTH` 三档切：

| 档 | 绑定 | 认证 | 典型用法 |
|---|---|---|---|
| `local` | 回环（默认） | 无 | 单机自用；终端旁路可用 |
| `lan` | 私有 IPv4 + `WS_LAN_NO_AUTH=true` | **无** | 内网调试入口（明文直连，同网段可驱使代理） |
| `external` | 其余非回环 | 强制 Bearer | 对外 / 跨网，token 只认 `~/.heagent/setting.md` |

```dotenv
# 内网明文直连（第一步形态）：客户端不必带 token / 证书
WS_HOST=192.168.2.226
WS_LAN_NO_AUTH=true
```

```dotenv
# 需要认证（第二步形态）：同一地址，不开免认证开关，配 token + TLS
WS_HOST=192.168.2.226
WS_TLS_CERT_FILE=.heagent/tls/cert.pem
WS_TLS_KEY_FILE=.heagent/tls/key.pem    # cert + key 成对配齐才走 wss
```

- `WS_LAN_NO_AUTH=true` 只接受**私有地址字面量**：`0.0.0.0` / 公网地址 / 主机名一律拒绝启动。
- token **只认** `~/.heagent/setting.md`；项目 `.env` 写 `WS_AUTH_TOKEN` 不生效并告警。
- 非回环且未开免认证 ⇒ 缺 token 拒绝启动（fail-closed），不会降级成「无认证对外」。
- 端点可见性：CLI 旁路 `/api/cli/ws` **只挂回环** listener；通知流 `/api/notifications/ws`
  在 `lan` / `external` 上同样可见，但只在 `CRON_PUSH_ENABLED=true` 建起中枢时才存在。

## 二、使用

### 单次执行、交互模式、显式子命令有什么区别？

```bash
heagent "用一句话解释 asyncio"     # 单次执行
heagent                            # 交互模式（REPL）
heagent run --system "你是 Python 专家" "写一个二分查找"   # 显式子命令 + 选项
```

- 默认 CLI 会在同一进程内起本机网页入口（`127.0.0.1:9101`）与 WS listener（`127.0.0.1:9201`）。
  这是**代码默认**（`HTTP_ENABLED` / `WS_ENABLED` 默认 true）；项目 `.env` 把它们置 false 就只剩终端。
- 其余子命令：`heagent replay FILE`（回放 JSONL）、`heagent init`（含 `--interactive` 向导）、
  `heagent doctor`（配置诊断）、`heagent cron status`（定时任务状态）、`heagent gui`、`heagent http-server`。
- `heagent gui` 需要 `pip install -e ".[gui]"`；网页入口需要 `pip install "heagent[http]"`。

### 交互模式有哪些斜杠命令？

```text
/provider    切换 LLM provider
/model       路由状态 / 强制定档（<池内名>|auto）
/help        列出全部斜杠命令（含自定义命令）
/help <cmd>  单个命令的语法 / 参数 / 示例（未知命令会给最接近的建议）
/clear       清空当前会话上下文
/compact     摘要并压缩当前会话
/mcp-prompt  调度 MCP prompt
/deferred    列出 deferred-work 台账
/goal        目标驱动开发（new/next/run/status/pause/resume/auto/reset/doctor）
/loop        目标驱动开发 v7（8 步工作流；来自项目自定义命令 `.heagent/commands/loop.md`）
```

未注册的名字不会被拦截，会**当作普通 prompt** 交给模型（多花一次调用）；旧名 `/route` 已不注册。
`.heagent/commands/*.md` 里的自定义命令会出现在 `/help` 列表里，`custom: true` 的那几条即来自该目录。

### 命令跑了很久，终端停在 `[calling …]` 不动，正常吗？

- 超过 **3 秒**的工具执行会出现原地刷新的耗时行（如 `[calling shell → pytest 3.5s]`）；
  3 秒以内**刻意不显示**，避免正常快调用把终端刷满。
- 超过 **10 MB** 的文件读写在同一行追加「已处理 / 总量 / 百分比 / 约剩 Ns」。
- 管道或重定向（非 tty）降级成一行收尾摘要；`ANNOUNCE_PROGRESS=false` 则完全静默。

### 配置看起来没错但起不来，有自检工具吗？

有：`heagent doctor`（只读，不调模型、不写文件）。

```bash
heagent doctor            # 人读：每条 finding 一行 severity/code + 一行 fix
heagent doctor --json     # 机器读：JSON 数组，每项含 code/severity/message/fix
```

共 **30 个诊断码**（11 组检查）：无凭据、`ACTIVE_PROVIDER` 指向不存在或无凭据的条目、
`OLLAMA_ENABLED` 缺模型、`MAX_OUTPUT_TOKENS` 不小于 `MAX_CONTEXT_TOKENS`、`ROUTING_POOLS`
非法 JSON 或池条目无凭据、`.env` 缺失 / BOM / 重复键 / 空值键 / 未知键、非回环 listener
缺 token、`WS_LOCAL_AUTH_ENABLED` 缺 token、`WS_LAN_NO_AUTH` 组合非法（非私有地址 / 与
`WS_LOCAL_AUTH_ENABLED` 同开 / 绑回环）、退役的 `WS_EXTERNAL_*` 残留键（INFO）、
TLS 半配、端口已被监听、`APPROVAL_TOOLS` 含未注册工具、`SAFETY_BLOCKED_TOOLS` 拦了 `shell`、
docker 后端探不到 daemon、技能双根同名冲突、WS TLS 身份四项（pin 短指纹 INFO、到期余量、
`WS_HOST` 是否在 SAN、材料读不出来）。

退出码：有 `error` 级 finding 时为 1，否则 0——可以直接进 CI 或启动脚本。

### 怎么加自定义斜杠命令？

在 `.heagent/commands/*.md`（项目级）或 `~/.heagent/commands/*.md`（用户级）放一个带 frontmatter 的
Markdown，正文就是触发后提交的 prompt 模板。

```markdown
---
name: review
description: 以审查者身份过一遍改动
---
请以资深审查者身份阅读 git diff，只报告问题，不修改代码。
```

项目级覆盖用户级同名命令。

### 技能和角色分别放在哪？

技能是双根、**全局优先**；角色与命令是「本地覆盖全局」。

| 内容 | 项目级 | 用户级 | 优先级 |
| --- | --- | --- | --- |
| 技能包 | `.heagent/skills/<name>/SKILL.md` | `~/.heagent/skills/<name>/SKILL.md` | 全局优先（同名冲突告警） |
| 自定义命令 | `.heagent/commands/*.md` | `~/.heagent/commands/*.md` | 项目优先 |
| 角色 | `.heagent/agents/*.md` | `~/.heagent/agents/*.md` | 项目优先 |
| 人格 | `.heagent/SOUL.md` | `~/.heagent/SOUL.md` | 项目优先 |

```bash
ls .heagent/skills/ ~/.heagent/skills/    # 看两处各有什么（同名全局生效）
ls .heagent/commands/ ~/.heagent/agents/  # 自定义命令与角色
```

技能包必须有带 frontmatter 的 `SKILL.md`（`name` / `description`），否则不会被目录收录。

### 怎么续跑上次会话？

```bash
heagent run --continue "接着上面的说"        # 最近一次会话
heagent run --resume <session-id> "…"       # 指定会话
```

会话文件在 `.heagent/sessions/`，受 `SESSION_RETENTION_DAYS`（默认 30 天）清理。

### `/goal` 怎么用，产物在哪？

```text
/goal <目标描述>      创建目标并启动首个步骤
/goal next            推进一步或一条 Story
/goal run             连续推进直到 checkpoint 或阻塞
/goal status          查看状态和产物
/goal pause           保存并暂停
/goal resume [回复]   提交回复并继续
/goal auto [cron]     注册定时推进；off 注销
```

产物在 `_he-output/goals/<goal-id>/`。工作流契约见 `.heagent/skills/he-goal/workflow.md`，
导读见 [`framework.md` §4.13](framework.md#413-goal-驱动工作流-goal)。

### `/loop` 怎么用，产物在哪？

`/loop` 是项目级自定义命令（`.heagent/commands/loop.md`），执行契约是同包的
`.heagent/skills/loop/SKILL.md` ＋ `workflow.md`（两者都要读）。8 步：市场调研 → 发散构思 →
需求分析 → 产品范围 → 架构设计 → 故事细化 → 逐故事实现 → 系统集成测试；Step 04 与 Step 06 是审批门。

- 触发：`/loop <大目标描述>`；`reset` 只删 `_he-output/works/current` 指针，不删目标目录。
- 运行状态：`_he-output/works/<goal-id>/progress.md` ＋ 指针 `_he-output/works/current`；每步用一个**全新** `task_delegate` 子会话，无 Python 状态机。
- 规划与 story 状态：BMAD v7 票树 `_bmad-output/initiative-<slug>/tickets/`（`tickets.py mark` 是唯一合法写路径）；不再产出 `epics.md`，也不写 `sprint-status.yaml`。
- 与 `/goal` 的关系：两套工作流**互不读写**对方的产物目录（`/goal` 在 `_he-output/goals/`，`/loop` 在 `_he-output/works/`）。

### 定时任务现在是什么状态？

```bash
heagent cron status          # 人读：每 job 一行状态 + 最后/下次执行 + 失败原因
heagent cron status --json   # 机器读
```

- 状态取自 `jobs.json` 的执行记录：`never` / `running` / `success` / `failed`，卡住的 `running` 会按开始时间判成 `interrupted`。
- **时间口径要注意**：`last_run` 落盘是 UTC，而 cron 表达式按**宿主本地时**匹配——输出里两列分别标注，别混读。
- 失败原因只留「异常类型: 首行消息」（截断），完整栈仍在 `logs/heagent-*.log`。

### 怎么接入 MCP server？

在项目根放 `.mcp.json`，默认启用。

```dotenv
MCP_ENABLED=true
MCP_CONFIG_PATH=.mcp.json
```

- 密钥写在环境变量里，不写进 `.mcp.json`。
- 网络入口（HTTP 网页/WS）**不连接** MCP server，也不安装 stdin 审批处理器——需要审批的工具在
  网络入口下按 fail-safe 语义阻断。

### 怎么把 HeAgent 当库嵌进自己的程序？

```python
import asyncio

from heagent import Agent, OpenAIProvider


async def main() -> None:
    agent = Agent(OpenAIProvider(api_key="sk-...", model="gpt-4o"))
    print(await agent.run("你好"))


asyncio.run(main())
```

库是**单进程异步**的：直接 `asyncio.run()` 桥接，不要在同步函数里阻塞等待。

### 网页控制台怎么开，端口在哪？

```bash
heagent                    # 交互模式下网页入口与终端并存，地址打印到 stderr
heagent http-server        # 只起网页服务
heagent http-server --port 9100 --ws-port 9201
```

- 默认 HTTP `127.0.0.1:9101`、WS `127.0.0.1:9201`（单 listener；非回环入口走 `lan` / `external`）。
- 端口被占时会在 `preferred … preferred+9` 内顺延，以日志 `ws event=started address=…` 为准。
- 网页控制台的配置写入通道默认**关**（`HTTP_CONSOLE_WRITE_ENABLED=false`）：开启后任何能连上该端口
  的人都能改项目 `.env`，属显式危险操作。

补充：控制台与 CLI 同进程时，`GET /api/tasks` 能读到后台任务（如上下文压缩）的实时进度；
该路由只在入口层注入进度来源时注册，跨进程不共享（没有 IPC）。

## 三、故障排查

### `heagent: command not found` / 模块找不到

包没装进当前解释器。

```bash
pip install -e ".[dev]"     # 开发安装
python -m heagent "…"       # 与 heagent 等价的入口，用来判断是 PATH 还是安装问题
```

### 启动直接报配置缺失并退出（不是 WARNING）

启动期会做一次**同步、纯本地**的必需配置校验（<100ms，不联网、不探测端口），只判「不满足就一定起不来」的项，共 **6 项**：

1. `provider_credentials` —— 一个凭据都没有（`OLLAMA_ENABLED=true` 时改判 `OLLAMA_MODEL` 是否为空）
2. `ollama_model` —— 启用了 Ollama 但模型名为空
3. `ws_auth_token` —— WS 启用且会落进非回环强制认证模式，但 `~/.heagent/setting.md` 里没有 `WS_AUTH_TOKEN`
4. `ws_lan_no_auth` —— `WS_LAN_NO_AUTH=true` 但绑的不是私有地址字面量 / 与 `WS_LOCAL_AUTH_ENABLED` 同开 / 绑回环
5. `ws_tls_pair` —— TLS 只配了一半
6. `sandbox_docker` —— `SANDBOX_BACKEND=docker` 但镜像名为空 / digest 不是 repo digest


- 失败即**退出**（fail-loud），不做降级——降级会让错误推迟到第一次调用才暴露。
- 与 `heagent doctor` 分工：doctor 是全量只读体检（含端口、docker daemon、技能双根冲突），启动校验只覆盖必需项。
- 找不到具体哪个键时先跑 `heagent doctor`；报错块里的 `Try these commands:` 会给可直接执行的命令。
- 注意 `--no-ws` / `--no-http` **不能**绕过这道校验：校验作用于 `Settings`，早于本次进程的命令行覆盖生效。

### 启动报 `No API key configured`

一个凭据都没配。检查顺序：`.env` 是否在当前工作目录 → 变量名是否拼错 → 是否只在 `setting.md`
写了但被项目 `.env` 的空值覆盖。

```bash
grep -n "API_KEY" .env ~/.heagent/setting.md
```

### 端口被占用 / 浏览器连不上

先看启动日志里 listener 实际绑到哪个端口，再探活。

```bash
# 日志里找这两行
grep -n "ws event=started\|http event=started" logs/heagent-*.log
```

- 端口顺延会打印 `Port 9101 was in use, using port 9102 instead` 一类行。
- 完全没有 `http event=started` ⇒ 不是冲突，而是 `HTTP_ENABLED=false`（或本次 `--no-http`）。
- 只绑 `127.0.0.1` 时，从别的机器连不上属预期。

### 容器里 `git` 报 `dubious ownership`

容器内 UID 与挂载文件属主不一致，不是仓库损坏。

```bash
git -c safe.directory=/workspace status
# 或一次性配置
git config --global --add safe.directory /workspace
```

### 工具报 `attempted to access a path outside workspace: /workspace/...`

路径围栏只认**宿主形态**或**工作区相对**路径，容器内的 `/workspace/...` 不在其中。

```text
Tool 'content_search' attempted to access a path outside workspace: /workspace/src
```

改用相对路径（`src/heagent/web`）或宿主形态路径即可；`shell` 不走这层围栏，所以 `cd /workspace && ls` 正常。
这不是「目录不存在」，不要把两者混为一谈。

### WS 连上就被关（1008 / 403）

按绑定模式分两种情形：

- **对外模式**（或曾把 `WS_HOST` 设成 `0.0.0.0` 后没改回来）：必须带 token，且 token 只认
  `~/.heagent/setting.md` 的 `WS_AUTH_TOKEN`——项目 `.env` 里写同名的键不生效。
- **本地模式**（回环绑定，默认）：正常不需要 token；若被要求认证，说明开了
  `WS_LOCAL_AUTH_ENABLED=true`（此时连旁路 `/api/cli/ws` 也要带 token）。

```bash
grep -n "WS_HOST\|WS_LOCAL_AUTH" .env
grep -n "ws event=started" logs/heagent-*.log    # 看 listener=local 还是 external
```

裸 403 还有一种**非认证**成因：`/api/notifications/ws` 只在 `CRON_PUSH_ENABLED=true` 建起中枢时
注册，默认关 ⇒ 该路由不存在，连上去只会拿 403。先确认这个开关再怀疑 token。

日志里成片的 `ws event=auth_rejected reason=throttled` 是**限速**（同源失败次数超限后不再比对
token，仍回同一个 1008），先查客户端 token 来源与重连风暴。

### 把 `WS_HOST` 设成 `0.0.0.0` 后启动失败或终端旁路没了

`0.0.0.0` 不算回环也不算私有地址字面量 ⇒ 两条路都不通：不开 `WS_LAN_NO_AUTH` 会落进
`external` 档（强制 Bearer、缺 token 直接拒绝启动）；开了则因为「通配不是私有地址」拒绝启动。
两种情况 CLI 旁路 `/api/cli/ws` 都不会挂。

```dotenv
WS_HOST=127.0.0.1        # 保住终端旁路：listener 回环（本地模式）
# 确实要局域网直连就绑具体网卡地址（不要 0.0.0.0）
# WS_HOST=192.168.2.226
# WS_LAN_NO_AUTH=true
```

```bash
grep -n "cli_bypass_skipped" logs/heagent-*.log
```

见到 `ws event=cli_bypass_skipped reason=non_loopback_listener listener=lan host=192.168.2.226`
即这条，不是故障——旁路内容包含终端里尚未提交的输入，刻意不外溢。

### docker 沙箱不起作用 / 启动时降级

后端不可用时会**显性降级**为宿主执行并每次 WARNING，不会静默「假装在容器里」。

```bash
docker ps                  # daemon 可用吗
grep -n "SANDBOX_BACKEND\|sandbox" logs/heagent-*.log | head
```

- `SANDBOX_BACKEND=auto` **不会**自动选 docker，必须显式写 `docker`。
- HeAgent 整进程已在容器内时，`auto` 同样只能 `passthrough`——隔离来自外层容器。

### 日志里怎么确认某次调用到底用了哪个模型？

只看 `provider_call_completed` 的 `details['model']`；路由决策与配置都不等于实际调用。

```bash
grep -n "provider_call_completed" logs/heagent-*.log | tail -5
grep -n "Routing (.*) →" logs/heagent-*.log | tail -5
```

- 状态行与 `/model` 显示的模型名取自**最近一次路由决策**，池内换档时同一会话会出现不同模型名（属预期）。
- 配置了某个 provider 不等于发生过调用；只有 `provider_call_completed` 能证明。
- 注意：用 `content_search` 在日志里查这些字符串会命中的是**检索命令自身**的回显，别当成调用记录。

### 上下文什么时候被压缩 / 重置？

按「上报 token / `MAX_CONTEXT_TOKENS`」的比值：compressor 在 0.8 触发，reset 策略在 0.6 触发。

```bash
grep -n "context_compressed" logs/heagent-*.log | tail
```

- 触发后事件里带 `before` / `after` token 数。
- 阈值一直不触发，先查 `MAX_CONTEXT_TOKENS` 是否被设得比模型真实窗口大。

### 技能列表显示 stale，是不是该删？

不一定。stale 的判据只有「`record_usage` 计数 + 最后使用时间」，与技能是否仍相关无关。

- 外部装入的技能包（如 `bmad-*`）不经过 `record_usage`，恒显示 `used 0x, last: never`；
- 自建但一直没被真正加载过的技能同样显示 `used 0x`。

只看 `SKILL.md` 是否已被当前实现推翻——被推翻才归档，否则不动。核对办法是先看用量计数与来源：

```bash
grep -n "usage_count\|last_used" .heagent/skills/*/meta.yaml | head
ls .heagent/skills/ ~/.heagent/skills/    # 成批出现的外部包（如 bmad-*）一律不动
```
