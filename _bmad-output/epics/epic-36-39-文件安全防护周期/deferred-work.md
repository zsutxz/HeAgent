# Epic 36–39 文件安全防护周期遗留项台账（deferred-work）

> **归档规则**：按条目**归属的 epic** 归档（本周期 = 凭证 deny / env scrubbing / 内部状态读 deny / 安全声明）；
> 「闭合者」注明实际完成它的批次 / commit。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码与测试。
> **活动（未闭合）遗留项**仍在 [`implementation-artifacts/deferred-work-archive.md`](../../implementation-artifacts/deferred-work-archive.md)。
>
> **立场不变**：以下全部为 defense-in-depth 启发式层，**非真正安全边界**——shell 工具仍可
> `cat .env` 绕过，须 OS 级沙箱兜底（见 CLAUDE.md 安全声明）。

## 状态总览

| ID | 条目 | 状态 | 闭合者 |
|----|------|------|--------|
| F-D1 | 凭证 deny 规则的用户可配置入口 | 已闭合（2026-09-17） | 优化批次 2（commit `63806d3`） |

---

## F-D1 凭证 deny 规则的用户可配置入口

- **来源**：`brief.md`「### Deferred（未来考虑）：凭证 deny 规则的用户可配置入口」；2026-09-17 第二轮优化批次闭合（commit `63806d3`）。
- **问题**：凭证路径 deny 规则是 `path_safety.py` 内硬编码表，用户既不能补充自定义敏感路径，也不能放行误伤（如把某测试夹具目录从 deny 中排除）。
- **结论**：**已闭合**（含函数名勘误：台账原记 `write_deny_reason`/`read_deny_reason`，实为 `check_write_denied` / `check_read_denied`）。新增项目级 `.heagent/path_deny.json`（workspace 围栏锚定 + 进程级懒缓存，对齐 `injection_signatures.json` 先例）：`deny_write_paths`/`deny_write_prefixes`/`deny_read_basenames` 收紧、`allow_write_paths`/`allow_read_basenames` 放行显式列举项（内部状态目录 deny **不接受豁免**——另一保护类，不随用户配置放松）；**无任何整体关闭入口**，fail-safe 默认仍拒（冻结边界满足）。容错对齐 `_load_user_signatures`：文件缺失静默空、读坏/JSON 坏 ERROR+空、逐条非法跳过+ERROR，从不抛出。5 个消费点（policy 预检 / file handler ×2 / search ×2）零改动，两层纵深自动生效。
- **证据**：`tests/test_credential_guard.py::TestUserDenyRules`（9 用例：收紧/放行/缺失/坏 JSON/逐条跳过/懒加载一次/内部状态不豁免）。
