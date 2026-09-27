# 网页控制台周期 · Retrospective（Epic 50）

> 日期：2026-09-27（**补做**：交付时 `epic-50-retrospective` 为 `optional`；按 Epic 48（2026-09-23）先例，在收口时一并补做并补登 `sprint-status.yaml`）
> 范围：`_bmad-output/epics/epic-50-网页控制台周期/`（8 个 story：`50-1-workspace-first-class`、`50-2-project-registry-api`、`50-3-session-persistence-api`、`50-4-config-sources-readonly-api`、`50-5-config-write-channel`、`50-6-console-ui`、`50-7-security-acceptance-docs`、`50-8-console-ux-refinement`）
> 动机：把 Epic 49 的「一个进程 = 一个目录 = 一次性聊天页」升级为**本机控制台**——多项目登记与切换、会话持久化、配置有效值/来源可视化，以及闸门约束下的项目 `.env` 保真写入（`brief.md`）。

## 一、做了什么

| Story / 交付项 | 核心交付（commit） |
|---|---|
| 规划（`5878e92` → `33adba0`） | `brief.md` + `ARCHITECTURE-SPINE.md` + `epics.md` + 7 份 story 同日建立；对抗式规划评审（三镜头 12 条）当场把 8 处规划不准确校正回脊柱（含 12 个未分类配置键、1 处白名单/排除模式冲突、1 处不存在的测试文件） |
| 50-1 / 50-2 · `7ef2c92` | `pub/workspace.py`（`WorkspacePaths` 单一来源）+ 各 store 改为按工作区派生路径 + `path_safety.build_internal_state_dirs()` 从同源收紧；项目注册表与项目 API（登记 / 重命名 / 移除保留数据 / 目录失效标记 / 损坏注册表 fail-soft） |
| 50-3 · `af6850a` | 会话持久化与会话 API、运行绑定会话、会话 id 路径遍历与保留设备名拒绝、在途运行约束 |
| 50-4 · `db861c8` + `13a14b0` | 四层来源求解（system_env / project_env / global_env / default）+ 只读配置面板；凭证只回 `configured + 定长掩码`；未知键单列 |
| 50-5 · `6f448aa` | 配置写入通道：白名单（fail-closed）+ `.env` 行级保真写（EOL/BOM/注释逐字节）+ 写前备份 + 指纹冲突检测 + 审计（不含值）+ 回读校验；`HTTP_CONSOLE_WRITE_ENABLED` 默认关且**网页无法自我开启** |
| 50-6 · `f5f4c3f` | 两栏 UI + 独立设置面板 + 来源徽标 + 危险项二次确认 + 常驻安全声明；真实浏览器（CDP）验收清单 |
| 50-7 · `1ca29cf` | 安全检查收口（凭证零回传遍历、跨项目不串味）+ brief §9 逐条验收 + `frame.md` 4.18 与 `HTTP_CONSOLE_*` 文档同步 |
| 50-8 · `cc717f8` + `bb436b8` | 收口**后**的体验优化轮（用户实测驱动）：会话列表截断与展开、原生目录选择（`cli/dialogs.py` + `POST /api/dialogs/pick-directory`）、项目与会话同栏一列、设置面板瘦身、读取类工具只显示文件名 |
| 评审与台账 | 四轮收口评审 + 3 份验收（`reviews.md`，2026-09-26 由 8 份文档合并）；`Z-D13` / `Z-D14` / `Z-D15` 三条派生缺口当日闭合并回填 `deferred-work.md` |

## 二、做对的

1. **规划阶段就把「对抗式评审」前置**——12 条规划评审里有 8 处是文档与代码不符（配置键计数、白名单与排除模式冲突、不存在的测试文件），全部在写码前校正；`ARCHITECTURE-SPINE.md` §14 记了逐条证据。
2. **判据先于修复**：每一轮评审的修复都配**负向验证**（把修复回退 → 判据必须精确变红）。50-8 的变异体从 17 条加到 23 条，全部精确红后按 sha256 逐字节还原；真浏览器清单 23/23。
3. **桩保真度被当成一等公民**：`Z-D15`（首页遮罩被作者级 `display` 压过 `hidden`，`node.click()` 又绕过命中测试）暴露后，验收清单给关键行加了**几何判据**（`getBoundingClientRect` + `elementFromPoint`），并补了静态守卫 `[hidden] { display: none !important }`。
4. **配置面单一事实源**：划分表（白名单 ∪ 排除 = 全部字段）、上界表（`RESOURCE_CEILINGS`）、面板取值提示全部由后端常量派生，前端**不硬编码任何键名与边界**——这条被「21 键上界」与面板用例同一常量表遍历钉死。
5. **冻结边界写得住**：不改 `Settings` 字段定义（保持既有配置文件可加载）、守卫只作用于写通道与面板、`HTTP_CONSOLE_*` 不可由网页开启——每条都在 story 里说明了「为什么不那样做」。

## 三、可改进的

1. **收口后没有把「主干质量门」当成 Epic 的持续契约**。2026-09-24 收口放行，2026-09-27 的三次改动（`eefca06` 端口顺延 / `25812d5` 内存预算 / `5f4324b` 诊断显示）分别打破 Epic 50 建立的三条判据 —— `test_partition_is_complete`、`test_groups_are_emitted_once_and_cover_every_item`（两条未登记的新配置键）与 `test_settings_panel_is_compact_without_losing_reasons`（诊断条数口径变了）—— 且**无人发现**，直到 2026-09-27 的独立复核（本次）。
2. **`eefca06` 的端口自动查找默认开启且改写了显式端口**，直接破坏 Epic 49 Story 49-2 的「绑定失败必须显性」契约：占用端口时服务照常起来，`test_startup_failure_is_reported_without_a_listening_banner` 因此**永久 hang**，全量套件跑不完 —— 于是「全量绿」这条收口判据**在事实上失效**（跑不完 ≠ 通过），而 `reviews.md` 里 3144 passed 的数字仍被当作有效证据引用。
3. **测试桩与后端形状不一致**：`tests/js/app_probe.js` 的 `configPayload` 同时给出 `exists: true` 与 `notes: ["project_env_missing"]`（后端只在文件缺失时给这条 note），自相矛盾的桩让「信息性 note 不计入告警条数」这一分级长期没有判据。
4. **新增 `Settings` 字段的「三处同步」仍靠人肉**（catalog 划分 / `RESOURCE_CEILINGS` 上界 / `.env.example`）。本轮两条新键三处全漏，直到断言变红才暴露。

## 四、教训

1. **「跑不完」与「跑得过」必须在流程上区分**：门禁要么给单测超时，要么把整轮跑不完当失败；本轮一次 25 分钟无输出的等待几乎被误读成「慢」。
2. **契约变更与便利功能冲突时，默认值必须站在契约一边**：端口顺延本身是好功能，但默认必须关闭、且永不改写**显式**端口 —— 现在 `HTTP_PORT_AUTO_FIND_ATTEMPTS` 默认 `0`，开启后也只对未显式传 `--port` 的路径生效。
3. **桩是测试的一半**：桩自相矛盾时判据会永久假绿；「信息性 note」这类分级必须同时钉「不进告警」与「说明仍可见」两侧。
4. **新字段的登记是可执行断言，不是文档义务**：本轮正是那三条断言（划分完备、上界 ≥10× 默认、`.env.example` 覆盖）把漏登记抓出来的 —— 加字段时应当**主动跑**它们，而不是等红灯。

## 五、遗留项状态（2026-09-27 复核）

- **已闭合**：50-1 ~ 50-8 全部 `done`（`sprint-status.yaml` 与 8 个 story frontmatter 一致）；`epic-50: done`；`epic-50-retrospective: done`（本文件）。
- **本轮顺手闭合的主干回归**（收口后破坏 Epic 50 判据的三次改动）：`edc7992` / `d6d6b4a` / `ab77bf8` / `d7f8c75` / `13c6d2b` 五个提交，收口门实测 **pytest 3089 passed / 覆盖率 91.92%**、`ruff check` / `ruff format --check` / `mypy`（本机 + `--platform linux`）全绿。
- **仍开（活动台账 A8~A19）**：跨项目并发无全局上限（A8）、运行时归因族（A9）、控制台端点阻塞 I/O（A10）、非回环运行姿态 + cron 跨会话后置执行（A11，`blocked`）、浏览器验收不进 CI（A12）、高影响键差异化确认（A13）、写通道四类低危残余（A14）、网页请求可拉起宿主 GUI 进程（A15）、原生弹窗不可自动化（A16）、`Error:` 前缀判据（A17，`blocked`）、会话总数硬上限少报（A18，`blocked`）、目录选择端点默认开（A19，`blocked`）。
- **已闭合的周期内缺口**：`Z-D13`（写通道可设无界资源旋钮 → 21 键上界）、`Z-D14`（审计无回收 → 行级裁剪 500 条）、`Z-D15`（首页遮罩关不掉 → `[hidden]` 守卫 + 命中测试判据）。
- **立场不变**：网页入口**无认证 / 无 TLS / 不是安全边界**，须 OS 级沙箱兜底。

## 六、结论

Epic 50 把「网页入口」从一次性聊天页做成了本机控制台，最扎实的部分不是功能数量而是**判据的可执行性**：划分完备性、上界 ≥10× 默认、凭证零回传遍历、跨项目不串味、真浏览器几何判据，全部有断言与变异体验证支撑。它也因此成为本项目里**判据密度最高**的一个周期。

短板在收口**之后**：一个周期的契约不会因为 `done` 而自动持续成立 —— 收口后三天内的三次改动就打破了两条不变量、并让全量门从「绿」退化成「跑不完」，而当时的证据链（`reviews.md` 的通过数字）对此毫无感知。**下一轮同类周期的 Definition of Done 应加两条**：① 跨周期改动若触碰既有不变量，必须跑对应断言（不是只跑自己新增的测试）；② 门禁必须显式失败于「跑不完」，避免把超时读成宽容。
