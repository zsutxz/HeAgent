"""CLI 侧用户级配置写入的统一审计留痕（A62）。

``heagent init`` / ``heagent init --interactive`` 会写 ``~/.heagent/setting.md``，这条路径此前
不经 :func:`heagent.pub.audit.record_operation`；网页写通道（``config.write``）与会话 / 技能删除
都进同一条链，缺了 CLI 侧就追证不到「谁改了配置」。

口径与既有接入点一致：

- ``before`` / ``after`` 只放 :func:`heagent.pub.audit.fingerprint_file` 的摘要（sha256 + 字节数），
  **配置值不进审计**；
- 审计落 ``<setting.md 所在目录>/audit/``——用户级配置没有项目状态根；
- 留痕失败不改变调用方结果（:func:`heagent.pub.audit.record_operation` 自身 fail-soft）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from heagent.pub.audit import fingerprint_file, record_operation

if TYPE_CHECKING:
    from pathlib import Path

OPERATION_SETTINGS_WRITE = "settings.write"


def snapshot_settings(path: Path) -> dict[str, Any]:
    """写前快照（供 :func:`record_settings_write` 的 ``before``）；文件不存在也返回可比较摘要。"""
    return fingerprint_file(path)


def record_settings_write(*, target: Path, before: dict[str, Any] | None) -> bool:
    """记一条用户级配置写入（``settings.write``），返回审计是否落盘。"""
    return record_operation(
        operation=OPERATION_SETTINGS_WRITE,
        target=str(target),
        before=before,
        after=fingerprint_file(target),
        state_dir=target.parent,
    )


__all__ = ["OPERATION_SETTINGS_WRITE", "record_settings_write", "snapshot_settings"]
