# 文件安全与凭证防护周期 · Retrospective（Epic 36）

> 日期：2026-09-18（**补做**：原 `sprint-status.yaml:375` 标记 `epic-36-retrospective: optional`）
> 范围：`_bmad-output/epics/epic-36-39-文件安全防护周期/`（Epic 36，4 个 story：36-1 凭证写 deny 规则表 / 36-2 凭证读 deny + handler 守卫 / 36-3 policy deny 预检 / 36-4 SafetyGuard 凭证破坏性命令拦截）
> 动机：文件层原本只有「工作区围栏」一个维度——`file_read(".env")` 原样返回 API key、`file_write` 可覆盖凭证文件（`brief.md` 问题 1）。

## 一、做了什么

| Story/交付项 | 核心交付 |
|------|----------|
| 36-1 | `path_safety.py:102` `build_write_denied_paths()`（realpath 精确表：`~/.ssh/authorized_keys`、`~/.ssh/id_rsa`、`~/.ssh/id_ed25519`、`~/.env`、`~/.netrc`、`~/.npmrc`、`~/.pypirc`、`~/.git-credentials`、`/etc/sudoers`、`/etc/passwd`、`/etc/shadow`）+ `:123` `build_write_denied_prefixes()`（`.ssh/`、`.aws/`、`.gnupg/`、`.kube/`、`.docker/`、`.azure/`、`.config/gh/`、`.config/gcloud/`、`/etc/sudoers.d/`）+ `:168` `check_write_denied()` |
| 36-2 | `path_safety.py:139` `build_read_denied_basenames()`（`.env` 及其 local/development/production/test/staging 变体、`.envrc`）+ `:186` `check_read_denied()`；handler 守卫接入：`file.py:40→43`（先围栏后写 deny）、`file.py:96→97`（读侧重载） |
| 36-3 | `policy.py:127` `_PATH_FIELDS`、`:140/:141` `_DENY_READ_TOOLS`/`_DENY_WRITE_TOOLS`；`_validate_paths` 在围栏循环之后（`:295` 起）挂 deny 预检——git 工具只走围栏不接 deny |
| 36-4 | `safety.py:79` `_CREDENTIAL_PATH_ALT` + `:84-86` 两条 `_CREDENTIAL_DESTRUCTIVE_PATTERNS`（`rm`/`mv`/`rmdir`/`unlink` 作用于凭证路径、`>` 重定向覆盖凭证路径）+ `:148` 在 `check()` 第一层后接入 |
| 测试 | 新增 `tests/test_credential_guard.py`：`TestDenyRuleBuilders:43`、`TestCheckWriteDenied:80`、`TestCheckReadDenied:95`、`TestFileHandlerDeny:181`、`TestPolicyDenyPrecheck:215`、`TestCredentialDestructiveCommand:252` |
| 交付 | commit `a1d886d`「feat(security): 文件安全与凭证防护周期 Epic 36-39」（25 files，+1881/−44，含本周期 4 个 Epic / 6 个 story 与规划产物） |

## 二、做对的

1. **deny 是与围栏并列的独立纯函数层（AD-F1）**——`path_safety.py:102-205` 无 I/O、无 contextvar，`check_write_denied` / `check_read_denied` 可脱离引擎单测（`tests/test_credential_guard.py:43,80,95`）；`resolve_under_root` 一行未改，`git.py` 不受影响。顺序「先围栏后 deny」在代码里可逐行核对：`file.py:40→43`、`search.py:23→26` 与 `:39→42`。
2. **两层纵深各自独立、共用同一对纯函数**——policy 预检（`policy.py:295-306`）与 handler 守卫（`file.py:43,97`）不会各持一份可漂移的副本；AC-2「workspace 内但命中 deny 仍 BLOCKED」由 `TestPolicyDenyPrecheck.test_policy_deny_independent_of_fence:236` 钉死。
3. **同一威胁补第二刀（36-4）**——`check_write_denied` 只管 `file_write`，`rm` / `mv` / 重定向走 shell 仍可删改凭证；`safety.py:84-86` 补命令层，并以 `test_allows_non_credential:287` 证明 `cp` 与普通重定向不误伤。

## 三、可改进的

1. **story 的 Task 清单与实际测试名对不上**——36-1 列了 `test_check_write_denied_exact_match` 等 5 个名字，落点实为 `TestCheckWriteDenied` 的 `test_exact_match:81` / `test_prefix_match:86` / `test_not_denied:90`：能力覆盖了，但 checkbox 与代码无一一对应，交付后无从据 story 核查（story 文件 frontmatter 至今仍 `status: backlog`）。
2. **architecture.md 的伪代码未回写**——spine 里 `build_write_denied_paths` 只列 11 条、`build_internal_state_dirs` 只覆盖 home 下 4 个目录；实现（`path_safety.py:152-166`）覆盖 `cwd` 与 `home` 两个根 × `sessions/ledger/runs/memory/skills` 5 个子目录。口径最终只在 `docs/frame.md:431` 对齐，spine 成了过期快照。
3. **6 个 story 的 frontmatter 至今 `status: backlog`**（本回顾实测 36-1 / 36-2 / 36-3 为 backlog，同 epic 的 36-4 为 `done`），与 `sprint-status.yaml:371-374` 的 `done` 不一致；`_bmad-output/consolidated-overview.md:934` 与 `retrospective-all-cycles.md:211` 均已登记为「仍开」。

## 四、教训

1. **每加一层启发式，必须同时写下它拦不住什么**——`check_*_denied` 只拦走工具层的路径，shell 里 `cat .env` 依然通。该立场已固化在 `docs/frame.md:879`（已知缺口行）与 CLAUDE.md 安全声明（`CLAUDE.md:99`），是跨周期可复用的纪律。
2. **一个威胁要枚举全部可达路径**——凭证写有 `file_write` 与 shell 两条路（36-4 的由来）；凭证读同理有 `file_read` 与 `content_search`（`search.py:42`）。只封一条，另一条就是静默缺口。
3. **纯函数层是这类加固的最小代价形态**——可独立单测、独立演进、不污染既有调用方（`resolve_under_root` / `git.py` 零改动）；`consolidated-overview.md:642` 已把这条记为周期教训，后续同类加固宜默认采用。

## 五、遗留项状态

- 已闭合：F-D1 凭证 deny 规则项目级配置入口 `.heagent/path_deny.json`——commit `63806d3`（2 files，+269/−5：`path_safety.py` +123 / `tests/test_credential_guard.py` +151）。实现见 `path_safety.py:208` `_USER_DENY_PATH`、`:212` `_UserDenyRules`、`:231` `user_deny_rules()`（经 `resolve_under_root` 做 workspace 锚定）；测试 `TestUserDenyRules:295`（含「内部状态目录 deny 不接受豁免」）。
- 仍开：凭证 store 绝对路径读 deny（`prd.md:220` Q2 仍为 Open Question；`consolidated-overview.md:641` 记为「仍开」）——活动台账 `implementation-artifacts/deferred-work-archive.md` 中**无**对应条目（本回顾实测该文件无「凭证」命中）。
- 仍开（跨周期，非本 epic 归属）：仅 MCP stdio 子进程不经沙箱（`consolidated-overview.md` §17.4-A2）；原列于此的 `RoleSpec.sandbox_profile` 死字段与沙箱进程数限额（原 §17.4-A5/A6）已于 2026-09-18 闭合。

## 六、结论

Epic 36 交付了本轮的核心价值面：凭证写 / 读两套规则表 + handler 与 policy 双层守卫 + shell 层补刀，全部落在既有防护点的纯函数增量上，无新架构、无执行链改动。真正值得带走的是「独立层 + 枚举可达路径 + 诚实声明非边界」这三条形状；真正欠的是纪律尾巴——story frontmatter 的 `backlog` 与 spine 伪代码的过期，二者都不影响代码正确性，但都会让下一轮复核多花一次勘察成本。
