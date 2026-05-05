import httpx
import pytest
import respx

from app.events import SignalMessage
from app.master_client import MasterClient, MasterClientError


def _message() -> SignalMessage:
    return SignalMessage(
        sender="+15551234567",
        message="hi",
        timestamp=1700000000,
        group_id=None,
        attachments=[],
        raw={},
    )


@pytest.mark.asyncio
async def test_disabled_client_returns_none_without_calling_master() -> None:
    client = MasterClient("http://master.test", enabled=False)

    reply = await client.send_signal_event(_message(), text="hi")

    assert reply is None


@pytest.mark.asyncio
@respx.mock
async def test_returns_reply_string_on_success() -> None:
    respx.post("http://master.test/v1/events/signal").mock(
        return_value=httpx.Response(200, json={"reply": "pong"})
    )
    client = MasterClient("http://master.test", enabled=True)

    reply = await client.send_signal_event(_message(), text="hi")

    assert reply == "pong"


@pytest.mark.asyncio
@respx.mock
async def test_returns_none_when_reply_is_missing_or_blank() -> None:
    respx.post("http://master.test/v1/events/signal").mock(
        return_value=httpx.Response(200, json={"reply": "   "})
    )
    client = MasterClient("http://master.test", enabled=True)

    reply = await client.send_signal_event(_message(), text="hi")

    assert reply is None


@pytest.mark.asyncio
@respx.mock
async def test_raises_master_client_error_on_5xx() -> None:
    respx.post("http://master.test/v1/events/signal").mock(
        return_value=httpx.Response(500, text="boom")
    )
    client = MasterClient("http://master.test", enabled=True)

    with pytest.raises(MasterClientError, match="500"):
        await client.send_signal_event(_message(), text="hi")


@pytest.mark.asyncio
@respx.mock
async def test_raises_master_client_error_on_network_failure() -> None:
    respx.post("http://master.test/v1/events/signal").mock(
        side_effect=httpx.ConnectError("nope")
    )
    client = MasterClient("http://master.test", enabled=True)

    with pytest.raises(MasterClientError, match="failed"):
        await client.send_signal_event(_message(), text="hi")


@pytest.mark.asyncio
@respx.mock
async def test_payload_includes_sender_text_transcript_and_metadata() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured.update(json.loads(request.content.decode()))
        return httpx.Response(200, json={"reply": "ok"})

    respx.post("http://master.test/v1/events/signal").mock(side_effect=handler)
    client = MasterClient("http://master.test", enabled=True)

    message = SignalMessage(
        sender="+15551234567",
        message="orig",
        timestamp=1700000000,
        group_id="grp1",
        attachments=[],
        raw={},
    )
    await client.send_signal_event(message, text="cleaned text", transcript="audio text")

    assert captured["sender"] == "+15551234567"
    assert captured["text"] == "cleaned text"
    assert captured["transcript"] == "audio text"
    assert captured["source_message_id"] == "1700000000"
    assert captured["message_timestamp"] == 1700000000
    assert captured["metadata"] == {"group_id": "grp1", "attachment_count": 0}


@pytest.mark.asyncio
@respx.mock
async def test_payload_omits_source_message_id_when_no_timestamp() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured.update(json.loads(request.content.decode()))
        return httpx.Response(200, json={"reply": None})

    respx.post("http://master.test/v1/events/signal").mock(side_effect=handler)
    client = MasterClient("http://master.test", enabled=True)

    message = SignalMessage(sender="+1", message="x", timestamp=None, raw={})
    await client.send_signal_event(message, text="x")

    assert captured["source_message_id"] is None
    assert captured["message_timestamp"] is None
