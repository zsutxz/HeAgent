"""Async TCP server for the HeAgent JSON Lines protocol."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from heagent.network.protocol import (
    ProtocolError,
    TcpErrorCode,
    TcpRequest,
    TcpResponse,
    decode_request,
    encode_response,
    error_response,
    response_from_protocol_error,
)

if TYPE_CHECKING:
    from asyncio import StreamReader, StreamWriter

logger = logging.getLogger(__name__)

TcpRequestHandler = Callable[[TcpRequest], Awaitable[TcpResponse]]


class TcpServerConfig(BaseModel):
    """Validated limits for one TCP server instance."""

    model_config = ConfigDict(frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=0, le=65535)
    max_connections: int = Field(default=32, ge=1)
    max_request_bytes: int = Field(default=1_048_576, ge=1)
    idle_timeout: float = Field(default=60.0, gt=0)
    request_timeout: float = Field(default=300.0, gt=0)
    shutdown_timeout: float = Field(default=5.0, gt=0)


class TcpServer:
    """Serve one bounded JSON Lines request per client connection."""

    _FRAMING_MARGIN = 2

    def __init__(self, config: TcpServerConfig, handler: TcpRequestHandler) -> None:
        self.config = config
        self.handler = handler
        self._server: asyncio.Server | None = None
        self._connection_tasks: set[asyncio.Task[None]] = set()
        self._request_tasks: set[asyncio.Task[Any]] = set()
        self._closing = False

    @property
    def sockets(self) -> tuple[object, ...]:
        """Return listening sockets for diagnostics and tests."""
        if self._server is None:
            return ()
        return tuple(self._server.sockets or ())

    @property
    def active_connections(self) -> int:
        """Return the number of tracked client handlers."""
        return len(self._connection_tasks)

    async def start(self) -> None:
        """Bind the configured address, propagating startup errors."""
        if self._server is not None:
            return
        self._closing = False
        self._server = await asyncio.start_server(
            self._handle_client,
            self.config.host,
            self.config.port,
            limit=self.config.max_request_bytes + self._FRAMING_MARGIN,
        )
        logger.info("TCP server listening on %s:%s", self.config.host, self.config.port)

    async def serve_forever(self) -> None:
        """Run until cancelled or closed."""
        if self._server is None:
            raise RuntimeError("TCP server is not started")
        await self._server.serve_forever()

    async def close(self) -> None:
        """Stop accepting connections and boundedly reap active handlers."""
        if self._closing:
            return
        self._closing = True
        server = self._server
        self._server = None
        if server is not None:
            server.close()

        request_tasks = tuple(self._request_tasks)
        connection_tasks = tuple(self._connection_tasks)
        for task in request_tasks + connection_tasks:
            task.cancel()
        tasks = request_tasks + connection_tasks
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=self.config.shutdown_timeout)
            if pending:
                logger.warning("TCP shutdown timed out with %d task(s)", len(pending))
            for task in done:
                if not task.cancelled():
                    task.exception()
        if server is not None:
            try:
                await asyncio.wait_for(server.wait_closed(), timeout=self.config.shutdown_timeout)
            except TimeoutError:
                logger.warning("TCP listener shutdown timed out")

    async def _handle_client(self, reader: StreamReader, writer: StreamWriter) -> None:
        task = asyncio.current_task()
        if task is None:
            await self._close_writer(writer)
            return
        if len(self._connection_tasks) >= self.config.max_connections:
            await self._write_response(
                writer,
                error_response("", TcpErrorCode.RATE_LIMITED, "server connection limit reached"),
            )
            await self._close_writer(writer)
            return

        self._connection_tasks.add(task)
        try:
            await self._process_client(reader, writer)
        except asyncio.CancelledError:
            raise
        except (ConnectionError, BrokenPipeError) as exc:
            logger.debug("TCP client disconnected: %s", exc)
        except Exception:
            logger.exception("Unhandled TCP client error")
        finally:
            self._connection_tasks.discard(task)
            await self._close_writer(writer)

    async def _process_client(self, reader: StreamReader, writer: StreamWriter) -> None:
        request_id = ""
        try:
            async with asyncio.timeout(self.config.idle_timeout):
                raw = await reader.readline()
        except TimeoutError:
            await self._write_response(
                writer,
                error_response(request_id, TcpErrorCode.TIMEOUT, "request read timed out"),
            )
            return
        except (asyncio.LimitOverrunError, ValueError):
            await self._write_response(
                writer,
                error_response(request_id, TcpErrorCode.REQUEST_TOO_LARGE, "request exceeds maximum size"),
            )
            return

        if not raw:
            return
        try:
            request = decode_request(raw, max_bytes=self.config.max_request_bytes)
            request_id = request.id
        except ProtocolError as exc:
            await self._write_response(writer, response_from_protocol_error(request_id, exc))
            return

        request_task = asyncio.create_task(self._run_request(request, request_id))
        self._request_tasks.add(request_task)
        try:
            response = await request_task
        finally:
            self._request_tasks.discard(request_task)
        await self._write_response(writer, response)

    async def _run_request(self, request: TcpRequest, request_id: str) -> TcpResponse:
        try:
            async with asyncio.timeout(self.config.request_timeout):
                return await self.handler(request)
        except TimeoutError:
            return error_response(request_id, TcpErrorCode.TIMEOUT, "request processing timed out")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("TCP request handler failed for request_id=%s", request_id)
            return error_response(request_id, TcpErrorCode.SERVER_ERROR, "request processing failed")

    async def _write_response(self, writer: StreamWriter, response: TcpResponse) -> None:
        try:
            writer.write(encode_response(response))
            await writer.drain()
        except (ConnectionError, BrokenPipeError) as exc:
            logger.debug("TCP response could not be written: %s", exc)
        except Exception:
            logger.warning("TCP response write failed", exc_info=True)

    @staticmethod
    async def _close_writer(writer: StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, BrokenPipeError) as exc:
            logger.debug("TCP writer close failed: %s", exc)
        except Exception:
            logger.warning("TCP writer close failed", exc_info=True)


__all__ = ["TcpRequestHandler", "TcpServer", "TcpServerConfig"]
