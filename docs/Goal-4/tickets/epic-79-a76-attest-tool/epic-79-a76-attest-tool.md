---
type: epic
code: E79
parent: brief
slug: epic-79-a76-attest-tool
covers: ["R1", "R2"]
sources: ["_bmad-output/open-items.md", "docs/decisions/adr-0004-ws-tls-install-time-trust.md", "docs/Goal-4/tickets/epic-78-open-items-followthrough/epic-78-open-items-followthrough-retrospective.md"]
after: ["epic-78-open-items-followthrough"]
risk: low
refined: true
status: in-progress
---

# E79 · A76 服务端侧收成一条命令（wss 承兑工具 + 台账操作卡收窄）

## Description

E78 给 A76 写了操作卡，但「宿主 `netstat` 对账 + pin 三格式人眼比对 + 无 token 403 手测」仍是三条手工命令，
且台账正文与 `docs/tls-connect-guide.md`（gitignored 本地页）都还写着已退役的 A75 与「生产姿态未切换」。
本 epic 只做仓库内两件：① 新增 `scripts/ws_tls_attest.py` 把服务端侧四段判据机器化（一条命令出 `[OK]/[FAIL]`
与 exit code，含离线 `--self-check`）；② 把 A76 的操作卡收成「跑这一条 + 客户端三处对账」，并修掉本仓内
可入库的指针漂移（`AGENTS.md` 工具链）。**A76 不闭合**——剩下的客户端 pin 与设备三处对账仍在另一仓。

## Requirements

- **R1**（← A76 服务端侧）新增 `scripts/ws_tls_attest.py`：四段判据逐段打印 `[OK]/[FAIL]`——
  ① 绑定面（`host:port` 可连 + 指定地址必须 REFUSED，默认在被测地址非回环时加 `127.0.0.1:<port>`）
  ② TLS 握手（版本 / 套件 / 对端叶证书；不校链不校主机名，信任锚是 pin）
  ③ pin 对账（对端叶证书 SPKI-SHA256 与 `--cert` 逐字相等；打印 `spki_sha256` / 短指纹 / `sha256/<base64>` 三格式）
  ④ 认证闸门（无 token 的 WS 升级请求期望 `403`，给 `--token` 时追加验 `101`）。
  另有可选第 ⑤ 段 `--status-url`（比 `/api/status` 的 `tls.spki_sha256` 与第 ③ 段同源）。
  退出码 `0` 全过 / `1` 判据失败 / `2` 前提缺失（材料不可读、目标未监听）。`--self-check` 在本机起 TLS stub 离线自证四段。
  **token 只在请求头出现，任何分支都不打印值**（只报「已提供（长度 N）」）；脚本 stdlib only，只读探针。
- **R2**（← A76 操作卡）`_bmad-output/open-items.md` 的 A76 正文把「宿主 `netstat` + `heagent tls fingerprint`
  两条手工命令」收成「`python scripts/ws_tls_attest.py` 一条 + 期望输出」，`netstat` 降为可选补证；
  `AGENTS.md` 的 WS/TLS 工具链补该脚本（`heagent tls` → `ws_tls_attest.py` → `ws_manual_probe.py`）。
  **不新增 A 号、不改活动计数与速读节集合**（仍 4 条 / `A55 A65 A67 A76`）。

## Outcome

- A76 的服务端侧从「三条手工命令 + 人眼比对」变成「一条命令 + exit code」，差异点（绑定面漂移 / pin 漂移 /
  认证没开 / TLS 没起）各自有可读判据行。
- 客户端交付 pin 时不必再问服务端要值：脚本第 ③ 段直接打印三格式。
- 台账与工具链文档不再指向已退役的 A75 或「生产姿态未切换」这类过期口径。

## Boundaries

- **不闭合 A76**：客户端 `X509TrustManager` pin 与设备三处对账属 `aihome-client` 仓，本 epic 不碰。
- 不改服务端行为：不新增配置键、不加 `/api/status` 字段、不动 `heagent tls` 命令面与 TLS 材料管理。
- 不进 `heagent` CLI 命令面：与 `ws_manual_probe.py`、`web_search_smoke.py` 同档，`scripts/` 一次性工具。
- 不把 token 写进任何产物：脚本不落盘、不读 `.env`、不写 `.heagent/`。
- `docs/tls-connect-guide.md` 被 `.gitignore` 排除（客户端本地资料，见 ADR-0004），本 epic 的漂移修正在该页上
  只做**本地落改**、不入库；可入库的指针只有 `AGENTS.md`。

## Done when

- `pytest tests/test_ws_tls_attest_script.py -q` 全绿（自检全绿 / pin 不匹配判 `1` / 材料缺失与目标未监听判 `2` /
  `--help` 正常 / token 静态断言 / IPv6 脱括号）。
- `python scripts/ws_tls_attest.py --self-check` exit 0；对真 listener 跑一次四段全 `[OK]` 且 exit 0。
- `pytest tests/test_deferred_id_registry.py tests/test_docs_links.py -q` 全绿；`mkdocs build --strict` 0 warning。
- `ruff check` / `ruff format --check` / `mypy src` 与 HEAD 同谱。

## References

- `_bmad-output/open-items.md`（A76 正文与操作卡）
- `docs/decisions/adr-0004-ws-tls-install-time-trust.md`（信任锚 = SPKI pin；页 gitignored 的裁定）
- `src/heagent/network/tls_identity.py`（`spki_der` / `spki_sha256_of_der` / `short_fingerprint_of_der` 等）
- `tests/fixtures/ws_tls/`（自签材料，自检与判红路径的夹具）

## Notes

- 2026-11-24 Decision：**不新登 A 号**。A76 仍是一件事（客户端 pin 未交付），本 epic 只把它服务端侧机器化；
  为「立完即闭合」的中间态另开 A 号只会增加台账迁移成本（同 E78 的立场）。
- 2026-11-24 Decision：脚本取 **stdlib only**（`ssl` / `socket` / `urllib`），不依赖 `websockets`——
  宿主 `python scripts/ws_tls_attest.py` 直接可跑，不必先装 dev 依赖；离线自检自带 TLS stub，
  不复用 `tls_ws_stub.py`（后者是给人手测用的常驻进程，这里要的是进程内、可断言的形态）。
- 2026-11-24 Review：三审单文档见 `epic-79-a76-attest-tool-review.md`（四镜头一 0 条 / 镜头二 4 Medium 落改 / 镜头三 1 Low 记录）。核心落改 = 暴露面漂移不再被误报成「服务未在监听」（`1` vs `2`）、脱括号改走`network.exposure.unbracket_host`、第 ⑤ 段用显式指纹而非反解析文案、材料不可解析与非法参数不再 traceback；判据 7 → 11 例。epic 仍 `in-progress`，等用户放行。
