"""端口查找工具 - 自动查找可用端口以避免冲突"""

import logging
import socket

logger = logging.getLogger(__name__)


def find_available_port(preferred_port: int, host: str = "127.0.0.1", max_attempts: int = 10) -> int:
    """查找可用端口，优先使用 preferred_port，失败则尝试后续端口。

    Args:
        preferred_port: 首选端口号
        host: 绑定地址（默认 127.0.0.1）
        max_attempts: 最大尝试次数（默认 10）

    Returns:
        可用的端口号

    Raises:
        RuntimeError: 在指定范围内未找到可用端口

    Examples:
        >>> port = find_available_port(8766)
        >>> # 如果 8766 可用则返回 8766，否则尝试 8767, 8768...
    """
    for offset in range(max_attempts):
        port = preferred_port + offset
        try:
            # 测试端口是否可用
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                # 成功绑定，端口可用
                if offset > 0:
                    logger.info(
                        "Port %d was in use, using port %d instead (offset +%d)",
                        preferred_port,
                        port,
                        offset,
                    )
                return port
        except OSError as exc:
            # 端口被占用或其他绑定错误
            if offset == 0:
                logger.debug("Port %d is in use, trying next available port: %s", port, exc)
            continue

    # 所有尝试都失败
    raise RuntimeError(
        f"No available port found in range {preferred_port}-{preferred_port + max_attempts - 1}. "
        f"All {max_attempts} ports are in use. "
        f"Please specify a different port with --port or HTTP_PORT environment variable."
    )
