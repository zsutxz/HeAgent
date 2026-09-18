# BMad 技能包运行时周期 · Retrospective（Epic 42）

> 日期：2026-09-18（**补做**：原 `_bmad-output/sprint-status.yaml:421` 标记 `epic-42-retrospective: optional`）
> 范围：`_bmad-output/epics/epic-42-BMad技能包运行时周期/`（Epic 42，5 个 story：`42-1-skill-package-model-resource-safety`、`42-2-skill-catalog-resolution`、`42-3-skill-step-runner`、`42-4-skill-importer`、`42-5-compatibility-regression`；FR1 ~ FR8）
> 动机：把技能从「单个 `SKILL.md` 学习型技能」升级为可安装、可验证的声明式技能包运行时（`drafts/spec-skill-package-runtime.md` Intent 段）

## 一、做了什么

| Story/交付项 | 核心交付 |
|------|----------|
| 42-1（FR3/FR4）· commit `0e84d5f` | `SkillPackage` 入口 / step / references / templates 按需读取 + 包根围栏（`skill_packages.py` +168 行，`tests/test_skill_packages.py` +147 行） |
| 42-2（FR1/FR2）· commit `eca33fc` | catalog 与别名解析（现见 `skill_packages.py:553` `SkillCatalog`、`:649` `SkillResolver`）：`he-*` canonical + `bmad-*` 别名 |
| 42-3（FR5）· commit `6168100` | `SkillRunner` / `SkillStep` / `SkillRunnerState` 单步状态机（`pending`/`waiting_user`/`blocked`/`completed`/`failed`） |
| 42-4（FR6/FR7）· commit `6168100` | 新增 `src/heagent/memory/skill_importer.py`（+224 行）：manifest 映射 + 源哈希 + `.heagent/skills/manifest.lock`（`skill_importer.py:82`） |
| 42-5（FR8）· commit `6168100` | 兼容回归：`SkillStore` CRUD / 关键词匹配 / AgentLoop 注入 + `/goal` 固定路径行为不变；补 `tests/__init__.py` |
| 交付总量与归档 | `6168100` 单提交 8 files、+580/−1（2026-09-01）；当时 spec 与 story 落在 `_bmad-output/implementation-artifacts/`，后由 `ba7ab3e` 归位到周期目录 |
| 竞态转出与命名演进 | `epics.md` NFR 段记「`resolve`→`read_text()` 替换窗口已由特征测试证实」→ Epic 46.1 评估、46.2 以 `os.open` + `O_NOFOLLOW` 加固（`9115a25`）、`c7349a5` 记录边界；角色技能 canonical 后迁至 `bmad-agent-*`（`6b044af`） |

## 二、做对的

1. **职责分层清晰且写下设计理由**——`SkillPackage` 管包根内资源、`SkillCatalog` 管索引、`SkillResolver` 管确定性 ID 解析、导入器管物化与锁定，分层意图写在 `drafts/spec-skill-package-runtime.md` 的 Design Notes 段，便于后续 `WorkflowOrchestrator` 注入。
2. **围栏复用而非另造**——`skill_packages.py:15` 引用 `tools.path_safety.resolve_under_root`，`:494` 用于资源解析；错误类型 `SkillPackageResourceError` 带技能 ID + 相对路径 + 原因，满足 `epics.md` UX-DR4。
3. **冲突与损坏一律显式失败**——缺 `SKILL.md`、别名冲突、源文件缺失、锁损坏都 raise（`skill_importer.py:119,120,174`），`epics.md` 的验收逐条要求「不静默择一」。
4. **竞态不谎报**——把「路径围栏 ≠ OS 安全边界」直接写进 `epics.md` 并转出独立 story，之后由 Epic 46.2 真做加固（`9115a25`），比宣称已修更可审计。

## 三、可改进的

1. **Story 42-3 的交付物已从代码库消失**——`git grep "SkillRunner" -- src tests` 零命中；`git log -S"SkillRunner"` 显示新增于 `6168100`、删除于 `f49c20a`（2026-09-03「…remove dead state machines」，`skill_packages.py` −121 行、`tests/test_skill_packages.py` −79 行）。而 `stories/42-3-skill-step-runner.md` 仍写「已交付 `SkillRunner`」，即 FR-5 的单步运行器在当前 HEAD 上**不存在**。
2. **FR1/FR2 的 catalog/resolver 无生产调用点**——`git grep "SkillCatalog\|SkillResolver"` 只命中 `skill_packages.py` 自身、`skill_importer.py` 内部与 tests；生产侧 `cli_goal.py:56` 只 import `SkillPackage`，`/goal` 与 CLI 未消费 catalog/resolver。
3. **导入器无生产入口**——`import_manifest`（`skill_importer.py:84`）在 `src/` 中没有任何调用者（仅类定义与 `__all__`），FR6/FR7 目前只能靠测试触达。
4. **周期台账被删除**——`deferred-work.md` 由 `0e84d5f` 引入、`ba7ab3e` 删除（`git log --diff-filter=D` 唯一命中）；当前周期目录只剩 `drafts/`、`epics.md`、`stories/`，闭合与转出记录散落在 `epics.md` 与活动台账。

## 四、教训

1. **`status: done` 的判据必须是「当前树里可运行」**——状态机交付两天后即被当死代码删除，story 文档随之失真；交付时若未写清「谁消费它」，清理死代码会静默回退功能。
2. **只被测试触达的能力等于未接线**——库能力（catalog / resolver / importer）与用户可见功能必须分开表述，否则 FR 完成度会被高估。
3. **删除台账要留转出指针**——`ba7ab3e` 删掉周期 `deferred-work.md` 后，Epic 46.1/46.2 的转出链路只能靠 `epics.md` 与 git 历史还原。
4. **命名演进要连带核对兼容层**——`he-*` 从 canonical 降为 legacy 别名（`6b044af`）说明「canonical」是活的约定，需在文档与测试里同步声明主从关系。

## 五、遗留项状态

- 已闭合（story 级）：`stories/42-1..42-5` 五份 frontmatter 均为 `status: done`（各文件第 5 行）。
- 已转出：技能资源 TOCTOU 后续（descriptor-relative open / 目录句柄、可信导入 snapshot、OS sandbox）→ `consolidated-overview.md` §17.4-A1（中）；其中 46.2 的 `O_NOFOLLOW` 加固已由 `9115a25` 落地。
- 名存实亡：FR-5 单步 runner（代码已删，`f49c20a`）——本回顾未核实其在活动台账中的登记状态。
- 跨周期活动项见 `_bmad-output/implementation-artifacts/deferred-work-archive.md`。

## 六、结论

Epic 42 把技能从「单文件学习型技能」推进到「可安装、可验证的技能包」形态，路径围栏、冲突诊断与竞态透明化三点做得扎实，也为 Epic 46 的加固留下了明确入口。它同时留下了最典型的完成度失真：状态机交付两天后被当死代码删除、catalog/resolver/importer 至今没有生产调用点，而 story 文档仍写 `done`。后续同类周期应把「消费方是谁、从哪个入口生效」写进 story 验收，并把「删除能力时的回退校验」纳入清理流程。
