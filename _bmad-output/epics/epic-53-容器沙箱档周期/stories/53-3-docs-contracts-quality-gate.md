# Story 53-3 · 文档、契约与质量门

状态：**done**（2026-10-21 全量门 3740 绿，文档与契约同步完成，另闭合两笔**既有**契约失守
（台账计数 + 端口顺延用例）。2026-10-24 用户 walkthrough 验收通过；
docker.io 直连 digest 验证残余转 **D53-3**）。

## 交付物

- **判据 11（53-2 挂账闭合）**：`tests/test_sandbox_docker.py::test_sandbox_decision_full_chain_docker`
  ——`Settings → resolver → DockerRunner → SandboxDecision → executor 注入 → run 上下文元数据`
  全链替身判据：可用链（effective docker / 双隔离 True / 元数据同源）、bridge 档（网络隔离翻转 False）、
  不可用链（诚实降级 passthrough / 双隔离 False）。
- **`docs/frame.md` 同步（8 处）**：§4.4 新增 DockerRunner 段（形状 / 镜像 pin / 网络档 D2 /
  探测降级 / kill 清理 / 非绝对边界）；FR-2 分级行（container 档预留 → DockerRunner 落地，
  审批降级仍未接入=期二 D53-2）；配置表 3 行（`sandbox_backend` 增 docker 选档、新增
  `sandbox_docker_image`、`sandbox_network` 双后端语义）；已知缺口表 3 行（MCP/engine 边界行、
  Z-D24 行 2026-10-21 注、分级行更名「沙箱后端分级」）；目录树 sandbox/ 清单补 docker.py。
- **AGENTS.md 同步（3 处）**：裸跑声明补「容器档已落地、`--sandbox docker` 显式启用、默认链路
  未启用」；MCP 风险行补「Docker 后端不覆盖 MCP stdio——期二 D53-1」；核心立场行补兜底实施项口径。
- **「须 OS 级沙箱兜底」表述逐行复核**：立场行（4.6 dream / MCP 围栏 / approval / path_safety /
  env 豁免 / SandboxSession / HTTP 入口 / GUI 拉起面等）**维持原文不改**——要求仍真、事实未变，
  不扩大宣称；修订只落在事实变化处（上列 8+3 处）。
- **台账契约对齐（全量门逮住的既有失守，非 53-3 原计划）**：
  - `0e8a330`（2026-10-20）在总账活动区登记 A34–A36（挂起待裁定/待触发）后，四份文档仍宣称
    「活动 0 条」、契约测试仍强制恒零——政策已变、契约滞后。`tests/test_deferred_id_registry.py`
    改造：恒零判据 → **计数真实性**（各声明点声明值 == 活动区实际行数；actual≠0 时禁 0 声明）；
    活动区表形判据（4 列 + 表头计数诚实）；epic 台账计数 10 → 11。
  - epic-53 `deferred-work.md` 补 状态总览 表（D53-1/D53-2 挂起待触发）——44c5363 立项时缺表。
  - 四处计数声明刷新为 3 条：`consolidated-overview.md` `§17.4-A`（标题 + 正文）、
    `_bmad-output/README.md`、`retrospective-all-cycles.md` `§5.1`（标题 + 叙事补 2026-10-20 段）、
    `implementation-artifacts/README.md`。
- **端口顺延契约测试对齐（既有失守之二，a545613 漏改）**：
  `test_cli_http_lifecycle.py::test_bind_failure_fails_the_command_without_entering_the_cli`
  以 **env 端口**期待 fail-loud——那是 2026-10-15 端口顺延契约修订**之前**的语义。现行契约：
  env/自动端口被占时**顺延**继续服务；fail-loud 保留给显式 `--port`
  （`test_cli_http.py::test_explicit_port_is_never_silently_replaced` 钉住，默认 CLI 入口本无
  `--port`）。用例改写为 `test_env_port_conflict_drifts_instead_of_failing`：占用端口 → exit 0、
  run 正常完成、实际监听端口 > 被占端口。HEAD 干净态复测确认失败先于本 story 存在。
- **skills.py 格式化漂移（chore 单列）**：`tools/builtins/skills.py` 两处换行口径随本机
  ruff 0.16.6 漂移（上次落库 2026-10-13，与本 epic 无关），`ruff format` 机械修正。

## 验收证据（2026-10-21 亲跑）

- 全量 `pytest`（跳过 integration/benchmark）：**3740 passed / 14 skipped / 0 failed**（156.2s，
  本地 Py3.13 不带 cov——cov 组合 bug 见仓库既有记录）。
- 静态：`ruff check src tests` 全绿；`ruff format --check` 326 files 全绿；`mypy src`
  Success: no issues in 168 source files。
- 契约：`tests/test_architecture_contracts.py` 30 passed **零改动**（docker.py 未新增跨包依赖）。
- 判据：`tests/test_sandbox_docker.py` 12/12（判据 11 新增）。

## 审查修复批（2026-10-21，跨 53-1/53-2/53-3 交付物）

story 入 review 后的一轮审查发现**实现层**缺口（原交付在「门全绿」意义上完整，但若干硬化与
诚实性维度未覆盖），逐项修复如下。修复本身新增判据 20–24，故验收证据一并刷新。

### 安全硬化（关 A/B/C 类）

- **容器硬化**（`docker.py`）：`--cap-drop=ALL` + `no-new-privileges` + 非 root `sandbox` 用户
  （`Dockerfile` 同名创建），防 root-in-container。argv 组装仍单处决定，判据 5 同步钉死。
- **kill 兜底**（`_docker_kill`）：kill 后 `inspect .State.Running` 校验；仍活着或状态不确定
  （inspect 自身失败）→ WARNING + `docker rm -f` 兜底。孤儿容器带 workspace 写挂载存活是真实
  暴露面，不能只 debug。兜底也失败只留痕不上抛（清理是兜底动作，不制造二次异常）。
- **workspace 兜底挂载**：FR-1 会话目录优先，缺省回落 resolver 传入的 `workspace_root`
  （firejail `--private` 同型语义）——消除「无挂载、写入随 `--rm` 蒸发还报成功」的静默形态。
- **resolver 可用性闸**：daemon 不可达时 resolver 回 `None`（对齐 winjob），不再构造一个
  「事件/决策报 container 档、执行全裸」的 runner；`run()` 内的 Passthrough 兜底保留为纵深防御。

### 诚实性（关 F 类）

- **`cpu_seconds` 无诚实映射**：`--cpus` 是速率上限而非 CPU 时间上限，硬映射会伪装成已生效。
  改为 resolver 在配置了该值时打 WARNING 明说「NOT enforced」，`frame.md` 配置表同步标注。
- **网络隔离事实源统一**：`CommandRunner` Protocol 增 `isolates_network()`，四后端全实现；
  `SandboxDecision.network_isolation` 与 enforce 告警面都按**实际能力**判定，不再按档位集合
  豁免——「档位够高但网络档错配」（bridge runner + `SANDBOX_NETWORK=False`）不再既无隔离也无提示。

### 资源限额（关 E 类）

- `sandbox_memory_limit_mb` → `--memory`、`sandbox_nproc_limit` → `--pids-limit`（0=关闭，
  默认零旗标 ⇒ 既有 argv 逐字节不变）。触发=容器被杀显性失败。

### 容器侧路径锚（关 D 类）

- `SandboxSession`：docker 后端专用 wrap——宿主路径无法直接 `cd`（挂载点固定 `/workspace`），
  cwd 跟踪改用**原始字符串**（`_extract_cwd_raw`，`Path` 在 Windows 宿主会把 POSIX 路径改写成
  反斜杠）；与宿主侧 `self.cwd` 并行维护，teardown 仍用宿主目录。
- `AgentLoop._bound_container_workdir` + `<shell-workspace>` 块追加容器侧路径锚：模型不知道
  `--private` 式的宿主→容器映射会拿宿主路径写 shell 命令，必然落空。
- `housekeeping.prune_exited_sandbox_containers`：回收崩溃遗留的**已停止** `heagent-*` 容器
  （`--rm` 未兑现的残骸）。只清 exited（running 可能是活命令，不可区分，一律不碰）；
  不依赖保留期，四类保留期全 0 时仍单独跑一次。

### 运行期 digest pin（D4 的运行期落实）

- `Settings.sandbox_docker_digest` + 首 run 前 `docker image inspect` 校验本地 tag 的 repo
  digest，不符显性拒绝——本地 tag 可被 retag 静默换载荷，构建期 pin 管不到这一点。

### 真实 daemon 实证逮住的真 bug（修复批内部，值得单列）

补 integration 用例时**真实链路立刻变红**：`--memory` / `--pids-limit` 被拼接在 `IMAGE`
**之后**，而 `docker run` 只在镜像名之前解析选项——两个旗标因此变成容器内命令的位置参数，
**限额静默失效**（64MiB 上限下分配 512MiB 照常成功）。

- **为什么原判据没逮住**：判据 14 只断言「argv 里存在 `--memory` / `--pids-limit` 及其值」，
  对**位置**无条件——旗标存在但不生效，是典型「测了行为没测意图」的盲区。
- **修复**：限额旗标移到 `IMAGE` 之前（`build_run_argv` 顺序 + 注释钉住原因）。
- **第二道闸**：判据 14 增位置断言（`argv.index("--memory") < argv.index(image)`）——
  位置错了单测即红，不必等真实 daemon。

### 验收证据（2026-10-21 修复后重跑）

- 全量 `pytest`（跳过 integration/benchmark）：**3771 passed / 14 skipped / 0 failed**
  （较修复前 +19 条）。
- 静态：`ruff check` / `ruff format --check`（326 files）/ `mypy src`（168 files）全绿。
- 判据：`tests/test_sandbox_docker.py` **28/28**（判据 12–19 既有 + 本次补 15c/15d/16c/16d，
  判据 14 增位置断言）；容器清扫 5 条 + docker 会话 cwd 2 条 + 容器工作目录锚 4 条。
- **integration 7/7 真实 daemon**（本机 Docker 28.5.2）——新增 3 条实证：
  ①`--pids-limit=8` 下反复 fork 被打断（非零退出，非「旗标在 argv 里」）；
  ②`--memory=64m` 下分配 512MiB 被杀（修复前此条红，是发现 bug 的用例）；
  ③硬化旗标可观测：`id -u`=1000 / `id -un`=`sandbox` / `CapEff: 0000000000000000` /
  `touch /etc/probe` ⇒ Permission denied。
- 覆盖率（修复前后同口径）：`docker.py` 81%→96%，`cli/housekeeping.py` 74%→86%。剩余未覆盖
  为真实进程启动与异常兜底分支（由 `integration` 标记用例覆盖）。

### 本批未做（如实标注）

- **`cpu_seconds` 仍不支持**：无诚实映射故明确不实现（不是遗漏）；若将来需要，须先裁定
  「CPU 时间」在容器语义下的口径。
- **硬化旗标无负向变异验证**：integration 用例只证「当前实现生效」，未做「删旗标后必红」的
  变异体验证（53-1 对判据 1–11 做过 6/6 变异体，本批未重复该强度）。

## 残余（如实标注）

- **docker.io 直连 digest 验证未完成**：`auth.docker.io` 30s 超时不可达（本机网络对 docker.io
  直连断流，与既有网络环境记录一致）。基座 digest 维持 53-2 的镜像源交叉验证口径
  （daocloud 与 docker.io manifest 字节一致）；直连补验挂起，触发条件=出现可用直连通道。
