---
ticket: 1
ref: 79.1
code: E79-S01
epic: epic-79-a76-attest-tool
risk: low
hitl: false
covers: ["R1"]
status: done
---

# E79-S01 · `scripts/ws_tls_attest.py`：A76 服务端侧的四段承兑

## Intent

<frozen-after-approval>

A76 的服务端侧证据散在三条手工命令里（宿主 `netstat` 看绑定面、`heagent tls fingerprint` 看 pin、
`websockets` 手测无 token 403），各自判读口径还要靠人记。本 entry 把它们收成一个脚本：一条命令跑完
绑定面 → TLS 握手 → pin 对账 → 认证闸门，逐段打印 `[OK]` / `[FAIL]`，用退出码给机器判。

四段 = ① `host:port` 可连 + 指定地址必须 REFUSED（默认在被测地址非回环时加 `127.0.0.1:<port>`，
生产姿态下回环腿是刻意消失的）② TLS 握手（版本 / 套件 / 对端叶证书；刻意不校链、不校主机名，
与客户端 pin 口径一致）③ pin 对账（对端叶证书 SPKI-SHA256 与 `--cert` 逐字相等，并打印
`spki_sha256` / 短指纹 / OkHttp `sha256/<base64>` 三格式）④ 认证闸门（无 token 的 WS 升级请求期望
`403`；给了 `--token` 再验 `101`）。第 ⑤ 段可选：`--status-url` 比 `/api/status` 的 `tls.spki_sha256`。

</frozen-after-approval>

## Boundaries & Constraints

**Always**

- stdlib only（`ssl` / `socket` / `urllib`）：宿主裸 `python scripts/ws_tls_attest.py` 就能跑，不必装 dev 依赖。
- 只读探针：不提交 run、不建会话、不改服务端状态；连接拿到状态行即关闭，不进帧循环。
- token 只进 `Authorization: Bearer` 请求头；任何输出行只报「已提供（长度 N）」。
- 退出码契约：`0` 全过 / `1` 判据失败 / `2` 前提缺失（材料不可读、目标未监听）。
- `--self-check` 必须在无网络、无生产材料的机器上可跑（材料用 `--cert` / `--key` 指向测试夹具即可）。

**Never**

- 不复用 `scripts/tls_ws_stub.py` 做自检（那是给人手测的常驻进程；自检要进程内、可断言）。
- 不进 `heagent` CLI 命令面；不加配置键、不改 `/api/status` 字段。

## Plan

1. 探针层：`_tcp_probe` / `_tls_handshake`（`CERT_NONE` + `check_hostname=False`）/ `_ws_upgrade`（手写
   RFC 6455 升级请求，只读状态行）。
2. 判据层：`_Segment`（同 `web_search_smoke.py` 的形态）+ 四段函数 + 可选 `_segment_status`。
3. 自检层：`_start_stub`（本机 TLS stub：有 `Authorization` 回 `101`、否则 `403`）+ `--serve-cert`
   以便验「对端与本地材料不是同一套」的判红路径。
4. 判据测试：`tests/test_ws_tls_attest_script.py`（子进程 argv 固定、不碰生产入口）。

## Verification

- `pytest tests/test_ws_tls_attest_script.py -q` → **11 passed**（首版 7 例；三审补 4 例：暴露面漂移判 `1`、
  本地材料不可解析判 `2`、`--refused` 非法判 `2`、第 ⑤ 段比对显式指纹）。
- `python scripts/ws_tls_attest.py --self-check --cert tests/fixtures/ws_tls/cert.pem --key tests/fixtures/ws_tls/key.pem` → exit 0，四段 `[OK]`。
- 对真 listener（`192.168.2.226:9201`）跑一次 → exit 0，且 `127.0.0.1:9201 REFUSED`、pin `247a8b…fd301`、
  `无 token → HTTP/1.1 403 Forbidden` 三行俱在（2026-11-24 实测，见 epic Notes）。
- `ruff check src tests scripts examples` / `ruff format --check` / `mypy src` 与 HEAD 同谱。
