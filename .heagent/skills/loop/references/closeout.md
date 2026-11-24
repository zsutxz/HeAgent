# /loop 契约 · 收口、提交与交接

> 本文件是 `workflow.md` 拆出的章节，与它同属流程真源；章节归属见 `workflow.md` 的「文件地图」。

## epic 收口三审（epic review sweep）

**触发与自动性。** 触发条件 = 该 epic 全部 entry 都达到 `built` / `in-review` / `done`，只认
`tickets.py status <goal 目录>`——**不看「本批是否含最后一条」**（跨会话续跑、上一轮只差收口时，下一轮
一开工就补跑）。满足即**自动开跑：不呈报、不等确认、不是审批门**；这套流程幂等，开工先看
`tickets/<E编号>-<slug>/` 下是否已有 `-review.md`（**单文档三镜头**）与 `-retrospective.md`，
文档里已写过的镜头不重跑。

**三审前先换一次上下文。** epic 全部 entry 达标后，先按「完成即自动提交」提交这批 entry，再按
「上下文交接与续跑」写交接块，然后把三审交给**新会话**开跑（默认注册一次性 cron；用户自己接手时是
`/clear` + `/loop next`）——实现轮的上下文（试错过程、门禁输出、被否掉的方案）对评审只是噪声，带着
它审自己刚写完的代码，会系统性地漏掉「按意图该有而没有」这类缺口。三审链本身在新会话里**连跑到底**
（`R1` → 修 → `R2` → 修 → `R3` → 修 → 回顾 → 提交），中途不再换会话、不呈报、不等确认。

每个 epic 收口**必须做三次审查**，一次一轮、串行推进（上一轮的修复落盘后才开下一轮）：不是三次
同题重复，而是三个不同视角各查一遍。**三镜头写在同一份报告里**（`<E编号>-<slug>-review.md`，每镜头
自带 `## 镜头 N · …` 小节与自己的计数/结论），加上回顾里的记录，epic 才算收口；缺任一镜头即未收口。
（用户 2026-11-24 定：此前拆 `-review-r1/r2/r3.md` 三份的形态作废，历史 epic 的三份保持原样不动。）

- **`R1` 规格与实现对账**（执行角色 `bmad-code-review`）：本 epic 全部改动 vs epic Requirements /
  `Done when` / 各 plan 的 `<frozen-after-approval>` 与 `## Verification`。查「实现是否真的交付了规格」
  与「验证结论是否有证据」，不做风格挑刺。发现按 Critical / High / Medium / Low 分档，逐条给
  `文件:行` + 当前行为 + 正确口径 + 谁守着。
- **`R2` 不变量与守卫反脆弱**（宿主自扫 + 反证）：查安全与不变量（凭据/明文/日志脱敏/错误分类/
  端点判定）、跨产物一致性（`framework.md` 数字与磁盘、活文档口径）、以及**守卫本身是否有牙**——
  至少对一条关键守卫做「注入一处违规 → 必须判红 → 复原 → 必须转绿」的反证（`CleartextCopyTest` /
  `ConfigSurfaceBoundaryTest` / `FrameworkNumbersTest` 这类源码扫描守卫尤其要验）。常量断言恒真、
  锚点随行尾或文案漂移、只看回执不看落盘，都记 Medium 以上。
- **`R3` 三镜头对抗式评审**（技能 `code_review`）：按该技能的三个镜头各跑一遍、独立成段记发现——
  **对抗式**（默认假设改动有问题，找「缺什么」而不是「错什么」，至少 10 条具体发现，提不出要说明理由）、
  **边界追踪**（沿真实调用链追空值/空集合/上限/超时/取消/重试/部分失败/顺序依赖/类型边界，每条问
  「会不会崩、会不会静默错、有没有测试」）、**验证缺口**（对照验收标准找「声称通过但没有证据」：
  只测 happy path、断言实现细节、改了实现没改测试、用覆盖率顶行为验证）。定级用该技能的
  high / medium / low（high = 必须修，等同 Critical），**不得**把 Critical 写成 Warning。
  `R1` 以规格与契约为轴、`R2` 以不变量与守卫为轴、`R3` 以「缺什么 + 边界 + 验证缺口」为轴：
  三者是并列镜头，重叠是信号，**不得**用其中一轮的结论顶替另外两轮。

**`R3` 的调用与 v7 适配**（技能正文按 v6 产物写的，落盘时按下面映射，别照 v6 路径找文件）：

- 调用：`skill_load code_review` → 按它在**本 goal 的 v7 面**执行——评审对象 = 本 epic 全部 entry 的
  plan（含 `## Verification`）+ epic 文件 + 合并 diff，**不采信**实现/测试报告与自验证结论，亲自读
  diff、亲自跑命令核对数字；不得把范围缩到单条 entry；
- 产物：R3 的发现写进**同一份** `<E编号>-<slug>-review.md` 的「镜头三」小节（不是技能原文的
  `review-report.md`），frontmatter 记
  `review_loop_iteration`；延期项落 goal 的 `brief.md`「延期项」段（不是 `deferred-work.md`）；
- **不改** `epics.md` / epic Requirements / plan 的冻结段（v7 下 epic Requirements 同样冻结；`bad_spec`
  发现走 `mark <goal 目录> <ref> blocked` + 回 Step 04/06 重切，不在评审里改规格）；
- 回环上限：同一 epic 内「回到实现重新推导」累计 5 次即停并升级给人；
- 技能不可用（`skill_load code_review` 失败）时按 gap 处置：交接块「未关闭的门」写 `R3 未执行（gap：
  code_review 技能不可用）` + 记 `brief.md`「延期项」，**不**伪造结论、**不**拿 `bmad-code-review`
  顶替 R3（那是 R1 的镜头）；`/loop auto` 下登记完继续收口，不停等人。

**产物与落点。** **一份**报告落 epic 文件夹：`tickets/<E编号>-<slug>/<E编号>-<slug>-review.md`，
结构固定：`## 范围`（改动面 / 判据来源 / 本轮技能名 / 实跑命令表）→ `## 镜头一 · 规格对账` →
`## 镜头二 · 不变量与守卫反脆弱`（含注入反证表）→ `## 镜头三 · 三镜头对抗（契约 / 并发 / 文档）` →
`## 落改清单` → `## 结论`（每镜头各给计数与通过 / 有条件的通过，末尾给总体结论）。
`<E编号>-<slug>-retrospective.md` 必须带 `## 三审记录` 段，逐轮一行写明轮次、结论、发现计数与
落改去向；`progress.md` 决策日志追加一行（三轮结论 + Critical/High 的落改或 `blocked` 处置）。

**发现怎么处置。** Critical / High：当轮落改并重跑受影响门禁，改不动就 `mark <goal 目录> <ref> blocked --blocked <原因>`
按显性失败停；Medium / Low：进延期项（`brief.md`「延期项」）或对应 plan 的评审记录，**不**在本轮扩范围。
三审的发现**一律不得**只写在对话里：至少落到一份报告或 plan，否则视为未审。

**与收口、提交的顺序。** `R1` → 修 → `R2` → 修 → `R3` → 修 → 回顾（`<E编号>-<slug>-retrospective.md`，
含 `## 三审记录`）→ 「完成即自动提交」的判据 → 提交 → 交接 → `tickets.py next` 取**下一个 epic**。
有未落改的 Critical/High 时按显性失败停，不进入提交。

## 完成即自动提交（completion commit）

「做完了」不等于「已落盘」：完成判据一过就**自动 `git commit`**，不再逐轮征询（`CLAUDE.md` 的「提交与汇报」
把 `/loop` 通过完成判据列为唯一允许自动提交的场景，其余场景仍先呈报）。顺序固定为**先提交、再交接、后换会话**，
交接块里的「本轮结论」才对得上 HEAD。

- **触发点**：一批 entry 全部置 `built` 之后（串行时即单条）；epic 收口的提交时点见「epic 收口三审」的
  「与收口、提交的顺序」，`-review.md`（三镜头）或回顾缺一份即不提交，按显性失败停并报告缺口。
- **提交前必过的判据**（缺一项就**不提交**，把缺口写进交接块）：plan `status` 已是 `built`；plan 的
  `## Verification` 有本轮实测命令与结果；`progress.md` 记了结论（失败轮次同样记）；epic 末条另有
  `<E编号>-<slug>-review.md`（三个镜头小节齐备）与带 `## 三审记录` 的
  `<E编号>-<slug>-retrospective.md`；动过 Android 代码时 `:app:testDebugUnitTest` 与 `:app:lintDebug` 通过。
- **提交信息**：中文 Conventional Commit；entry 用 `<type>(<e编号>-s<mm>): <标题>`（scope 小写，如
  `feat(e13-s01): …`），epic 收口用 `<type>(<e编号>): <标题>，<E编号> 收口`；一次提交只装一条 entry 及其配合产物，
  文档与源码同批，不跨 entry 混装；并行批按声明序逐条提交（写集互不相交，可安全逐条 `git add`）。
- **只暂存本批显式文件**：逐条 `git add <path>`，**禁止** `git add -A` / `git add .`；工作树里别人的未提交改动
  只列出、不碰、不 stash；提交后 `git show --stat HEAD` 复核装进的文件与预期一致。
- **不 `git push`**、不改写历史；提交被钩子拦截或冲突时按显性失败处理：如实报告并停，不带病交接。
- **用户当轮说了「先呈报 / 别提交」**：以用户为准，本轮不提交，把待提交清单写进交接块留给下一轮。

## 上下文交接与续跑（context handoff）

一条 entry 的实现细节（改过的文件、试错过程、门禁输出）只对那条 entry 有用；留在对话里，后面的
entry 反而读不到真正需要的上下文。所以**完成一批 entry（串行时即一条）与完成一个 epic 都是交接点，不是停止点**：
plan 置 `built`（或 epic 收口回顾落盘）之后，先按「完成即自动提交」提交，再写交接块，再继续。

**交接块**：覆盖写活动 goal 的 `progress.md` 的 `## 交接块（下一轮入口）`（不是追加，历史留决策日志），
五项缺一不可：

- `- 下一条：<ref> <E编号>-S<mm>（<epic slug>）`——取 `tickets.py next` 的下一批（串行时即 `ready_to_start` 首行）；
  没有可开工的 entry 写 `- 下一条：none（转 Step 08）`；
- `- 票树实测：counts {…} / problems 空 / longest_remaining_chain …`——现测抄录，不凭记忆；
- `- 必读：<plan 路径> · <epic 文件> · <epic 回顾>`——下一轮真正要读的文件清单；
- `- 未关闭的门：<审批门 / checkpoint / 待用户裁决项>`——没有就写 `无`；
- `- 本轮结论：<一两行>`——只留影响后续 entry 的事实（新增守卫、接口改动、门禁新基线），不复述过程。

**交接后一律换新会话（默认自动）**：agent **不能**调用客户端的 `/clear`（那是输入框里的斜杠命令，
工具集里没有等价能力），所以「清空 context」在本契约里的落法是**注册一次性 cron job**——job 触发即新会话，
等价于 clear 后自动开工：

- **换会话的时点**：每批 entry（串行时即每条）完成之后，以及每个 epic **开跑三审之前**；三审链内不换会话
  （理由见「epic 收口三审」的「三审前先换一次上下文」）。
- **默认**（`next` / `run` / `auto` 下的上述两个时点）：写完交接块立刻注册一次性 cron，
  `recurring: false`、`schedule` 用 `* * * * *`（下一个整分钟触发），prompt 只写
  「读 `docs/current` 指向 goal 的 `## 交接块` 与 `tickets.py next`，继续 Step 07」，不带本次对话内容；
  注册完即收官本轮，回复里写明 job 与「下一轮入口」。
- **cron 不做的事（如实说）**：它只把下一轮交给新的执行入口，**不保证清空当前这轮对话的 context**；
  真正的 context 清零只有两条——用户在输入框敲 `/clear`，或另开新会话。所以注册 cron 之后，
  回复里必须同时给出「想立刻清零就 `/clear` + `/loop next`，并先删掉这个 job」。
- **注册前先 `cron_list`**：已有同 prompt 的 loop job 就复用、不重复注册；同一条交接只留一个 job。
- **不该注册**（这些门之后没人接手只会空转，按人工续跑收官，并删掉遗留 loop job）：下一条是
  `hitl` / `plan_checkpoint` / `done_checkpoint`、Step 08 放行前、显性失败、需要用户裁决、Step 02 交互轮待用户回复。
- **用户接手**（说「我来 / 先别自动」）：写完交接块收官，提示「新会话继续：`/loop next`」；
  用户自己 `/clear` + `/loop next` 与 cron 等价——此时先 `cron_remove` 已注册的 loop job，
  避免两条会话同时推进（一次只跑一批，见「并行纪律」）。

**纪律**：交接块是唯一跨会话载体（不依赖上一会话记忆，也不得为保住上下文而不写）；交接不改变状态机
（不提前写 `done`、不跳过 plan 推进与 `## Verification` 实测）；「下一条」与 `tickets.py next` 现测不一致时
以脚本为准并就地改正；每轮开工先按 `next` 校准 `progress.md` 头部的「当前步骤」行。
