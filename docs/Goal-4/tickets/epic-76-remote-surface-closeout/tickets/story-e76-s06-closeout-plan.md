---
ticket: 6
ref: 76.6
code: E76-S06
epic: epic-76-remote-surface-closeout
risk: low
hitl: false
covers: ["R7"]
status: done
---

# E76-S06 · 契约快照与文档收口：基线只含预期新增、文档同批同步

## Tasks & Acceptance

- [x] `python scripts/contract_snapshot.py --write` 重生成**五份**基线（`public_exports` / `transport_routes` / `exception_types` / `transport_errors` / `error_codes`），`git diff --stat tests/fixtures/contract_baselines/` = **空**（E74 / E75 期间已逐条落定，本轮零漂移 ⇒ 与「diff 只含预期新增」等效成立，且**无任何意外增删**）。
- [x] `python scripts/contract_snapshot.py --check` 五份全 `[OK]`。
- [x] `docs/framework.md` §4.16.1 项目通道行补**客户端对接口径（N3）**：`project_id` 随路径派生 ⇒ 目录移动 / 改名即换 id，旧 id 立刻变 `unknown_project`，客户端重拉列表让用户重选。
- [x] `docs/framework.md` §4.16.1 单 listener 装配行补**启动告警族**：`ws event=tls_identity` / `ws event=external_without_sandbox listener=external sandbox=<backend>`（对外档 + 生效后端非 docker 恰一条）/ `ws event=cli_bypass_skipped`，并点明「都只喊不停」。
- [x] `docs/errors.md` 项目与会话表补一行「客户端口径：`project_id` 的稳定性」：id 随路径派生、目录移动即换键、已安装 APK 需重新选择项目，并给出处置（收到 `unknown_project` 就重拉列表，不要重试同一 id）。
- [x] `mkdocs build --strict` 退出码 0、WARNING 计数 0（新增两处均为既有段落内的行内补充，未新增标题 ⇒ 手写 TOC 与锚点无需改动）。
- [x] 写集：五份基线（零字节变化）+ `docs/errors.md` + `docs/framework.md` + 本 plan。`docs/frame.md` **不存在**（见 Design Notes），未新建。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python scripts/contract_snapshot.py --write` | 五份重写（17216 / 9836 / 29561 / 7891 / 3975 bytes） |
| `git -c safe.directory=/workspace diff --stat tests/fixtures/contract_baselines/` | **空** |
| `.heagent/tmp/py311-venv-linux/bin/python scripts/contract_snapshot.py --check` | 五份全 `[OK]` |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests -q -k "contract or release_workflow or docs_links or security_posture"` | **269 passed, 1 skipped** |
| `.heagent/tmp/py311-venv-linux/bin/python -m mkdocs build --strict` | exit 0，WARNING 0 |
| `grep -n "路径派生\|目录移动" docs/errors.md docs/framework.md` | 各命中（客户端对接口径节） |

## Code Map

| 文件 | 改动 |
|---|---|
| `tests/fixtures/contract_baselines/*.json`（5 份） | `--write` 重生成，**零字节变化** |
| `docs/errors.md` | 项目与会话表 +1 行（`project_id` 稳定性 / 客户端口径） |
| `docs/framework.md` | §4.16.1 两处行内补充（启动告警族、客户端对接口径 N3） |
| `docs/Goal-4/tickets/.../story-e76-s06-closeout-plan.md` | 本文件 |
| `docs/frame.md` | **未新建**（见 Design Notes） |

## Design Notes

1. **`bad_spec` 记录：`docs/frame.md` 不存在**（与 75.3 / 75.6 同一处 v6 命名遗留）。真源是 `docs/framework.md` 的 §4.1 cli 子模块表 / 六、目录结构 / §4.16.1 WS 段。新建一份平行文件会造第二份真相并触发 mkdocs 无 nav 告警 ⇒ 不新建，只按真源同步。本行即裁定载体。
2. **基线「只含预期新增」以「零 diff」达成**：E74 的 `SubmittedRun` / `ProjectChannelService` / `WsProjectsFrame` 等与 E75 的 `project_registry_unreadable` 已在 75.1 与批级派生里逐条落定，本轮 `--write` 真正零字节变化 ⇒ 票面要求的「diff 只含预期新增」被更强的「无任何变化」满足，且反证了「没有意外增删」。
3. **五份而非四份**：`error_codes.json` 是 Epic 70 的产物，与其余四份同住 `tests/fixtures/contract_baselines/`。票面写「4 份」，实测 5 份；口径按实测。
4. **客户端口径为什么同时写两处**：`docs/errors.md` 是客户端**按码查表**的地方（收到 `unknown_project` 时该怎么办），`docs/framework.md` §4.16.1 是协议面**为什么**会这样（id 派生规则）。只写一处会让「查表的不知道原因、读协议的不知道动作」。
