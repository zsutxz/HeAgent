# /loop 契约 · epic 内并行批

> 本文件是 `workflow.md` 拆出的章节，与它同属流程真源；章节归属见 `workflow.md` 的「文件地图」。

## epic 内并行批（parallel batch）

同 epic 内互不冲突的 entry 可以**成批并行**：宿主一次开多个子会话跑实现，批末由宿主**串行**收口门禁、
`mark`、提交与交接。**默认并行**：声明齐全且七条件全过的相邻 entry 一律成批并行；串行是 fail-closed
兜底，只落在声明缺失或条件不过的那几条上，不因个别条目拖慢整 epic。

**声明（Step 06 写，义务）。** 并行是默认形态，每条 entry 都默认声明两个键（这是组批门控的输入）：

- `parallel_group`：非空组名，同组条目才可以成批；缺省 = 该条单条串行兜底，须在 plan 写明不能并行的
  原因（带门 / 依赖并发中的 entry / 单条已满负荷）；
- `write_set`：该 entry 会改的**全部**仓库相对路径（新建文件、测试文件、fixture 都要列），必须完备。

`tickets.py` 不读这两个键（不进 `status` / `find`），它们是本契约的门控输入：宿主直接读该 epic 的
`tickets.toml` 判定，不自行发明第三处声明。

**七条件**（全过才成批；成员按 `next` 的 `ready_to_start` 表序取相邻条目）。

- 同 epic、`parallel_group` 相同且非空——跨 epic 不成批（epic 是 `after` 与收口的边界）；
- 成员 `write_set` 非空、两两不相交（派生产物见「批级共享写集」）；
- 成员的 `after` 已全部交付，且**不依赖批内其他成员**（依赖并发中的 entry 不可证安全）；
- 成员都没有 `hitl` / `plan_checkpoint` / `done_checkpoint`——带门的一律单条串行走；
- 成员都没有 `unknown`、未裁决的核心 `Ask First` 与竞争方案；
- 批大小 ≤ 3（默认上限；用户点名更多最多 5，写集仍须两两不相交）；
- 宿主能让门禁串行跑：本仓源码树、容器 workspace 与设备腿都只有一份，**并行只发生在实现阶段**；
  做不到就退回串行。

**执行形态。**

1. 宿主用 `task_parallel` 一次开 N 个子会话，每条正文与该条单跑时逐字相同（entry 全文、epic 文件
   全文、`find` 的 plan 路径、`after` 所指 plan 的 Code Map / Design Notes / Plan Change Log），
   另加一句「本批并行、只准写 `write_set` 内的路径」；
2. 子会话返回后逐条核对产物；Step 07 实现子会话按各自 `write_set` 写盘，宿主批末跑一次
   `git status --porcelain` 做**写集审计**：出现「本批写集 ∪ 宿主自写产物」之外的 tracked 改动，
   该条判失败并**撤销本 epic 的并行授权**（此后一直串行到 epic 收口）；untracked 只记警告（夹具与新
   产物本就是未跟踪写入）；
3. 实现全部落盘后宿主**串行**跑门禁：先逐条跑各自 `## Verification`（批内共享的仓库四件套只跑一次），
   结果按 entry 分行写进 `progress.md` 与各自 plan；
4. 门禁不过只回退该条：`git checkout -- <该条 write_set 内的 tracked 路径>` 并删掉它新建的文件，其余
   条照常收口；同一条连续两轮仍失败即 `mark <goal 目录> <ref> blocked`，按显性失败处理；
5. 逐条 `mark <status>`（各 plan 是不同文件，互不干扰），再按声明序**逐条提交**：每次 `git add` 只装该
   条的 `write_set` 与 plan，禁 `-A` / `.`。

**批级共享写集。** 派生文档与守卫基线天然被多条 entry 牵连（`docs/aihome-client/framework.md` 的模块
规模表、`ChatViewModelSizeTest` 上限、注释与配色守卫）：它们**不算写集相交**，而是由宿主在批末按落盘
后的实测数字统一重算一次，作为批收尾提交（`docs(<e编号>): 批内派生文档重算`），实测值记 `progress.md`。

**批是一次 checkpoint 单元。** 带门成员不进批（七条件第 4 条），所以批内没有逐条等人的门；人工确认
按批一次，不按条拆。**交接点也从「每条 entry」改为「每批」**：批内不写交接块、不注册 cron；批末
（全部提交后）按「上下文交接与续跑」写一次，`- 本轮结论` 记整批，`- 下一条` 取下一批。
