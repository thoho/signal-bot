import pytest

from app.events import SignalMessage
from app.processor import build_response


@pytest.mark.asyncio
async def test_ping_response() -> None:
    message = SignalMessage(sender="+15551234567", message="/ping", raw={})

    assert await build_response(message) == "pong"


@pytest.mark.asyncio
async def test_echo_response() -> None:
    message = SignalMessage(sender="+15551234567", message="hello", raw={})

    assert await build_response(message) == "You said: hello"
