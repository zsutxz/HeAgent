# 文件安全与凭证防护周期 · Retrospective（Epic 37）

> 日期：2026-09-18（**补做**：原 `sprint-status.yaml:379` 标记 `epic-37-retrospective: optional`）
> 范围：`_bmad-output/epics/epic-36-39-文件安全防护周期/`（Epic 37，1 个 story：37-1 `scrub_sensitive_env` 纯函数 + shell spawn 接入）
> 动机：`_run_subprocess_shell` / `_run_subprocess_exec` 调 `create_subprocess_*` 时不传 `env`，子进程继承父进程全部环境，`shell("env")` 可直接泄出 `*_API_KEY`（`brief.md` 问题 2）。

## 一、做了什么

| Story/交付项 | 核心交付 |
|------|----------|
| 37-1 主体 | `sandbox.py:142` `_SENSITIVE_ENV_SUFFIXES`（`_API_KEY` / `_API_KEYS` / `_TOKEN` / `_SECRET` / `_PASSWORD` / `_CREDENTIALS` / `_PRIVATE_KEY`）+ `:153` `scrub_sensitive_env(env=None, *, allowlist=None)` 纯函数（按键名 `.upper().endswith(...)` 剥离，大小写不敏感；默认取 `os.environ`） |
| 37-1 接入 | spawn 点传 env：`_spawn_kwargs():202` → `:207` `kwargs["env"] = scrub_sensitive_env(...)`，`_run_subprocess_shell:236` 与 `_run_subprocess_exec:242` 共用该 kwargs（两条路径不会分叉） |
| 交付 | commit `a1d886d`「feat(security): 文件安全与凭证防护周期 Epic 36-39」（25 files，+1881/−44；其中 `tools/sandbox.py` +27） |
| 测试 | `tests/test_credential_guard.py:115` `TestScrubSensitiveEnv`（`test_strips_sensitive_keys:116`、`test_case_insensitive:135`、`test_keeps_nonsensitive:141`、`test_empty:146`） |

## 二、做对的

1. **「按模式剥离敏感 key」而非白名单透传（AD-F3）**——只剥匹配敏感后缀的键，`PATH` / `HOME` / `LANG` 原样透传，`TestScrubSensitiveEnv.test_keeps_nonsensitive:141` 直接钉住 shell 工具可用性不退化（对应反指标 SM-C2）；若照 hermes 全白名单，shell 工具会大面积失效。
2. **剥离逻辑是零 I/O 纯函数**——`scrub_sensitive_env` 可脱离引擎、脱离子进程单测（`tests/test_credential_guard.py:116-147`），符合 NFR-F3「不触达 LLM、确定性」。
3. **接入点单点化**——改造后 shell 与 exec 共用 `_spawn_kwargs():202`，`env` 剥离与 `start_new_session` 等 kwargs 在同一处构造（`sandbox.py:236,242` 各自只有一行 spawn）；后端 Passthrough / Firejail / WinJob 零改动。
4. **豁免是「显式列举」而非「默认放开」**——后续 Epic 40.3 加 `allowlist` 时，未配置（None/空）行为与改动前逐字节一致（`test_allowlist_empty_identical_to_default:156`），默认仍是全剥离。

## 三、可改进的

1. **spawn 集成测试实际缺席，AC-3 只靠代码可读性成立**——story 37-1 的 Task 3 要求 `test_run_subprocess_shell_passes_scrubbed_env` / `test_run_subprocess_exec_passes_scrubbed_env`；本回顾实测 `tests/test_sandbox.py`、`tests/test_coverage_sandbox.py` 对 `scrub` **零命中**，全仓测试也无 `kwargs["env"]` 类断言。`a1d886d` 对这两个文件只做了形参扩容（如 `test_sandbox.py:106,443` 的 `fake_shell` / `fake_exec` 加 `env=None`），使既有 fake 不再因新 kwarg 报错——**「能接受 env」≠「验证了传的是什么 env」**，最小失效模式（漏传 env / 传原始 os.environ）不会被任何测试抓到。
2. **敏感模式是固定后缀表，覆盖面对外不透明**——`sandbox.py:142` 的 7 类后缀不含 `*_CLIENT_SECRET` / `*_PASSPHRASE` 等，`prd.md:219` 的 Q1 至今是 Open Question；新增一类后缀需要改代码（与 AD-F2 的「内置纯函数」立场一致，但 Q1 未收口）。
3. **spine 与实现再次偏差**——`architecture.md` 写「`_run_subprocess_shell` / `_run_subprocess_exec` 传 `env=...`」（两点），实现已是 `_spawn_kwargs()` 单点（`sandbox.py:202`）；架构文档未回写，与 Epic 36 的第 2 条同型。

## 四、教训

1. **让既有 fake 接受新参数是最容易被误当成「已测」的假绿**——测试签名扩容只证明「不炸」，不证明契约；凡 AC 写成「传 X」，就必须有测试捕获 kwargs 并断言其内容，否则该 AC 实际由代码审查兜底。
2. **防护强度与可用性的折中要留显式反向通道**——「默认剥离 + 可选豁免」比「默认透传 + 可选收紧」安全；豁免必须逐变量列举、默认关闭，才不必靠改代码放宽（后由 `SANDBOX_ENV_ALLOWLIST` 兑现）。
3. **同一威胁的第二条路径要显式记账**——env scrubbing 只覆盖 shell 工具的 spawn 点；MCP stdio server 由 SDK 自行 spawn，不经过这两个 helper（`deferred-work-archive.md:15`，严重度中-高），若只在本 epic 内宣称「子进程凭证已处理」即为不诚实。

## 五、遗留项状态

- 已闭合：F-D1 凭证 deny 项目级配置入口 `.heagent/path_deny.json`——commit `63806d3`（属凭证 deny 面，非 scrub；`scrub_sensitive_env` 侧无用户配置面，只有后来 Epic 40.3 的 `sandbox_env_allowlist`）。
- 仍开：MCP stdio server 子进程的 env scrubbing / 不经沙箱（严重度 中-高，`implementation-artifacts/deferred-work-archive.md:15`）。
- 已判定不成立：「cron job 脚本子进程 env scrubbing」——`cron/` 无子进程路径（`brief.md` Deferred 段 2026-09-15 核实；`deferred-work-archive.md:15` 注同）。
- 仍开（跨周期）：沙箱 env 豁免 `sandbox_env_allowlist` 本身亦非安全边界（`docs/frame.md:882` 已知缺口）。

## 六、结论

Epic 37 以约 27 行生产代码换到「shell 子进程默认拿不到 API key」，方向和形状都对：纯函数 + 单点接入 + 保留非敏感变量。唯一的实质欠账在测试面——AC-3 的「spawn 传入 scrub 后的 env」无任何断言，属于典型假绿窗口；它不改变当前代码的正确性（`sandbox.py:207` 确实传了），但让这一层在后续重构中没有护栏，建议下次动 `_spawn_kwargs` 前补两个 kwargs 断言。
