import asyncio

import httpx
import pytest

from app._retry import retry_request


def _ok() -> httpx.Response:
    return httpx.Response(200, text="ok")


def _gateway_error(code: int = 503) -> httpx.Response:
    return httpx.Response(code, text="busy")


def test_retry_returns_first_successful_response_without_retrying() -> None:
    calls: list[int] = []

    async def send() -> httpx.Response:
        calls.append(1)
        return _ok()

    result = asyncio.run(retry_request(send, attempts=3, label="t"))

    assert result.status_code == 200
    assert len(calls) == 1


def test_retry_recovers_after_one_503_then_success() -> None:
    queue = [_gateway_error(503), _ok()]

    async def send() -> httpx.Response:
        return queue.pop(0)

    result = asyncio.run(retry_request(send, attempts=3, label="t"))

    assert result.status_code == 200
    assert queue == []


def test_retry_returns_last_503_when_all_attempts_exhausted() -> None:
    calls: list[int] = []

    async def send() -> httpx.Response:
        calls.append(1)
        return _gateway_error(502)

    result = asyncio.run(retry_request(send, attempts=3, label="t"))

    assert result.status_code == 502
    assert len(calls) == 3


def test_retry_does_not_retry_on_4xx() -> None:
    calls: list[int] = []

    async def send() -> httpx.Response:
        calls.append(1)
        return httpx.Response(404, text="nope")

    result = asyncio.run(retry_request(send, attempts=3, label="t"))

    assert result.status_code == 404
    assert len(calls) == 1


def test_retry_recovers_after_transient_connect_error() -> None:
    state = {"calls": 0}

    async def send() -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            raise httpx.ConnectError("kaboom")
        return _ok()

    result = asyncio.run(retry_request(send, attempts=3, label="t"))

    assert result.status_code == 200
    assert state["calls"] == 2


def test_retry_reraises_after_persistent_transport_error() -> None:
    async def send() -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(retry_request(send, attempts=2, label="t"))


def test_retry_does_not_swallow_non_transient_exceptions() -> None:
    async def send() -> httpx.Response:
        raise RuntimeError("programmer error")

    with pytest.raises(RuntimeError, match="programmer error"):
        asyncio.run(retry_request(send, attempts=3, label="t"))
