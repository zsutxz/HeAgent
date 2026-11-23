---
type: retrospective
code: E76-RETRO
epic: epic-76-remote-surface-closeout
retrospective_at: 2026-11-23
head: 3ef5be81
---

# E76 回顾 · WS 远程项目通道：并发隔离与远程面收口

## 交付面

| Entry | 内容 | 形态 |
|---|---|---|
| 76.1 | 断线续流（cursor）不丢事件 | 纯测试增量（`test_ws_resume.py`） |
| 76.2 | 并发隔离：名额双层、三码不互相占额 | 纯测试增量（`test_ws_project_admission.py`） |
| 76.3 | 远程可见面不扩张（命令/帧封闭集 + 词根守卫） | 纯测试增量（`test_ws_protocol.py`） |
| 76.4 | `external` + 非 docker 恰一条启动 WARNING | **唯一实质代码改动**（`cli/http_config.py` + `cli/http.py`） |
| 76.5 | ADR-005 验收基线五步串跑 | 纯测试增量（`test_ws_remote_flow.py`） |
| 76.6 | 契约基线与文档收口 | 文档 + 五份基线（零 diff）+ 客户端对接口径 |

## 三审记录

| 轮次 | 镜头 | 结论 | 计数 |
|---|---|---|---|
| R1 | 规格与实现对账 | 有条件的通过 | Critical 0 / High 0 / Medium 4 / Low 3 |
| R2 | 不变量与守卫（反证式） | 通过 | G1–G7 全部可反证；G2 原为软守卫，当轮补强 |
| R3 | code_review 三镜头 | 通过（有条件） | Critical 0 / High 0 / Medium 3 / Low 3 |

- R2 反证两条实跑：注入 `return None` ⇒ 76.4 告警用例红，回退绿；`sandbox_backend` 入口注入断言补前对漏传无牙、补后有牙。
- 当轮落改仅 1 处（`tests/test_cli_http_lifecycle.py` 增一行断言），其余 Medium/Low 全转 `brief.md` 延期项。
- 无 High / Critical ⇒ 无阻塞项。

## 门禁实测（E76 收口）

- `pytest tests/network tests/test_cli_http_lifecycle.py tests/test_architecture_contracts.py tests/test_contract_baselines.py -q` = 见 progress 收口行
- `scripts/contract_snapshot.py --check` = 五份 `[OK]`
- `mkdocs build --strict` = 0 warning

## 遗留（转 `brief.md` 延期项）

1. `lan` 档在宿主执行时零告警（风险高于 external）—— 需用户裁定是否补喊。
2. `http_server_cmd` 回落链取请求值而非生效值的静默窗口。
3. ADR-005 端到端（真 listener + 真服务）未验 —— 承 E75 同名缺口。
4. 两处公告口径不一致、词根守卫的子串匹配过宽。

## 方法沉淀

- **判据要盯「生效值」而不是「请求值」**：76.4 的 WARN 逻辑本身对，但测试只调 `build_ws_servers`，入口漏传时回落链会掩盖 ——「断言比实现弱」是纯测试增量类 entry 最典型的空转形态，反证（注入即红）能一击暴露。
- **纯测试增量 entry 的验收要点是「能否被反证」**：76.1/76.2/76.3/76.5 全绿不等于有牙，必须逐条注入缺陷验证（R2 的 G1–G7 清单化做法可复用）。
- **票面与生产链的码名容易错位**：`project_busy`（删项目面）vs `run_conflict`（WS 提交面）——按码名读规格会在错误层找断言，落判据前先核「这个码是谁抛的」。
