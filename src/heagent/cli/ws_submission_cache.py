"""WS 提交幂等窗口（Epic 77 D1）：同键在途合流 + 成功结果短窗重放。

住在入口层而不是传输层：幂等是**提交语义**，网络层只把客户端的 `request_id` 原样透传给
`ProjectChannelService`。本模块不认识项目目录、不读配置、不写盘——只有一个有界的内存字典。

三条语义（与 `ProjectChannelService` docstring 同口径）外加一条显式边界：

- **在途合流**：同一 `(project_id, request_id)` 的第二个等待者等同一个 `Future`，因此两侧拿到
  同一个 `run_id`；owner 失败时异常转交给等待者。**在途项不因 TTL 过期被踢**——它的键还在用着，
  踢掉就等于允许同键第二次真提交，合流这条保证会静默失效。
- **成功可重放**：结果在 TTL（默认 60s，**从提交开始计时**，不是从完成计时）内保留，重发直接
  命中，不再触达控制台。
- **失败不缓存**：键被移出窗口，重试可以重来（与「提交失败不做原子性保证」并存）。
- **内存有界优先于合流**（显式边界）：容量满时先淘汰已完成的旧项，全是在途时才退化为按插入序
  淘汰最旧一条——那一条的合流保证随之失效，这是 256 条上限的代价，不是漏写。

窗口是**进程内**状态：进程重启后失效。这是显式边界，不是缺陷——落盘幂等会把「提交」升级成有
状态事务，与既有立场冲突。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heagent.network.ws_protocol import SubmittedRun

#: 幂等窗口：同一 ``(project_id, request_id)`` 在这段时间内只真正提交一次。
IDEMPOTENCY_TTL_SECONDS = 60.0
#: 窗口内最多记住多少条提交：满了按插入序淘汰最旧的一条（内存有界，不随重试无限增长）。
IDEMPOTENCY_MAX_ENTRIES = 256

logger = logging.getLogger(__name__)

SubmissionKey = tuple[str, str]

#: 可观测面的两个事件名（E78）：容量淘汰与键移出各一条 DEBUG。TTL 过期清理**不打日志**——
#: 那是正常回收，逐请求刷一条只会淹掉真正的事件。
_EVENT_EVICTED = "ws event=idempotency_evicted"
_EVENT_DROPPED = "ws event=idempotency_dropped"


class SubmissionCache:
    """成功提交的短窗缓存与在途合流表（``(project_id, request_id)`` → ``Future``）。

    查表与登记之间**没有 ``await``**（并发提交会一起穿过「有没有」这把闸，A9③ 的老坑）。
    """

    def __init__(
        self,
        ttl: float = IDEMPOTENCY_TTL_SECONDS,
        max_entries: int = IDEMPOTENCY_MAX_ENTRIES,
    ) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        # 键 → (存入时刻, Future)：成功后保留结果直到过期；失败即由调用方移除。
        self._entries: dict[SubmissionKey, tuple[float, asyncio.Future[SubmittedRun]]] = {}
        self._clock = time.monotonic

    def reserve(self, key: SubmissionKey) -> tuple[asyncio.Future[SubmittedRun], bool]:
        """查表或登记：返回 ``(future, is_owner)``，只有 owner 负责真正提交并落结果。

        过期只清**已完成**项（在途项一条都不踢，见模块 docstring 的第二条）。清理带两层早停：

        - 窗口里最旧的一条都还没过期时，一次 O(1) 探测就跳过整趟扫描（高频稳态）；
        - 真要扫时按插入序（即时间序）从最旧往后走，遇到未过期即停——后面的只会更新。

        探测键的是「最旧一条」而**不是**「最旧一条已完成项」：在途项不会被 TTL 清掉，所以只要存在
        一条活得比 TTL 长的在途项，探测就会一直认为「有过期项」⇒ 每次 ``reserve`` 都退化成全表扫描。
        当前由调用方的提交上界兜住（`cli/ws_project_adapter` 的 ``submit_timeout`` 默认 30s < 60s TTL），
        保持 ``submit_timeout < ttl`` 这条耦合即可；**调大上界超过 TTL 时**要么把探测改成跳过未完成项，
        要么接受这条静默的性能退化。语义（在途不踢 / TTL 从提交计时）与扫描策略无关，改探测不会动它。

        容量满时同样先淘汰已完成的旧项，全是在途才退化为按插入序淘汰最旧一条。
        """
        now = self._clock()
        if self._entries:
            oldest = next(iter(self._entries))
            if now - self._entries[oldest][0] >= self._ttl:
                for stale_key, (at, entry_future) in list(self._entries.items()):
                    if now - at < self._ttl:
                        break
                    if entry_future.done():
                        self._entries.pop(stale_key, None)
        existing = self._entries.get(key)
        if existing is not None:
            return existing[1], False
        if len(self._entries) >= self._max_entries:
            # 只找**第一条**已完成项就够，不必先把已完成的全集建出来。
            victim = next((k for k, (_, future) in self._entries.items() if future.done()), None)
            if victim is None:
                victim = next(iter(self._entries))
            self._entries.pop(victim, None)
            # 只记 project_id 与 reason：``request_id`` 是客户端的不透明键，不进日志（同 ack 不回显）。
            logger.debug("%s project_id=%s reason=capacity entries=%d", _EVENT_EVICTED, victim[0], len(self._entries))
        future: asyncio.Future[SubmittedRun] = asyncio.get_running_loop().create_future()
        self._entries[key] = (now, future)
        return future, True

    def drop(self, key: SubmissionKey, *, reason: str = "failed") -> None:
        """失败 / 取消路径把键移出窗口：重试可以重来。

        ``reason``（``failed`` / ``cancelled``）只进 DEBUG 日志，不进任何对外面；键本来就不在窗口里
        时**不打日志**（幂等调用不该刷两条事件）。
        """
        if self._entries.pop(key, None) is not None:
            logger.debug("%s project_id=%s reason=%s", _EVENT_DROPPED, key[0], reason)


__all__ = ["IDEMPOTENCY_MAX_ENTRIES", "IDEMPOTENCY_TTL_SECONDS", "SubmissionCache", "SubmissionKey"]
