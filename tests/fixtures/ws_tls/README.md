# WS TLS 测试件（Epic 56 Story 56-2）

`cert.pem` / `key.pem` 是**测试专用**的自签证书与私钥（CN=localhost，SAN=localhost + 127.0.0.1，
有效期 2026-01-01 至 2050-01-01），只用于 `tests/network/test_ws_e2e.py` 的 `wss` 握手判据。

- **不是凭证**：不含任何真实系统身份、不签发任何东西、不被任何生产代码引用。
- **不进生产路径**：`WsServerConfig.tls_*` 的默认值为 `None`；生产 TLS 由 `WS_TLS_CERT_FILE` /
  `WS_TLS_KEY_FILE` 指向用户自己的 PEM。
- **为什么要入库**：`cryptography` 不是本项目依赖，用 `openssl` CLI 现场生成会把测试变成
  「环境依赖 + 可跳过」——那样的判据等于没有（verification-gap 口径）。固定材料保证任何环境
  都能真跑 wss 判据。
- 轮换方式：直接重新生成同名两文件即可（`openssl req -x509 -newkey rsa:2048 -nodes …`）。
