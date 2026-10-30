---
name: google-skills
source: https://github.com/google/skills
accessed: 2026-10-28
heat: 21,619 stars / 1,834 forks（2026-10-28 GitHub API 快照；创建 2026-03-31，最近 push 2026-10-27）
first_study: 2026-10-28
last_review: 2026-10-28
---

# google/skills

## 核心观点与价值

本卡最重要的一节，综合报告主要从这里引用：

1. **负向触发写邻接指名**（"Don't use for X (use y-skill)"）。为何成立：负例不仅抑制误触发，还把正确路由候选塞进同一句里，agent 无需二次检索；前提是库内存在明确分工的兄弟技能。单技能场景可退化为「不适用于 X 场景」。
2. **命名前缀约定 = 常驻路由表；活目录路由器**。库规模上百后，常驻层只装前缀映射（`gke-*`、`<product>-basics`），全量发现交给运行时抓取 generated index.json——命名规范从「可读性约定」升级为「检索机制」，技能本体常驻成本趋零。前提：目录发布渠道可靠 + 路由技能自带取数验证（见下条）；代价：多一次网络依赖。
3. **取数验证教义**（finding-google-skills 与 retrieving-developer-knowledge 共有）："A tool call that returns without raising is not a success"——响应必须过 parse/内容校验才算成功；证书失败为终态且明令禁任何绕过（`curl -k`/`-SkipCertificateCheck`/`ServicePointManager` 逐一点名）；429 降级到廉价端点而非回退记忆；反幻觉收束："Presenting recalled documentation as a retrieved result is the worst available outcome, because nothing in the reply distinguishes it from a real lookup." 适用于一切要「替 agent 拿事实」的技能。
4. **建议而非执行的安全边界**：对生产资源操作，把「只读诊断 + 人执行修复」写成开头硬约束而非结尾提醒，配可数升级条件与固定升级动作。迁移前提：领域存在人类执行者；全自动场景需换成 plan-validate-execute。
5. **技能侧遥测打标 + opt-out**：内联环境变量/User-Agent token 让「哪条技能产生了哪些 API 调用」可归因，为技能维护提供运营数据；关键配套是豁免生成物（不污染用户代码）与用户退出权。写法上把每个「不能怎么做」都配机制性理由（持久化会错标、改写 token 会断解析）。
6. **CI 自愈 issue**：链接检查器不做人肉巡检，自动探测修复候选并把「改成哪个 URL」写进 issue；人只确认。配套声明「以内部源为准」避免镜像仓库与上游编辑权冲突。
7. **生成物防御标记**：generated 文件首行声明 "Do not edit it by hand"、README 用 BEGIN/END 标记圈出生成区——把「人写/机器生成」边界写进文件本身，防手改被覆盖。
8. **封闭作者制的取舍**：官方库以放弃外部 PR 换取内部验证一致性，用 issue + fork remix 保留社区出口。与 superpowers/ECC 的开放贡献模式互为参照：作者群体越分散，越需要 ECC 式的遵从性测量；作者越集中，越可以省。

## 整体定位

Google 官方 Agent Skills 库（README 自述："Agent Skills for Google products and technologies"，采用 agentskills.io 开放格式）。解决的具体问题：让 coding agent 在使用 Google 产品（Google Cloud 为主，兼及 Ads/Analytics/Identity/开发者平台）时，用**有据可查、随文档更新的官方知识**替代模型记忆里可能过时的 API 模式与命令。目标用户是任意 Agent Skills 兼容 harness（Claude Code、Codex、Antigravity CLI、skills.sh 安装器）的使用者。与既有案例的根本差异：这是**第二个生态（Google）的官方库**，其知识架构是「技能不装知识、装取数协议」。

## 体系结构与组织机制

**1. 三层分发架构（联邦式枢纽，区别于 anthropics/skills 的单体库）。**

- **聚合枢纽（本仓库）**：`skills/` 按 5 个产品域组织，共 176 个独立 skill——cloud 155、ads 14、analytics 2、developers 3、identity 2（git tree 逐目录计数）；另加插件捆绑副本 5 份，全库 181 个 `SKILL.md`。机器注册表 `index.json`（约 119 KB）由生成器产出（文件首字段原文："This file is generated. Do not edit it by hand."），176 条 entry，每条 `{name, description, entrypoint}`，entrypoint 指向 raw.githubusercontent 的 SKILL.md 直链。README 的技能列表夹在 `<!-- BEGIN SKILLS -->`/`<!-- END SKILLS -->` 标记间自动生成。
- **联邦插件层**：`.claude-plugin/marketplace.json` 与 `.agents/plugins/marketplace.json` 双清单并存。marketplace.json 列 16 个插件，**除 1 个第一方插件（`google-cloud-developer`，source 指向仓库内 `./plugins/cloud/google-cloud-developer`）外，15 个全部指回 `GoogleCloudPlatform/*` 独立仓库并按版本 ref 钉死**（如 `alloydb-plugin@0.2.0`、`google-cloud-storage-plugin@3.0.1`）；`.gitmodules` 同步 16 个 submodule 且 branch 字段钉版。即：产品团队在自己的仓库里维护自己的技能，中央库只做**版本化聚合与发现**。
- **兄弟生态**：README "Additional Google skills" 一节链接 `android/skills`、`dart-lang/skills`、`flutter/skills`、`firebase/agent-skills`、`googlemaps/agent-skills` 等——各产品线自建技能库，本仓库是旗舰入口而非唯一来源。

**2. 安装与更新。** README 提供 `npx skills add google/skills`（skills.sh 安装器，运行时选择 skill 子集、目标 agent 与 project/global scope）与 `npx skills update`（可选清除 obsolete skill）；插件路径按 harness 分流：Claude Code `claude plugin marketplace add google/skills`、Codex 插件市场、Antigravity `agy plugin install <plugin-path>`。同一份技能资产面向多 harness 分发，靠的是清单层适配（`.claude-plugin/`、`.agents/`、`gemini-extension.json`、`.codex-plugin/` 四套 manifest 并存于第一方插件目录）而非技能本体改写。

**3. 质量控制：封闭作者制 + CI 自愈。**

- `CONTRIBUTING.md` 原文："**we are not accepting external pull requests or code contributions.** … all Agent Skills must undergo a rigorous internal verification and approval process by Google teams." 外部只有 issue 反馈与 fork remix 两条路；作者指南（内部 "Agent Skills Program" 文档）不公开。
- `.github/workflows/link-checker.yml`（约 9 KB）：每周一 cron 跑 lychee 扫全部 md，`fail: false` 不阻断；随后的 Python 自动分诊脚本对 DevSite 404 **探测修复候选**（试 `.md.txt` 端点、删中间路径段、末两段以 `.` 连接、向上遍历祖先导航页），把「Update to `<具体URL>` (HTTP 200)」级建议写进固定 issue（`DEFAULT_ISSUE_NUMBER: '240'`），并在 issue 头部声明 "All broken links need to be updated in the **internal source of truth**"——镜像仓库不直接改稿。CI 的角色不是门禁而是**修复建议生成器**。
- `skills/developers/retrieving-developer-knowledge/references/supported-domains.md` 内嵌 `<!-- LINT.IfChange -->` / `<!-- LINT.ThenChange(//depot/google3/third_party/devsite/.../corpus-reference.md) -->` 同步标记——技能文件与 Google 内部 google3 源树双向挂钩的直接证据。

**4. 知识架构（本对象最独特处）：技能不内联产品知识，装的是取数协议。** 三个组件分工：

- `skills/developers/retrieving-developer-knowledge/SKILL.md`（8.2 KB）：对接 Developer Knowledge MCP server（`answer_query`/`search_documents`/`get_documents`）或 REST fallback（`developerknowledge.googleapis.com/v1`）。关键条款："A declared server is not always a connected server"（声明≠可用，工具缺失属正常，走 REST）；"Official documentation conventions have absolute precedence over memorized defaults"；429 时立即降级 search 端点而非回退记忆。
- `skills/developers/finding-google-skills/SKILL.md`（6.8 KB，与插件副本字节同大小 6,842 B）：运行时抓取 `index.json` 的**活目录路由器**——"The catalog lives outside this file and is fetched on demand, so loading this skill costs almost nothing until a lookup actually happens"。按 description 做路由匹配、短名单 ≤3、只 fetch 命中项。
- `plugins/cloud/google-cloud-developer/rules/google-cloud-discovery.md`（`trigger: always_on` 的常驻规则层）：**把命名约定当路由表**——`gke-*`、`agent-platform-*`、`google-cloud-solution-*`、`<product>-basics` 等前缀映射到主题域，让常驻文本不用罗列 155 个技能即可指引发现；并立教义："Fetching is the normal path and installs nothing… gone when the session ends. Prefer it."（fetch 优先于 install，会话结束即消失）；"Never infer a skill's contents from its name."

**5. 描述契约：负向边界 + 邻接指名是全库 house style。** 逐条 census（index.json 176 条描述）：**128 条（73%）含 "Don't use…" 类负向触发**，且典型写法是把替代技能指名道姓写进负向边界（样本条目 agent-platform-alert-configuration："Don't use for standard infrastructure monitoring unrelated to AI agents…"；gke-node-notready 见解剖样本）。粒度策略：任务级窄技能——仅 GKE troubleshooting 就拆成 12 个单一症状技能（`gke-ai-troubleshooting-tpu-vbar-oom`、`gke-node-notready` 等，目录名即症状）。

**6. 使用度遥测协议（此前五轮案例均未出现的机制）。** cloud 域技能普遍携带 `references/attribution.md`（MUST READ），要求每条直接执行的 `gcloud` 命令内联 `CLOUDSDK_METRICS_REQUEST_ATTRIBUTION="agent-skills/1.0 (skill:gke-node-notready)"`、HTTP/MCP 请求 User-Agent 追加同一 token——技能侧自报身份，形成「哪条技能驱动了哪些 API 用量」的运营观测闭环。详见解剖样本。

## 解剖样本：gke-node-notready

**定位**：GKE 节点 NotReady/Unknown 状态的系统性诊断技能。`SKILL.md` 12,254 B，自包含 + 仅 1 个引用文件 `references/attribution.md`（1,891 B）。

**触发边界**：description 三段式——做什么（"Diagnoses GKE nodes reporting NotReady or Unknown status by inspecting node conditions, events, kubelet/containerd logs…"）、正向触发（"Use when nodes show NotReady, when the kubelet stops posting node status…"）、负向边界带邻接指名（"**Don't use for pod-level application failures (use gke-workload-troubleshooting), autoscaler scale-up/scale-down decisions (use gke-cluster-autoscaler), or non-GKE compute.**"）——负例直接把流量导给兄弟技能，这是 155 个细粒度技能互不误触发的配合机制。

**任务契约（文件明确写出）**：

- 开头正文即两条硬约束："This skill operates **non-interactively** and enforces a **read-only diagnostics boundary**: gather evidence first, then propose a fix… for a human to apply. **Never** mutate the cluster, drain, delete, or recreate nodes automatically."——建议者而非执行者。
- `[!IMPORTANT]` 块：先排除**预期内**瞬态 NotReady（新置备/升级/修复/cordon/缩容中的节点），"Only treat it as a fault if it persists beyond the expected window"——误报前置闸。
- Attribution 契约："**MUST READ**: Before executing any `gcloud`, REST API, or MCP command, you MUST read [Usage Attribution]"。

**机制拆解**：

1. **Step 0 参数提取与降级路径**：`project_id`/`cluster_name`/`cluster_location`/`node_name` 从 prompt、`SETTINGS.md`、`kubectl config current-context`、`gcloud config get-value project` 非交互获取；凭据失败（沙箱/离线）时"present the exact diagnostic commands for a human to run and continue the analysis from the reported symptoms"——诊断不因环境残缺而中止，只降级为纸面分析。时间窗显式计算（issue_time ±30m）。
2. **证据带深链**：每步日志查询同时给出 Logs Explorer deep link 的完整 URL 模板（`logs/query;query={URL_ENCODED_QUERY};timeRange={start}%2F{end}?project=...`，细到 `/` 编码为 `%2F`、滚动窗口用 `;duration=PT1H`）——人可以一键打开 agent 所依据的原始证据。
3. **症状→根因决策表（Step 3）**：9 行签名表（`containerd.sock` 连接错误→运行时宕；`Got sys oom event`→节点级 OOM；`PLEG is not healthy`→过载；`TaskHung`→磁盘 I/O；`kube-node-lease` 租约终止→flapping…），每行映射根因与分支号（Step 4a–4f）。分支内各配确认命令与**只提出不执行**的修复建议。
4. **可数升级条件（Step 5）**：命中其一即停——(a) 日志不可用（给出硬事实：`_Default` 桶默认 30 天保留，超期"permanently deleted"；`_Required` 桶 400 天）；(b) 签名不在决策表内且分支排查后仍未定位。升级动作固定三件事：明说局限、汇总已取证据、转 GKE support——"Do **not** keep proposing further self-service investigation, and do **not** fabricate a diagnosis when the evidence is missing."
5. **Attribution 遥测细节**（attribution.md）：环境变量**逐命令内联**而非 `gcloud config set`（明示原因：shell 状态不跨命令持久，持久化会"mislabel unrelated usage"）；User-Agent **追加不覆盖**（"the collection pipeline parses the `agent-skills/<version>` and `skill:<name>` tokens, so any rewording breaks attribution"）；**严格豁免生成物**（"Do NOT include this tracking prefix in generated scripts, Terraform templates, or code provided to the user"）；**用户 opt-out 即摘除**。
6. **References 溯源段**：列 4 条公开文档链接，逐条注明贡献了什么（"node conditions and the kubelet / PLEG / system-OOM … signatures and their remediations"）——技能内容对官方文档的可追溯声明。

**设计本质（研究者解释，区别于文件事实）**：该技能针对的诊断场景三类失真——①自行变更生产资源（用只读边界+人 apply 堵）；②拿记忆里的过时模式当根因（用决策表把「先取证后归因」编译成顺序路径，References 段保证知识可溯源）；③证据不足时编造诊断（用可数升级条件+「三件事」把「何时停」从模型自觉变成判据）。与第三轮 superpowers `systematic-debugging` 同属纪律型技能，但增量的落点不同：superpowers 管的是「先理解再动手」的通用纪律，本技能把纪律**预编译成产品特定的取证 SQL/URL/签名表**——纪律不再依赖模型现场推理。成立前提：有人类在环执行修复、Cloud Logging/Monitoring 可用；代价是覆盖窄（需要 155 个兄弟技能+路由层配合）与 deep-link/查询模板对 Google Cloud URL 格式的强绑定（由每周 link-checker 兜底失效）。

## 未读与局限

- 全程静态阅读，未运行任何技能：attribution 打标是否如描述生效、Developer Knowledge MCP/REST 可用性、路由技能实际触发率均未实测。
- 深读 3 个技能（gke-node-notready 全文、finding-google-skills 全文、retrieving-developer-knowledge 全文）+ 2 个引用文件（attribution.md、supported-domains.md、api-fallback.md 前半）；155 个 cloud 技能中其余 152 个仅目录/大小勘察；`bigquery-optimization` 的 9 个 references、插件的 `gcloud`（15 KB）/`google-cloud-recipe-auth`/`google-cloud-recipe-onboarding` SKILL.md、`.agents/plugins/marketplace.json`（与 `.claude-plugin` 版差异）、`gemini-extension.json`、`mcp.json`、link-checker.yml 后半段（约 4.5 KB 截断）均未读。
- 首轮抓取中 CONTRIBUTING.md 与 retrieving-developer-knowledge SKILL.md 各有一次空返回，重试成功（raw.githubusercontent 直连瞬断，未用镜像）；引文以重试成功版本为准。
- `index.json` 176 条目与全库 181 个 SKILL.md 的差值（5）为插件捆绑副本，其中仅 2 个经字节大小核对与 skills/ 下同名技能一致，未逐一 diff。
- 热度与结构均为 2026-10-28 单日快照；库处于活跃迭代期（前一日仍有 push），数据会漂移。
- 内部「Agent Skills Program」作者指南不公开，Google 内部验证流程只能从 CONTRIBUTING 的只言片语推断，未读到一手规范。
