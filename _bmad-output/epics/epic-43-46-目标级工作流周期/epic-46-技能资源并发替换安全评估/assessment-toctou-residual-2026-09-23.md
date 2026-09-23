# 技能资源 TOCTOU 残余 · 评估更新（2026-09-23）

> 上游评估：`spec-skill-resource-toctou-assessment.md`（Epic 46 Story 46.1，决策「assessment only；
> 不做跨平台运行时改动」）+ Story 46.2 的 `O_NOFOLLOW` 加固。
> 本文件是台账活动条目「技能资源 TOCTOU 残余」的复核与更新，**不含代码改动**
> （实施需按 Story 46.1 的 Ask First 单独授权）。

## 一、结论摘要

1. **竞态类残余无法在跨平台、无平台专用依赖的前提下闭合**：`open_text_under_root` 的 `O_NOFOLLOW`
   只覆盖**最终路径组件**，中间目录替换在 POSIX/Windows 上都仍是窗口；逐组件 `openat`+`O_PATH`
   只在 Linux 可用（Windows 无对应原语），且仍是「收窄」而非边界 —— 维持 Story 46.1 决策。
2. **复核发现一处非竞态、可闭合的真实缺口**（新）：**包资源内容没有任何完整性凭据**。
   `manifest.lock` 只钉 entry 文件（`SKILL.md`）的 `source_hash`，`_materialize` 却 `copytree` 复制
   **整棵包树**（`references/` / `templates/` / `assets/` / `scripts/` 全在内），且运行期**从不读**该 lock
   ⇒ 这些文本（会进入 LLM 上下文）被替换后无从察觉。附带效应是「已锁定」给人一种**超出实际**的完整感。
3. **现成先例就在隔壁一层**：`_bmad/render/*/manifest.json` + `render_skill.py::_verify_existing`
   已经实现了「逐文件 sha256 + 漂移即显性失败」；而真正把资源读进上下文的
   `SkillPackage` / `SkillStore` 读路径**不做任何校验**。修法因此可以很小、且跨平台。
4. 触发条件与严重度：需要**本地写权限**才能替换资源（与 symlink/hardlink 攻击同一前置）；严重度
   **中**（数据外发方向是「把非预期文件内容注入模型上下文」，与 path deny 的意图直接冲突）。

## 二、现状核实（逐条带位置）

| # | 事实 | 位置 / 证据 |
|---|------|-------------|
| 1 | 唯一安全读入口：围栏（`resolve` + `is_relative_to(root)`）→ `O_NOFOLLOW`（平台支持时）→ `fstat` 普通文件校验 → 解码 | `src/heagent/tools/path_safety.py::open_text_under_root`（docstring 自述 defense-in-depth，非边界） |
| 2 | 非竞态逃逸路径已被围栏堵住：`resolve` 会跟随符号链接，故包内 symlink 指向包外会被 `is_relative_to` 拒绝 | 同上：`resolved.is_relative_to(root_resolved)` 判定 |
| 3 | **最终组件符号链接在 Windows 上不被拒**（无 `O_NOFOLLOW`，回退普通 open）——竞态窗口因此在 Windows 更宽；非竞态情形仍由围栏兜住 | 同上：`nofollow = getattr(os, "O_NOFOLLOW", None)` 与 `EINVAL/ENOTSUP` 回退分支 |
| 4 | 凭证 deny / 内部状态读 deny **不**作用于该低层通道（工具层才做：`PolicyEngine` 预检、`file_read`/`search` handler） | `path_safety.check_read_denied` 调用点仅 `engine/policy.py`、`tools/builtins/file.py`、`tools/builtins/search.py`。**这是刻意的**：`.heagent/skills` 本身就在内部状态 deny 表内，低层通道若套用会挡住 store 自己的读 |
| 5 | lock 只覆盖 entry 文件；运行期无人读 lock | `skill_importer.py`：`source_hash = self._hash(source_file)`（entry）、`_materialize` 用 `shutil.copytree(source, ...)`；`_read_lock()` 仅被 `import_manifest()` 调用（全仓 grep 无其他读取点） |
| 6 | 读路径无完整性校验 | `memory/skill_packages.py::_read_text` → `open_text_under_root`（仅围栏 + 普通文件校验）；`memory/skill_store.py::_read_text` 同 |
| 7 | 渲染侧已有「哈希钉 + 漂移即失败」，但只在**重新渲染时**触发 | `_bmad/scripts/render_skill.py::_publish` 写 `manifest.json`（逐文件哈希）、`_verify_existing` 比对并 `RenderError("generation output hash mismatch")` |
| 8 | 本仓库当前**未激活** importer 通道：`.heagent/skills/manifest.lock` 不存在（rendered 快照在 `_bmad/render/**`） | `dir .heagent\skills\manifest.lock` → 不存在；`_bmad/render/bmad-build/*/*/manifest.json` 存在 |

结论：**缺口真实但通道当前多为休眠**（importer 未激活），故不构成紧急项；一旦下游用
`SkillImporter` 导入第三方包，第 5/6 条即成为实际暴露面。

## 三、候选方案评估

| 候选 | 平台可行性 | 成本 | 兼容性 | 残余 |
|------|-----------|------|--------|------|
| **A. descriptor-relative / 逐组件 `openat`** | 仅 POSIX（`os.supports_dir_fd`）；Windows 无对应原语，需 NT API | 高（平台分支 + symlink 策略 + 测试矩阵） | 中（改共享低层通道，影响全部 workspace 读） | 仍有窗口（组件级竞态）；**命中 Ask First：引入平台专用代码** |
| **B. 内容哈希钉 + 读时校验（推荐方向）** | 全平台（纯 Python `hashlib`） | 低（复用既有 `manifest.json`/lock 形态；无新依赖） | 需定语义：lock-backed / rendered 包被拒读漂移内容 → **对「导入后手工改包」是行为变化**（**命中 Ask First：导入物化/读取语义**） | 不防「产生凭据的那一刻」已被污染；不防 hardlink 到同一 inode 的「未改内容」情形（内容等价，无实害） |
| **C. 复制快照（materialize 到独立可信目录）** | 全平台 | 中（新增物化时机与清理；importer 已在做，renderer 已做） | 低（不改读路径），但只覆盖「新导入」 | 已导入的存量包不受保护；仍不防快照后替换 |
| **D. OS 级沙箱** | 全平台需外部机制（容器/firejail/受限账号） | 外部依赖 | — | **唯一真正边界**；项目立场不变（见 CLAUDE.md） |

## 四、建议（**已获授权并实施**，2026-09-23）

> 用户决策：**(a) 确认**接受「lock/rendered 包被手工编辑后读取显性失败」的行为变化；
> **(b) 复用**既有凭据形态（`manifest.json` 的 `outputs` 表），**不**给 `manifest.lock` 新增字段。
> 实施落点：`memory/skill_packages.py::_pinned_hashes` + `_verify_pinned_hash`，
> 底层摘要通道 `tools/path_safety.py::read_bytes_under_root` / `read_text_with_digest_under_root`
> （哈希必须对**原始字节**，不能对 CRLF→LF 归一化后的文本）；测试 `tests/test_skill_package_integrity.py`（17 例）。
>
> **实现细节（由实证决定）**：凭据读取**先 stat 再读**（`manifest_path.is_file()` 门控）——未托管包因此
> **零额外 `os.open`**。首版没有门控，探针会为不存在的 `manifest.json` 多开一次文件，
> 直接打破 `tests/test_skill_packages_toctou.py` 的两条刻画测试（「资源读取恰好一个描述符」与
> 「第 1 次 `open` 抛 EINVAL 模拟不支持 `O_NOFOLLOW` 的文件系统 → 兼容回退」）。
> **该回归只在 Linux 暴露**（Windows 无 `O_NOFOLLOW`，相关测试 skip），本机全绿 ≠ CI 绿——
> 故实现改为 stat 门控【修代码】而非放宽测试【改断言】。

以 **B** 为最小闭环，理由：跨平台、无新依赖、fail-loud、且**复用已经存在的凭据形态**。

设计草案（不改变现有调用方签名）：

1. **凭据来源（按优先级，存在即用）**：
   - `<package>/manifest.json`（renderer 产物，已有逐文件 sha256 表）；
   - `manifest.lock` 的 `SkillLockEntry` 增可选字段 `resources: dict[str, str]`（相对 POSIX 路径 → sha256），
     在 `_materialize` 后对**整棵树**计算（跳过目录；对符号链接显式拒绝或记录为 `"symlink"` 标记）。
2. **校验点**（已实施）：`SkillPackage._read_text` 读到**原始字节摘要**后，若该包有凭据 → 比对 `sha256(该资源字节)`；
   不匹配抛 `SkillPackageResourceError(skill_id, resource, "resource hash differs from <凭据名>")`（显性失败，不静默接受）。
3. **兼容**：无凭据（手写技能，占多数）= 行为逐字节不变；旧 lock 无 `resources` 字段 = 跳过校验并记一条 debug；
   `SkillStore`（`.heagent/skills/<name>/SKILL.md`）默认无凭据 → 不变。
4. **明确的取舍**：lock-backed / rendered 包一旦被手工编辑，读取将失败——这需要用户确认（渲染器对漂移本就
   fail-loud，语义上一致；但对手工编辑导入包的工作流是破坏性变化）。
5. **测试**：凭据生成（含嵌套资源、符号链接处理）、漂移即拒读（改写/替换/截断三种）、无凭据包零变化、
   旧 lock 兼容、`render_skill.py` 既有 manifest 被正确复用。
6. **文档**：`docs/frame.md` 4.14（TOCTOU 段）+ 五、「本台账」，均按「defense-in-depth，非安全边界」表述。

**实施前置（Ask First，需你确认）**：
- 是否接受「lock/rendered 包被手工编辑后读取显性失败」这一行为变化？
- 凭据存放位置选 `manifest.lock.resources`（importer 侧）还是复用 `manifest.json`（renderer 侧），或两者都认？

## 五、残余风险声明（不变）

上述 A/B/C 都**不是安全边界**：内容哈希只能证明「与写凭据时一致」，不能证明「凭据本身可信」；
路径围栏是启发式 + 竞态窗口；凭证 deny 是 path/basename 匹配（对 inode 级替换不可见）。
唯一真边界仍是 **OS 级沙箱**（容器 / firejail / 受限账号）+ 最小权限，见 `CLAUDE.md` 安全声明。
