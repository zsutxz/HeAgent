# E79 回顾 · A76 服务端侧收成一条命令

## 一、做成了什么

| entry | 交付 | 判据 |
|---|---|---|
| 79.1 | `scripts/ws_tls_attest.py`：四段承兑（绑定面 / TLS 握手 / pin 对账 / 认证闸门）+ 可选第 ⑤ 段 `/api/status` 对账 + `--self-check` 离线自证 + 退出码 0/1/2 | 11 例（自检全绿 / pin 漂移判 1 / 材料缺失与目标未监听判 2 / 暴露面漂移判 1 / `--refused` 非法判 2 / ⑤ 段显式指纹 / `--help` / token 静态断言 / IPv6 与 `[localhost]` 脱括号） |
| 79.2 | A76 操作卡收窄为「跑这一条 + 期望输出」、`netstat` 降为可选补证；`AGENTS.md` 工具链补该脚本 | 台账守卫全绿（仍 4 条 / `A55 A65 A67 A76`）；真跑输出与卡片三行逐字一致 |

## 二、代价与偏差（显式）

- **三审挖出 4 条 Medium，都是「工具会给出误导结论」**：① 暴露面漂移被报成「服务未在监听」（`2` vs `1`）
  ② IPv6 脱括号自写第四份实现（`strip("[]")` 会把 `[localhost]` 也剥掉）③ 第 ⑤ 段从人读文案反解析指纹
  ④ 材料不可解析与 `--refused` 非法串退化成 traceback + 错的退出码。⇒ **「自己写的判据工具」尤其要先审
  它自己的失败面**：判据写错时它不是漏报，而是给出一个看起来可信的错结论。
- **`_Segment.fail` 的语义重载是根因**：一个 `ok=False` 同时承担「前提缺失」与「判据失败」两种语义，退出码
  就必然错一个。修法不是加分支判断文案，而是让 `_segment_bind` 显式返回 `(seg, reachable)`。
- **仓库既有不变量又一次靠三审兜住**：`network/exposure.py::unbracket_host` 的 docstring 早就写了「脱括号
  规则只有这一处实现」，新脚本仍然自写了一份 —— 说明「新增消费方去找现成实现」这条纪律需要写在
  `scripts/` 类一次性工具的检查清单里，而不只写在源码模块里。
- **一处环境限制被记成 L 而非假装验过**：真机「带正确 token → 101」在容器内不可验（`WS_AUTH_TOKEN` 在用户级
  `~/.heagent/setting.md`），101 分支由 `--self-check` 的 stub 覆盖；服务端侧无未验分支，只差一次宿主复跑。
- **`docs/tls-connect-guide.md` 仍是 gitignored**（ADR-0004 客户端本地资料）：该页的过期口径（引退役 A75、
  写「生产姿态未切换」）只在本地页修正、不入库，故 79.2 的 write_set 不含它 —— 这类「本地页漂移」不会
  进任何守卫，只能靠人记得。

## 三、留给下一轮的东西

- **A76 只剩客户端侧**：`X509TrustManager` 的 pin 校验 / 不校主机名 / 三错误码（`pin_mismatch` ·
  `cert_expired` · `cert_unreadable`）在 `aihome-client` 仓；pin 值可直接取脚本第 ③ 段三格式，不再问服务端。
- **宿主 `netstat` 仍可选**：容器侧等价证据已机器化（只有 `192.168.2.226:9201` OPEN、`127.0.0.1` 与
  docker 网桥侧 REFUSED），宿主原文从闭合必要条件降为补证。
- **叶证书 2026-12-19 到期**（余 25 天）：< 7 天时脚本会打「余量 < 7 天」提示；重签用 `heagent tls issue`
  （pin 不变），`rotate-key` 才改 pin。
- **活动台账 4 条仍全等外部**：A55 缺 `WEB_SEARCH_API_KEY`、A67 缺有 daemon 的机器、A76 缺客户端仓、
  A65 由用户裁定暂停 —— 仓内可做的前置已全部做完（E78 三条操作卡 + E79 一条命令）。

## 三审记录

| 镜头 | 结论 | 计数 | 落改去向 |
|---|---|---|---|
| 一 · 规格对账 | 通过 | C0 / H0 / M0 / L0 | — |
| 二 · 不变量与守卫反脆弱 | 有条件的通过 | C0 / H0 / **M4** / L2 落改 + L3 记录 | 漂移退出码、脱括号单源、⑤ 段显式指纹、traceback 兜底（+4 例判据）；`tls.cipher()` 双调 / `ws_listeners` 幻影别名顺手改；7 条注入反证全「红→复原→绿」 |
| 三 · 三镜头对抗（契约 / 并发 / 文档） | 通过 | C0 / H0 / M0 / **L1** | L-6（stub accept 线程不随 close 立即退出）记录不改 |

报告：`epic-79-a76-attest-tool-review.md`（单文档三镜头）。门禁：全量 `pytest` 5924 passed / 0 failed、
`ruff check` + `format --check`（553 files）、`mypy src`（242 files）、`contract_snapshot --check` 五份 `[OK]`、
`mkdocs --strict` 0 warning、真跑生产姿态四段 `[OK]` exit 0。
