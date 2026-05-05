import pytest

from app.events import SignalMessage
from app.processor import build_response


@pytest.mark.asyncio
async def test_ping_response() -> None:
    message = SignalMessage(sender="+15551234567", message="/ping", raw={})

    assert await build_response(message) == "pong"


@pytest.mark.asyncio
async def test_ping_alone_returns_pong() -> None:
    message = SignalMessage(sender="+15551234567", message="ping", raw={})

    assert await build_response(message) == "pong"


@pytest.mark.asyncio
async def test_ping_prefix_echoes_remainder() -> None:
    message = SignalMessage(sender="+15551234567", message="ping hello world", raw={})

    assert await build_response(message) == "Pong: hello world"


@pytest.mark.asyncio
async def test_ping_prefix_is_case_insensitive() -> None:
    message = SignalMessage(sender="+15551234567", message="PING TEST", raw={})

    assert await build_response(message) == "Pong: TEST"


@pytest.mark.asyncio
async def test_echo_response() -> None:
    message = SignalMessage(sender="+15551234567", message="hello", raw={})

    assert await build_response(message) == "You said: hello"


@pytest.mark.asyncio
async def test_help_response() -> None:
    message = SignalMessage(sender="+15551234567", message="help", raw={})

    reply = await build_response(message)

    assert reply is not None
    assert "ping" in reply.lower()
