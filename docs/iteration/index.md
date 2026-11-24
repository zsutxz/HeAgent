# HeAgent 迭代开发指南与历程

> 状态：历史历程与迭代方法。维护责任：各周期变更提交者。架构迁移索引见 [cycles.md](cycles.md) §3.3；历史测试数和状态不作为当前质量基线。

> 本目录回答两件事：**项目是怎么一步步迭代到现在的**（历程，见 [cycles.md](cycles.md)），以及**怎么继续迭代**（流程，本文）。架构看 [`framework.md`](../framework.md)，愿景看 [`design.md`](../design.md)，本文只讲「迭代」这一维度。

## 这份文档的位置

| 文档 | 视角 | 回答 |
|------|------|------|
| `design.md` | 产品 | 为什么要做、目标与非目标 |
| `framework.md` | 架构 | 现在的实现怎么工作 |
| **`iteration/`**（本目录） | 工程 | 怎么迭代过来的（`cycles.md`）、怎么继续迭代（`index.md`） |

> **路径口径**：下文引用的 `_bmad-output/epics/<周期>/` 是**当前**布局——2026-11-15 起
> `archive/epics/` 已并入 `epics/`（归档周期与活跃周期同目录混排），故历史句子里也一律写当前路径。
> 文件名同理：`docs/frame.md` 已改名 `docs/framework.md`（2026-11-20），历史句子一律写现行名。
 > 状态真源同样在 2026-11-15 换代：v6 的 `sprint-status.yaml` 归档在
> `_bmad-output/Goal-2-v6/`（只读；2026-11-20 自 archive-v6/ 上移），v7 的活动票树随 goal 树落
> `docs/<goal-id>/tickets/`（指针 `docs/current`；原住 `_bmad-output/Goal-3/tickets/`）。

`_bmad-output/` 是各周期的原始产物（brief/prd/epics/stories），是 [cycles.md](cycles.md) 历程章节的事实来源之一；当本文与 `_bmad-output/` 或代码冲突时，以代码为准。

---

## 一、迭代模型（怎么继续迭代）

HeAgent 用 **BMad Method** 驱动迭代，组织单元是「**周期（Cycle）**」。一个周期 = 一个独立的目标集（一组 FR），产出自己的一套规划文档。

### 1.1 四类周期

| 周期类型 | 触发 | 产物目录 | 编号空间 |
|----------|------|----------|----------|
| **主线周期** | 新产品方向 / 大功能集 | `_bmad-output/<cycle>/`（brief→prd→architecture→epics→stories） | Epic 沿主线编号递增 |
| **集成周期** | 接入外部系统（如 MCP） | 同上，独立 brief/prd | Epic 编号延续主线 |
| **补丁周期** | 计划外技术债 / 缺陷 | 补丁 spec 按归属 epic 归入 `_bmad-output/epics/<周期>/<epic-NN-主题>/`（原 `patches/` 2026-09-15 解散）+ 各周期 `deferred-work.md`（已闭合项归档） | spec 文件，不占 Epic 编号 |
| **epic 外增量** | 架构演进（如 engine 治理层） | 直接落代码 + `framework.md` 记录 | 按 P0/P1… 分批 |

### 1.2 历史规划周期工作流

下面是历史规划产物采用的周期级顺序；它解释 `_bmad-output/` 的目录结构，不等于当前 `/goal` 的运行时步骤。
当前运行时工作流见 [`framework.md` §4.13](../framework.md#413-goal-驱动工作流-goal)。

每个历史周期按此顺序推进，每步对应一个 BMad 技能（`bmad-*` 前缀）：

```
brief  →  prd  →  architecture  →  epics  →  stories  →  quick-dev  →  code-review
 产品意图   功能需求  技术架构         拆 epic      拆 story      执行实现      对抗式审查
```

1. **brief**（`bmad-product-brief`）：产品意图与边界，决策记入 `*-decision-log.md`。
2. **prd**（`bmad-prd`）：功能需求（FR/NFR）。
3. **architecture**（`bmad-architecture`）：技术架构与冻结决策。
4. **epics**（`bmad-create-epics-and-stories`）：FR → Epic 拆分 + 覆盖矩阵。
5. **stories**（`bmad-create-story`）：Epic → 可执行的 story（含 AC）。
6. **quick-dev**（`bmad-quick-dev`）：按 spec 实现（见 1.3）。
7. **code-review**（`bmad-code-review`）：分层对抗式审查。

> `sprint-status.yaml` 跟踪每个 story 的状态流转：`backlog → ready-for-dev → in-progress → review → done`。

### 1.3 历史 Story 执行：quick-dev + spec 冻结

历史 quick-dev 是**基于 spec 的单会话执行**：

- 每个 story / 缺陷 / 变更先冻结成一个 **spec**（明确做什么、不做什么的边界），再实现。
- **一会话一 spec**：完整 spec 执行接近单会话 token 上限，多个缺陷要拆成多次会话分别执行（参见记忆 `bmad-quickdev-budget-per-spec`）。
- spec 边界之外的发现 → 不就地扩展，而是记入 `deferred-work.md`（活动台账现为根目录 `_bmad-output/open-items.md`「活动（未闭合）条目」节；文中旧路径 `implementation-artifacts/deferred-work-archive.md` 已于 2026-11-15 并入该节与 retrospective §三；见 1.4）。

### 1.4 技术债延期机制

迭代中发现的、**超出当前 spec 冻结范围**的问题，走 deferral，不悄悄塞进当前改动：

1. **发现**：code-review 的 edge case hunter / blind hunter 发现。
2. **分类**：`fix now`（当前 spec 内修）/ `defer`（记入 deferred-work）。
3. **记录**：写入活动台账（现为 `_bmad-output/open-items.md`「活动（未闭合）条目」节，append-only），含触发条件、严重度、冻结边界说明、建议修法。
4. **收尾**：后续开专门 spec 处理，修完写 `Resolution` 段关闭；**闭合后按归属 epic 归档**到 `_bmad-output/epics/<周期>/deferred-work.md`（保留结论、证据与 commit 指针，不保留原始长文历史）。

> **已闭合项归档（2026-09-15 整理）**：原跨周期台账 `_bmad-output/patches/_meta/deferred-work.md` 的条目已全部闭合，按归属 epic 归并进各周期 `deferred-work.md`（`epic-01-10-主线规划周期`、`epic-11-18-MCP集成周期`、`epic-S1-S4-沙箱硬化周期`、`epic-40-沙箱会话化周期`、`epic-41-目标驱动开发周期`、`epic-47-声明式BMad敏捷工作流周期`），原台账随之退役并删除。条目索引见 `_bmad-output/retrospective-all-cycles.md` §三（deferred 闭合与归档台账；原 `consolidated-overview.md` 已并入 `open-items.md` 与 `retrospective-all-cycles.md`）。

### 1.5 sprint-status 维护规则

- **Epic 编号延续主线**：新周期自称 Epic 1-N 会撞主线编号，故延续主线编号递增（MCP 周期 = Epic 11-13，MCP V2 周期 = Epic 15-18）。
- **story key 须匹配 `epic-N-M` 模式**：`sprint-status` 技能校验 key 格式，不能用自定义前缀（如 `mcp-`）。
- **MCP 周期映射**（2026-08-18 三目录合并为 `_bmad-output/epics/epic-11-18-MCP集成周期/`）：sprint-status 的 Epic 11-13 = `epics.md` 阶段一内部 Epic 1-3；Epic 14 = `epics.md` 阶段二；Epic 15-18 = `epics.md` 阶段三内部 Epic A/B/C + 内置工具扩展。
- **回顾字段**：每个 epic 配 `epic-N-retrospective`，状态 `optional`（可做不做）或 `done`（已完成）。
- **单一权威（2026-07-23，v6 口径）**：全周期 sprint-status 统一在 `_bmad-output/sprint-status.yaml`，旧文件保留作为只读归档。**v7 起（2026-11-15）状态真源换成票树**：现住 goal 树自带的 `docs/<goal-id>/tickets/`（指针 `docs/current`），原住 `_bmad-output/Goal-3/tickets/`，该 yaml 归档于 `Goal-2-v6/`（只读历史；2026-11-20 上移目录根）。

### 1.6 实现会话收尾清单（2026-10-26 落盘，闭环 Epic 53/54 retro 4 条 process item）

**每个实现会话结束前逐条核对**；4 条均为已发生失误的根因闭环，不是新增流程税。

1. **状态回写**（源：epic-54 retro A3；根因：Epic 54 全部 story 漏回写 sprint-status）——story 实现完成即回写两处：
   story 文件 frontmatter `status` + `_bmad-output/sprint-status.yaml` 对应 story 行；会话收尾前核对该 epic 名下
   无 `in-progress` / `review` / `ready-for-dev` 残留。（v7 起回写目标改为票树：`tickets/…/tickets.toml` 的
   entry 状态与 story plan frontmatter，`tickets.py mark` 是唯一合法写路径。）
2. **squash 后真实保留 backup ref**（源：epic-54 retro A4；根因：98ef6d8 提交信息引用了不存在的 `backup/pre-squash-abb406a`）——
   squash/amend 类改写历史操作后立即 `git branch backup/pre-<op>-<short-sha>`，保留至验收期满；
   提交信息**不得引用不存在的 ref**。
3. **评审前置**（源：epic-53 retro A53-1；根因：walkthrough 误报事件）——评审/验收论断前必须**读完 story 全文** +
   **实际运行行为验证**（跑测试/复现路径），禁止仅凭 diff 或转述下结论。
4. **契约测试子集不豁免**（源：epic-53 retro A53-2；根因：0e8a330 台账契约红 1 天 + a545613 端口顺延，非代码提交绕过契约）——
   政策/台账/纯 docs 类提交也须跑 `pytest tests/test_architecture_contracts.py -q`（台账契约与文档强耦合，
   非代码提交同样能打破）。

---

### 1.7 提交 SOP（2026-11-11 落盘）

三句话：**取证 → 呈报清单 → 获准后提交**。任一步跳过都算越权。

1. **取证**：`git status --porcelain`、`git diff --stat`、文件卫生（CR 计数 0 / 无 BOM）、是否触碰 `src/`（纯文档 story 必须为空）。
2. **呈报**：给用户看「拟用提交信息 + 文件清单 + 取证结果 + 未跑的检查及原因」，然后**停下等**。
3. **获准后提交**：`git add` → `git commit -F <msg 文件>`（多行信息走文件，写前先核 `\r\n` = 0 且无 BOM）。

触发词：`git commit` / `提交代码` / `确认` 都是同一纪律的触发，**不能因为换了说法就跳过呈报**。

反例（都算违规）：
- 先 `commit` 再汇报；
- 把「我改了但没让你看」当默认；
- 用「改动都很小」为由省掉清单。

环境坑：9p 挂载 + 宿主 GitKraken 会反复创建 `.git/index.lock`；`rm -f .git/index.lock` 会被 `SafetyGuard` 拦，
用一次性 Python 脚本 `Path('.git/index.lock').unlink(missing_ok=True)` 后**立即** `git add` + `git commit`。

---

## 二、迭代历程（怎么走到现在）

> 已迁至 [cycles.md](cycles.md)：按 Epic 分期的各周期（2.1–2.12）与迭代时间线（2.10）。

---

## 三、架构优化与维护

### 3.1 架构简化计划（2026-09-27）

**结论**：Provider 容错栈统一（早期完成）、TCP 入口删除（-2,800 行 / 6 文件 + 10 配置字段）、上下文管理统一落地，累计 -2,815 行（7.9%）/-6 文件、零回归；CLI 重组评估后**不执行**——预期收益仅 -100~200 行，且需迁移 15 个 monkeypatch 缝，风险大于收益。原计划文档 `architecture-simplification-plan.md` 已删除，结论归档于此。

---

### 3.2 内存注入预算解决方案

**问题**：MEMORY.md 采用 append-only 策略，条目持续增长导致超出默认注入预算（49152 字节），最新事实被省略（历史口径：当时注入为保头截尾；2026-10-30 story 59-3 已翻转为保尾省头，现行口径见 `framework.md` §4.6）。解决方案为三层：扩大注入预算（`MEMORY_INJECT_MAX_BYTES=98304`）、`memory/auto_archive.py` 自动归档超限老条目、手动整理（压缩原则与工具见 MEMORY.md 文件头部注记）。

**权威口径**：早期「按估算天数归档 / 按月分文件」（`.archive-stamp`）口径已于 2026-10-10 重写删除；现行触发阈值、归档落点、并发写语义与测试判据一律以 [`framework.md` §4.6](../framework.md) 为准（判据 `tests/memory/test_auto_archive.py`）。原方案文档 `memory-budget-solution.md` 已删除。

### 3.3 架构沿革与参考来源

> 已迁至 [cycles.md](cycles.md#33-架构沿革与参考来源)：迁移记录、参考实现与 path_safety 借鉴。

---

## 四、经验教训（轻量回顾）

> 下面是从 `deferred-work.md`（原跨周期台账，2026-09-15 退役并删除）、`framework.md` 已知缺口、git log 反推的跨 epic 教训。
> **2026-07-22 更新**：全部 24 个已完成 Epic + S1-S4 的正式回顾已完成（产物 `_bmad-output/retrospective-all-cycles.md`），所有 sprint-status 的 `epic-N-retrospective` 均已标记 `done`。以下 10 条为跨周期课纲，详尽「做对/可改进」见全周期回顾。

1. **edge case hunter 会误判并发竞态**（Epic 5 / SubAgent）：deferred-work 第一条把「多协程访问共享 SkillStore」判为竞态，经核实不成立——`record_usage` 是无 `await` 的同步原子段，单线程 asyncio 下必然串行。**教训**：审查发现要核实是否真有 `await` 交错，加回归测试锁定不变量即可。
2. **异常包装要加守卫，避免双层重包**（Epic 1 / ProviderChain）：provider 源头包成 `ProviderError` 后，chain 的 `except` 又包一层。**教训**：`_wrap_error` 类入口加 `if isinstance(e, ProviderError): raise`；用 `__cause__` 链断言写回归测试。
3. **流式与同步路径要对称**（Epic 1）：`send()` 的 backstop 跟踪 `last_error`，`stream()` 版本一度漏了。**教训**：成对的 send/stream 实现要互相对照，补齐对称路径。
4. **安全边界必须诚实声明，不制造「更安全」假象**（Epic 13 / engine）：`SafetyGuard` 与 engine sandbox 都不是真边界。**教训**：安全相关代码注释里写明「非真正边界，须 OS 级沙箱兜底」，见 `CLAUDE.md` 文首声明。
5. **两种模式并存要标记冲突，而非折中**（engine / 工作区路径双重围栏，**已收敛**）：`PolicyEngine._validate_paths()` 与 `tools/path_safety.py` 曾两套围栏并存。**教训**：改其一须同步评估另一处，冲突在文档显式标出——后经收敛为共用 `resolve_under_root` 单一算法（两层有意纵深防御）解决（2026-07-01 commit `2ae99ed` 落地，`c7171ba` 同步 framework.md/CLAUDE.md 已知缺口）。
6. **评估结论要留依据**（engine P5-1/P5-2）：暂缓决策（D1/D4）把理由写进 `framework.md`，避免日后重做时忘记为何如此——P5-1/P5-2 后于 2026-07-21 反转交付，当初的取舍依据仍有助于理清演进。
7. **缓存命中仍须复核策略裁决**（engine / ExecutionLedger）：ledger COMPLETED 缓存命中后曾直接返回，未复核最新 policy——若 policy 收紧为 `BLOCKED` 仍返回缓存会绕过门禁。**教训**：缓存层与策略层交叉时，命中后仍须过一遍 policy（commit `84ee783`）；同理 lease-active 命中跳过执行，防并发/重入重复跑 handler（`c07f811`）。
8. **关停/清理路径必须有硬上界**（sandbox / MCP / cron，2026-07-09~11）：`_kill_and_reap` 的 `proc.wait()`、MCP `__aexit__` 的 transport close、`CronScheduler.stop` 的 task join 都是裸 `await`，遇不可中断 await 点（Linux D-state / 远端不 FIN / job 执行中）会无限阻塞，唯一调用方（CLI 退出路径）挂死需 OS SIGKILL。**教训**：凡 `task.cancel()` + `await` 的关停结构，`await` 必包 `asyncio.wait(timeout=N)`，超时记 ERROR 放弃——三处同构缺口同批补齐（`spec-sandbox-reap-robustness` / `spec-mcp-shutdown-timeout` / `spec-cron-stop-timeout`）。
9. **上下文切分要保证消息配对完整**（compressor，2026-07-16）：compressor 按预算切分历史时，切点若落在 TOOL 调用与其 TOOL 结果之间，会留下孤儿 TOOL 消息（有调用无结果），破坏 LLM 的 tool_use/tool_result 配对约束。**教训**：切分边界须以完整工具轮次（call+result）为不可分割单元。
10. **跨 task session 泄露要两面收尸**（MCP `_server_loop`，2026-07-17）：`_server_loop` 在 `__aenter__` 成功后登记 `self._sessions[name] = session`，但 `_discover_and_register` 失败时 `except` 处理器只 set ready 未 pop——`_sessions` 残留虚假 session，桥接工具据此注册，后续调用抛异常。**教训**：配对登记的清理点必须覆盖全部退出路径（`except` + `finally` 两面收尸），单靠 `finally` 不够——`finally` 仅清 `entered` 路径，`except` 段的 early return 漏了 `finally` 后的 `pop` 收尾。

---

## 五、路线图与下一步

**历史快照（2026-08-19）**：当时记录的 9 个开发周期（主线 Epic 1-10、MCP 11-18、Sandbox 硬化 S1-S4、健壮性/质量 19-24、GUI 25-28、交互与可扩展层 29-35）已全部交付；该日期的测试统计仅代表当时状态。后续周期状态以下方「六、相关索引」的 sprint-status 为准；`pytest --collect-only -q` 收集数以本地运行结果为准，质量门禁仍需在可写临时目录下运行。

**当前缺口**（详见 `framework.md` 第五章）：

- `SafetyGuard` / `path_safety` / engine sandbox 均非真边界，须 OS 级沙箱兜底。
- `ToolExecutor.execute_in_sandbox()` 默认 Passthrough 透传；可注入 `FirejailBackend`（仅 shell 子进程、Linux-only、非完美边界），file/memory 等不受覆盖。

**下一步（候选，非承诺）**：

- ✅→⏳ **生产化**（2026-11-23 更新）：PyPI 已发 `0.10.0`；`0.11.0` 已归节（Epic 72/73 的破坏性变更按 0.x「minor 即破坏性变更」口径走 minor）；2026-11-24 起对外版本号重编为 `0.2.0`（历史节保留），下一次发布打 `v0.2.0` tag。`ci.yml` 内 release job 已具备 build / twine check / OIDC 发布 / 多架构推送；仍缺 Docker Hub 镜像。
- 🔮 **可选增强**：多模态（vision）、Web API 服务端（均与 `design.md` 当前非目标冲突，需重新评估）；Hooks 增强（`UserPromptSubmit`/`Stop`/`SubagentStop` 事件、参数模板引擎）。

---

## 六、相关索引

### 2026-09-01：目标级工作流质量收口

Epic 43-44 的实现已完成，Epic 45.3 补齐了无网络两-story 冒烟、checkpoint/ledger/EventBus 审计证据、损坏状态显式失败测试，以及 `scripts/quality_gate.py` 统一质量门。Epic 46.1 完成 TOCTOU assessment，Epic 46.2 为资源读取增加 descriptor + `O_NOFOLLOW` 最终组件加固；中间目录竞态、可信导入 snapshot 与 OS sandbox 仍保留为后续工作。

- 架构权威：[`framework.md`](../framework.md)（engine 模块见 4.12、已知缺口第五章）
- 当前工作流：[`framework.md` §4.13](../framework.md#413-goal-驱动工作流-goal)（`.heagent/skills/he-goal/workflow.md` 为 `/goal` 的可执行契约；v7 的 `/loop` 契约在同级 `loop/`）
- 产品愿景：[`design.md`](../design.md)
- **全周期回顾**：[`_bmad-output/retrospective-all-cycles.md`](../../_bmad-output/retrospective-all-cycles.md)
- 迭代原始产物：`_bmad-output/epics/epic-01-10-主线规划周期/`、`_bmad-output/epics/epic-11-18-MCP集成周期/`（原 mcp-client/ + mcp-v2-upgrade/ + mcp-client-v2/，2026-08-18 合并）、`_bmad-output/epics/epic-S1-S4-沙箱硬化周期/`、`_bmad-output/epics/epic-19-20-健壮性硬化周期/`、`_bmad-output/epics/epic-21-24-质量工程周期/`、`_bmad-output/epics/epic-25-28-GUI界面周期/`、`_bmad-output/epics/epic-29-35-交互扩展周期/`、`_bmad-output/epics/epic-36-39-文件安全防护周期/`、`_bmad-output/epics/epic-40-沙箱会话化周期/`、`_bmad-output/epics/epic-41-目标驱动开发周期/`、`_bmad-output/epics/epic-42-BMad技能包运行时周期/`、`_bmad-output/epics/epic-43-46-目标级工作流周期/`、`_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/`、`_bmad-output/epics/epic-48-TCP网络接口周期/`、`_bmad-output/epics/epic-49-HTTP网页访问周期/`、`_bmad-output/epics/epic-50-网页控制台周期/`（原 `_bmad-output/patches/` 已于 2026-09-15 解散，补丁 spec 已按归属 epic 归位）
- **sprint 状态（v6 历史权威）**：[`_bmad-output/Goal-2-v6/sprint-status.yaml`](../../_bmad-output/Goal-2-v6/sprint-status.yaml)（已归档、只读；覆盖 v6 全部周期与 Epic。v7 起状态真源是 goal 树自带的 `docs/<goal-id>/tickets/` 票树，指针 `docs/current`）
- 技术债登记：活动台账为根目录 `_bmad-output/open-items.md`（「活动（未闭合）条目」节；旧路径 `implementation-artifacts/deferred-work-archive.md` 已于 2026-11-15 并入）；已闭合项按归属 epic 归档到 `_bmad-output/epics/<周期>/deferred-work.md`（原 `_bmad-output/patches/_meta/deferred-work.md` 已于 2026-09-15 退役并删除）
- 已产出 retrospective：`_bmad-output/retrospective-all-cycles.md`（2026-11-15 起为**全周期**历史唯一载体，覆盖截至 Epic 57；Epic 58 起的回顾落在 `Goal-3/tickets/<epic>/` 票树）、`_bmad-output/epics/epic-11-18-MCP集成周期/retrospective-epic-13.md`、`_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/epic-47-声明式工作流与产物治理/retrospective-engine-p5.md`、`_bmad-output/epics/epic-01-10-主线规划周期/epic-01-基础设施与LLM通信/retrospective-p0-tech-debt.md`
