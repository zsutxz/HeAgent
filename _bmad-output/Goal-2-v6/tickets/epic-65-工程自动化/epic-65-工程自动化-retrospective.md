---
epic: epic-65-工程自动化
date: 2026-11-18
verdict: accepted
criteria: declared
headless: false
---

# Epic 65 Retrospective

> 路径约定：`tickets/story-65.*` 均相对
> `_bmad-output/Goal-2-v6/tickets/epic-65-工程自动化/`；其余路径相对仓库根。
> 本 retro 的实测数字为收口现场取证（2026-11-18，容器内 `.heagent/tmp/py311-venv-linux/bin/python`）。
> **全部改动仍在工作树、未提交**（基线 `ae831fe`）。

## Epic summary

**Epic**：epic-65-工程自动化（R12 / R13；9 story：5 `勘差 + ratchet`、4 新建）

**票态**：9/9 `done`（`tickets.py mark` 逐条置位），无 `dropped`。

```text
tickets.py status _bmad-output/initiative-heagent
→ counts: total 63, done 40, dropped 2, planned 21   （Epic 61–65 全闭合）
```

**前置勘误（v6 归档已授权）**：Epic 4（CI/CD）由「建设」降级为「勘差 + ratchet」——
`.github/workflows/ci.yml`（8 job）+ `codeql.yml` 早已存在；FR12 的「merge 自动发版」验收标准按
Step 04 决策 Q2 作废。本 epic 因此**先勘差、后动工**，9 条 story 中 5 条以「现状已达成 / 口径已收窄」
收口，4 条是真实缺口。

## 勘差结论（逐 entry）

| Entry | 现状实测 | 处置 |
|---|---|---|
| 65.1 质量门禁 | CI 有 8 job，`lint` 跑 ruff check/format + mypy + bandit + 契约快照 + pip-audit + docs build；本地 `quality_gate.py` 7 门**分头**承接 | **新增 ratchet**：`tests/test_ci_gate_parity.py` 把「本地门 → (CI job, 命令片段)」写成显式映射 |
| 65.2 PR 自动测试 | `on: pull_request:` 裸触发（无分支过滤）⇒ test 矩阵 3×4 / coverage / benchmark / goal-smoke / dependency-review 全跑；integration 仅 `workflow_dispatch`（需真实密钥） | **新增 ratchet**：PR 触发面 + 集成仅手动的断言 |
| 65.3 版本号管理 | 两处真源 + 三条契约测试（semver / 单一真源 / tag 一致）已达成；「merge 自动 bump」按 Q2 作废 | 勘差闭合，**不加 bump 脚本**（理由入 plan） |
| 65.4 CHANGELOG | 载体 + 四条守卫已达成；「依 commit 自动生成」已被 2026-11-13 勘误收敛为「载体 + 守卫」 | 勘差闭合，**不引入生成器**（理由入 plan） |
| 65.5 PyPI 发布 | `release` job 已含 build / twine check / OIDC 发布 / 多架构推送 / 审批门 | **补唯一缺口**：`if: failure()` 失败摘要 step |
| 65.6 开发环境 | **无 `.devcontainer/`**；`Dockerfile` 是产物镜像 | **新建** `.devcontainer/{Dockerfile,devcontainer.json}` + 4 条契约测试 |
| 65.7 结构化日志 | 格式串在两处硬编码，无机读格式 | **新建** `pub/log_config.py`（单点）+ `LOG_FORMAT` 设置面 + 装配收口 |
| 65.8 调试模式 | 中间变量插桩存在但无单开关；错误出口永不打 traceback | **新建** `DEBUG_MODE`（日志级别强制 DEBUG + 错误出口追加 traceback） |
| 65.9 性能分析 | 文档只给两条手敲 `cProfile` 命令，无脚本、无热点摘要 | **新建** `scripts/profile_run.py` + 文档改写 |

## 交付与证据

| 面 | 文件 | 判据 |
|---|---|---|
| CI 一致性 | `tests/test_ci_gate_parity.py`（161 行，6 例） | 映射集合相等 + 片段带右侧边界 + PR 触发面 + release 失败摘要 |
| 开发容器 | `.devcontainer/Dockerfile`(29)、`devcontainer.json`(35)、`tests/test_devcontainer_contract.py`(94，4 例) | dockerfile 存在 / extras ⊇ dev·gui·http + pre-commit / forwardPorts == Settings 三端口 / 基础镜像 X.Y == `requires-python` 下界 |
| 结构化日志 | `src/heagent/pub/log_config.py`(111)、`tests/test_structured_logging.py`(181，10 例) | json 单行可解析 + 四键 + 时区偏移 + context + exc_info + 退化 + 非法值失败 + 装配真写出 |
| 调试模式 | `cli/errors.py`(+33)、`cli/console.py`(+18/−2)、`tests/test_debug_mode.py`(128，7 例) | 默认块逐字不变 / 开启后 traceback 收尾 / 无异常不产假 traceback / 级别强制 DEBUG |
| 性能分析 | `scripts/profile_run.py`(152)、`tests/test_profile_script.py`(123，5 例) | `--` 参数透传 / 崩溃仍留报告 / SystemExit 码透传 / tottime 单调降序 |
| 配置面 | `config/__init__.py`(2 键)、`catalog/groups.py`、`catalog/guards.py`、`.env.example`(5 行) | 字段文档化（双射测试）、分类完备、白名单 51 → 53 |
| 文档 | `docs/frame.md`（4.10 两行 + pub 模块清单两处 + 日志卫生段）、`docs/performance.md`（单点 profile 节改写）、`README.md`（开发容器节）、`CHANGELOG.md`（5 条） | — |

**门禁实测**：

```text
pytest -m "not integration and not benchmark" -q   → 4867 passed / 51 skipped / 25 deselected（223.79 s）
quality_gate.py（首轮）                             → 仅 test_profile_script 1 例红（见下）
ruff check / ruff format --check / mypy src          → 全绿（mypy: 222 files, no issues）
bandit -r src/ -ll                                  → 退出码 0（无 medium+ 严重度）
contract_snapshot.py --check                        → 四份基线 OK（未重生）
```

## 判据的变异实测（均改完立刻还原，还原后复跑绿）

- `ci.yml` 的 `mypy src` → `mypy src/heagent`：**第一版纯子串匹配没红**，据此加「片段右侧须为空白或行尾」
  的边界后红；`bandit -r src/ -ll` → `true` 同样红。
- 结构化日志/调试模式/开发容器的判据都是「装配后真读文件/真读 Settings 默认值」，没有只测渲染函数的空转断言。

## 收口现场修掉的一个真问题

首轮全门红在 `test_hot_functions_is_sorted_by_self_time`（`profile_run` 的排序判据）。单独跑该文件绿、
带 `--cov` 单跑也绿，全量跑才红 ⇒ 根因是 `cProfile` 是**进程级钩子**：全量回归里进程带着别的线程，
噪声把「谁最热」这个排名冲掉了。处置：判据从「第一名必须是 busy」改为**受控剖面**下断言
「heavy 排在 light 之前 + tottime 单调不增」。教训：给进程级工具写断言时，排名类断言在并行/多线程环境
必然脆，改为关系断言。

## 决策与刻意不做的事

- **不让 devcontainer 镜像复述 extras 清单**：`pyproject.toml` 是唯一真源，镜像里再抄一份必然漂移 ⇒
  extras 安装放 `postCreateCommand`，镜像层只放与源码无关的东西。
- **不加 `scripts/bump_version.py`**：验收标准已被 Q2 作废，脚本写成什么样都算「完成」，属自证；
  两处不一致已有秒级判据（契约测试）。
- **不引 CHANGELOG 生成器**：本仓提交信息是「中文 Conventional Commit + 只写修改点」，
  而 CHANGELOG 每条还带活动台账编号/判据说明——生成器只能产骨架噪声。
- **不装 py-spy / 不产 SVG 火焰图**：外部二进制 + `ptrace` 权限，装进依赖树会污染安装面；
  脚本只产文本报告，attach 型火焰图在文档里给命令。
- **不把 json 变默认、不给 CLI 加 `--debug`**：默认格式变化属破坏性；旗标要贯穿每个子命令装配面。

## Open questions / 残留

1. **`runtime_stats` 不读 json 格式日志**：采集器按行正则解析 text 行，`LOG_FORMAT=json` 后它
   采不到数据 —— 这是「换格式就要换消费方」的已知前提，已写进 `docs/frame.md` 的日志卫生段，
   并**登记台账 A58**（`active`，触发条件 = 长期使用 json 且需要统计口径；闭合动作 = 采集器加 JSON 分支）。
2. **devcontainer 启动耗时为估算**：本开发容器内无 docker daemon（`docker info` 不可用），
   README 标注的是「约 2–3 分钟」而非实测；首次在有 docker 的机器上 `devcontainer up` 后应回填实测值。
3. **`release` 的失败通知依赖 GitHub 自带邮件**：无外部 webhook（引入 secret 会破坏「零 secret 发布」契约）；
   若用户需要即时推送，需单独立项并明确 secret 策略。
4. **`bandit` 的 8 条 High-confidence 低严重度项长期存在**（`-ll` 门限下不阻断），未在本 epic 内清理。
