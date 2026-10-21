# HeAgent 容器沙箱镜像（Epic 53 期一 · Story 53-2；brief 决策 D4）
#
# 基座 pin：python:3.11-slim @ sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
# （2026-10-21 查证。docker.io 直连不可达的网络，用
#   --build-arg BASE=docker.m.daocloud.io/library/python:3.11-slim 换源重建，产出一致；换源不换 pin 语义——
#   镜像源与 docker.io 的 manifest 字节一致。）
#
# 工具链立场：只装 git + ca-certificates（git 为 shell 工作流高频依赖，CA 供 bridge 档 TLS）。
# 其余按项目自备：容器默认 --network=none，pip 装包会显性失败——这是 D2 的立场而非缺陷。
#
# 非 root 用户（审查修复批 2026-10-21）：命令以 sandbox 运行（argv 同时带
# --cap-drop=ALL + no-new-privileges），防 root-in-container；POSIX 宿主上挂载目录
# 归属宿主用户时容器侧可能不可写——失败显性，chown 或挂载调整由宿主侧处理。
ARG BASE=python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
FROM ${BASE}

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/sh sandbox

USER sandbox
