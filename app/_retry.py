"""Tiny retry helper for transient HTTP failures.

Scope: connect/read timeouts, transport-level errors, and 502/503/504
gateway responses — i.e. failure modes that usually clear on a quick
retry. 4xx, parsing errors, and other deterministic failures are NOT
retried (they would just fail again).
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({502, 503, 504})

_TRANSIENT_HTTPX_ERRORS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


def is_retryable_response(response: httpx.Response) -> bool:
    return response.status_code in RETRYABLE_STATUS_CODES


def _backoff_seconds(attempt: int, base: float) -> float:
    raw = min(base * (2 ** (attempt - 1)), 5.0)
    return random.uniform(0.0, raw)


async def retry_request(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    attempts: int = 3,
    backoff_base: float = 0.4,
    label: str = "http",
) -> httpx.Response:
    """Run `send`, retrying transient failures up to `attempts` times total.

    Retries on httpx transport errors and on 502/503/504. Returns the
    response (which may itself be a non-retryable error response — the
    caller decides what to do with that).
    """
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = await send()
        except _TRANSIENT_HTTPX_ERRORS as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            delay = _backoff_seconds(attempt, backoff_base)
            logger.info(
                "%s transient error on attempt %d/%d: %s — retrying in %.2fs",
                label, attempt, attempts, exc, delay,
            )
            await asyncio.sleep(delay)
            continue

        if is_retryable_response(response) and attempt < attempts:
            delay = _backoff_seconds(attempt, backoff_base)
            logger.info(
                "%s got %d on attempt %d/%d — retrying in %.2fs",
                label, response.status_code, attempt, attempts, delay,
            )
            await asyncio.sleep(delay)
            continue

        return response

    assert last_exc is not None
    raise last_exc
