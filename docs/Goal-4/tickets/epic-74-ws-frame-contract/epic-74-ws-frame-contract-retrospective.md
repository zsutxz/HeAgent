---
epic: epic-74-ws-frame-contract
code: E74
date: 2026-11-23
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# E74 · WS 远程项目通道：协议与帧契约 — Retrospective

## Epic 摘要

- **Epic**：`epic-74-ws-frame-contract`（Requirements R1–R7 / 5 条 Done when），2026-11-23 立项 → 同日五条 entry 全部 `built` → 三审 + 回顾收口。
- **Tickets**（构建顺序 = 票树表序）：

| ref | 标题 | 状态 | 提交 |
|---|---|---|---|
| 74.1 | E74-S01 · 命令帧白名单单一映射表与可选 `project_id` | built | `d6e705de` |
| 74.2 | E74-S02 · 项目通道端口与带项目提交的端点转译 | built | `eeb7fee9` |
| 74.3 | E74-S03 · `cancel_run` 帧与只读口径 | built | `e0e9d411` |
| 74.4 | E74-S04 · 事件面零漂移契约钉子 | built | `ae1809f9` |
| 74.5 | E74-S05 · 错误码台账与哑传输边界收口 | built | `8b78186c` |

- **交付形态**：`ws_protocol.py` 426 行（帧模型 + 三个端口契约）/ 新建 `ws_commands.py` 253 行（命令循环簇）/ `ws_server.py` 988 → 698 行（反向拆出）；新增 6 个测试文件 869 行、+2 例架构契约判据。
- **证据面**：每条 entry 的 plan 均有 `## Verification` + 宿主实测数字；三审报告 `-review-r1/r2/r3.md` 齐备。

## 三审记录

| 轮次 | 结论 | 发现计数 | 落改去向 |
|---|---|---|---|
| **R1** 规格与实现对账（`bmad-code-review` 镜头） | 有条件的通过 | Critical 0 / High 0 / Medium 2 / Low 8 | 无落改（无 Critical/High）；M-1/M-2 与 8 条 Low 全进 `brief.md`「延期项」，M-1 转 75.2·75.3 |
| **R2** 不变量与守卫反脆弱（宿主自扫 + 注入反证） | 有条件的通过 | Critical 0 / High 1 / Medium 3 / Low 2 | High-1（依赖边界守卫对相对导入无牙）**当轮落改**：`_absolute_module` / `_package_of` / `_imported_modules` + 两条新判据，反证 D 自证（HEAD 无牙 → 修补后有牙 → 无注入转绿）；M-1/M-2/M-3 转 76.6 / 75.2·75.3 |
| **R3** 三镜头对抗式（`code_review`） | 通过（唯一 high 经复核为误报） | Critical 0 / High 1（→误报）/ Medium 8 / Low 6 | 落改 8 条（M-2 端口异常漏译判据、M-5 ack 语义措辞、M-6 `project_service` 显式忽略、L-1 两条只读流 `cancel_run` 判据、L-2 非对象 JSON、L-3 断连分支钉子、L-4 `project_id` 上界、L-6 R4 判据收紧）；M-1/M-3/M-4/M-7/M-8 + L-4(optional 结构)/L-5 转 75.2·75.3·75.5·75.6 |

- **H-1 误报的反证**（写在 `-review-r3.md` 的「H-1 复核」节）：注入 `from ..config import get_settings` 到 `network/ws_commands.py` → `test_no_reverse_dependency_on_agent` 红且报错逐字为 `运行期反向依赖：network/ws_commands.py → heagent.config`；复原即绿。
- **三审后的门禁实测**：`pytest tests/network tests/test_architecture_contracts.py -q` = **719 passed**；`ruff check` / `ruff format --check`（499 files）/ `mypy src`（239 files）/ `bandit -r src/ -ll`（No issues identified）全绿。

## 关键判断与 Decision

- **帧层先于运行时**：E74 只交协议与端口形状，`ProjectChannelService` 在生产装配里恒为 `None` ⇒ 生产行为是「带 `project_id` 回 `invalid_request`」。这是 epic 边界内的正当留白，但**必须写清**（否则 E75 会以为已有回归网）——已落 R3 M-1 的交接义务。
- **拆模块先于加功能**：74.3 前 `ws_server.py` 已 988 行（距 1000 行上限 12 行），先拆出 `ws_commands.py` 再加 `cancel_run`。事后看这一步是本 epic 最有复用价值的动作：E75 的 `project_service` 接线与 E76 的白名单收口都落在这个新模块边界上。
- **守卫比实现更值得投**：本 epic 测试 869 行里约 1/3 是「守卫的守卫」（依赖边界、事件面 golden、错误码台账）。R2 的反证证明这样投是对的——三条守卫里有一条（相对导入）确实没牙，而它是「哑传输」这条核心不变量唯一的机器判据。
- **三处口径差一律显式登记、不回改冻结文本**：R1 的 L-1 / L-3 / L-5 属「epic Requirements 字面 vs 实现」偏差，v7 下 epic Requirements 冻结，处置是登记进延期项并在 E76 文档收口统一措辞，不在评审里改规格。
- **误报也是要留证的产物**：R3 的 H-1 是本轮唯一 high，若按「评审说 high 就改」会去动一个本来就正确的函数。留证的反证（注入 → 红 → 复原 → 绿）把这条从"看起来严重"降为"噪声"，同时顺手把真实接线的红/绿钉进报告。

## 遗留（转下游 entry，详见 `docs/Goal-4/brief.md`「延期项」）

- **75.2 / 75.3**：适配器不得把路径写进错误消息（R2 M-2）；端口必须有内部超时（R3 M-3）；提交失败不做原子性保证 / 是否引入 `request_id`（R3 M-4）；补「名额计数不变」判据（R1 M-1）。
- **75.5**：`project_service` 的生产注入点 + wiring 判据（R3 M-1）。
- **75.6**：`_OPTIONAL_FRAME_FIELDS` 改 per-command 粒度（R3 L-4）；`frame_fields()` 公开读口（R3 L-5）。
- **76.6**：`docs/framework.md` 六处命令集口径 + 目录树补 `network/ws_commands.py`（R2 M-1 / M-3）；「权限口径 vs 授权」措辞（R3 M-8）；`invalid_request` 双义是否拆具名 code（R3 M-7）；单 run 端点 `unknown_run` 断连的措辞（R1 L-1）；`Done when` 第 4 条的异常类型口径（R1 L-5）。
- **已知预期红（不属本 epic）**：`tests/test_contract_baselines.py` 的 check 用例 —— `exception_types.json` 缺 74.1 新增的 `SubmittedRun` / `ProjectChannelService`，由 **76.6** 重生成快照收口。

## 结论

**accepted-with-open-items**：E74 的 7 条 Requirements 全部交付（R2 / R5 各有已登记的字面偏差），5 条 Done when 全部有可跑判据；三审三份报告 + 本回顾齐备；无遗留 Critical / High。开放项全部绑定到 E75 / E76 的具体 entry，不阻塞 E75 开工。
