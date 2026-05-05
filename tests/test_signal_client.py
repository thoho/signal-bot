import asyncio
from collections.abc import Iterable
from typing import Any

import httpx
import pytest
import respx
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from app.signal_client import SignalApiError, SignalClient


def _client() -> SignalClient:
    return SignalClient("http://signal.test", "+15550000000")


class FakeWebSocket:
    def __init__(self, messages: Iterable[str | bytes]) -> None:
        self.messages = list(messages)

    async def recv(self) -> str | bytes:
        if not self.messages:
            await asyncio.sleep(1)
            return "{}"
        return self.messages.pop(0)


class FakeConnect:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self) -> FakeWebSocket:
        return self.websocket

    async def __aexit__(self, *args: Any) -> None:
        return None


@pytest.mark.asyncio
@respx.mock
async def test_send_message_posts_payload_and_returns_json_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured.update(json.loads(request.content.decode()))
        return httpx.Response(200, json={"timestamp": 1})

    respx.post("http://signal.test/v2/send").mock(side_effect=handler)

    body = await _client().send_message("hello", ["+1", "+2"])

    assert body == {"timestamp": 1}
    assert captured == {
        "number": "+15550000000",
        "recipients": ["+1", "+2"],
        "message": "hello",
    }


@pytest.mark.asyncio
@respx.mock
async def test_send_message_returns_empty_dict_when_response_has_no_body() -> None:
    respx.post("http://signal.test/v2/send").mock(return_value=httpx.Response(200))

    assert await _client().send_message("hi", ["+1"]) == {}


@pytest.mark.asyncio
@respx.mock
async def test_send_message_raises_on_5xx() -> None:
    respx.post("http://signal.test/v2/send").mock(return_value=httpx.Response(500, text="bad"))

    with pytest.raises(SignalApiError, match="send failed"):
        await _client().send_message("hi", ["+1"])


@pytest.mark.asyncio
async def test_receive_returns_websocket_payload_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_connect(uri: str, **kwargs: object) -> FakeConnect:
        captured["uri"] = uri
        captured["kwargs"] = kwargs
        return FakeConnect(
            FakeWebSocket(
                [
                    '{"envelope":{"dataMessage":{"message":"one"}}}',
                    b'{"envelope":{"dataMessage":{"message":"two"}}}',
                ]
            )
        )

    monkeypatch.setattr("app.signal_client.websockets.connect", fake_connect)

    payload = await _client().receive(
        timeout_seconds=1,
        max_messages=2,
        send_read_receipts=True,
        ignore_attachments=False,
    )

    assert payload == [
        {"envelope": {"dataMessage": {"message": "one"}}},
        {"envelope": {"dataMessage": {"message": "two"}}},
    ]
    assert captured["uri"] == "ws://signal.test/v1/receive/+15550000000"
    assert captured["kwargs"] == {
        "open_timeout": 10,
        "ping_interval": 20,
        "ping_timeout": 20,
        "proxy": None,
    }


@pytest.mark.asyncio
async def test_receive_returns_empty_on_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.signal_client.websockets.connect",
        lambda *_args, **_kwargs: FakeConnect(FakeWebSocket([])),
    )

    payload = await _client().receive(
        timeout_seconds=0,
        max_messages=10,
        send_read_receipts=True,
        ignore_attachments=False,
    )

    assert payload == []


@pytest.mark.asyncio
async def test_receive_raises_on_websocket_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_connect(*_args: object, **_kwargs: object) -> FakeConnect:
        raise OSError("no route")

    monkeypatch.setattr("app.signal_client.websockets.connect", fake_connect)

    with pytest.raises(SignalApiError, match="websocket receive failed"):
        await _client().receive(
            timeout_seconds=1,
            max_messages=10,
            send_read_receipts=True,
            ignore_attachments=False,
        )


@pytest.mark.asyncio
async def test_receive_falls_back_to_http_when_websocket_gets_plain_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_connect(*_args: object, **_kwargs: object) -> FakeConnect:
        raise InvalidStatus(Response(200, "OK", Headers()))

    async def fake_http(self: SignalClient, **kwargs: object) -> list[dict[str, object]]:
        calls.append(kwargs)
        return [{"envelope": {}}]

    monkeypatch.setattr("app.signal_client.websockets.connect", fake_connect)
    monkeypatch.setattr("app.signal_client.SignalClient._receive_http", fake_http)

    payload = await _client().receive(
        timeout_seconds=1,
        max_messages=10,
        send_read_receipts=True,
        ignore_attachments=False,
    )

    assert payload == [{"envelope": {}}]
    assert calls == [
        {
            "timeout_seconds": 1,
            "max_messages": 10,
            "send_read_receipts": True,
            "ignore_attachments": False,
        }
    ]


@pytest.mark.asyncio
async def test_receive_falls_back_to_http_when_websocket_handshake_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_connect(*_args: object, **_kwargs: object) -> FakeConnect:
        raise TimeoutError("timed out during opening handshake")

    async def fake_http(self: SignalClient, **kwargs: object) -> list[dict[str, object]]:
        calls.append(kwargs)
        return []

    monkeypatch.setattr("app.signal_client.websockets.connect", fake_connect)
    monkeypatch.setattr("app.signal_client.SignalClient._receive_http", fake_http)

    payload = await _client().receive(
        timeout_seconds=1,
        max_messages=10,
        send_read_receipts=True,
        ignore_attachments=False,
    )

    assert payload == []
    assert calls == [
        {
            "timeout_seconds": 1,
            "max_messages": 10,
            "send_read_receipts": True,
            "ignore_attachments": False,
        }
    ]


@pytest.mark.asyncio
async def test_receive_raises_on_non_json_websocket_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.signal_client.websockets.connect",
        lambda *_args, **_kwargs: FakeConnect(FakeWebSocket(["not-json"])),
    )

    with pytest.raises(SignalApiError, match="non-JSON"):
        await _client().receive(
            timeout_seconds=1,
            max_messages=10,
            send_read_receipts=True,
            ignore_attachments=False,
        )


@pytest.mark.asyncio
@respx.mock
async def test_get_attachment_returns_bytes_and_content_type() -> None:
    respx.get("http://signal.test/v1/attachments/abc").mock(
        return_value=httpx.Response(
            200, content=b"raw-audio-bytes", headers={"content-type": "audio/ogg"}
        )
    )

    body, content_type = await _client().get_attachment("abc")

    assert body == b"raw-audio-bytes"
    assert content_type == "audio/ogg"


@pytest.mark.asyncio
@respx.mock
async def test_get_attachment_raises_on_5xx() -> None:
    respx.get("http://signal.test/v1/attachments/abc").mock(
        return_value=httpx.Response(404, text="missing")
    )

    with pytest.raises(SignalApiError, match="attachment download failed"):
        await _client().get_attachment("abc")


@pytest.mark.asyncio
@respx.mock
async def test_send_message_retries_503_then_succeeds() -> None:
    respx.post("http://signal.test/v2/send").mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    body = await _client().send_message("hi", ["+1"])

    assert body == {"ok": True}


@pytest.mark.asyncio
@respx.mock
async def test_get_attachment_recovers_after_one_connect_error() -> None:
    respx.get("http://signal.test/v1/attachments/abc").mock(
        side_effect=[
            httpx.ConnectError("first fails"),
            httpx.Response(
                200, content=b"audio", headers={"content-type": "audio/ogg"}
            ),
        ]
    )

    body, content_type = await _client().get_attachment("abc")

    assert body == b"audio"
    assert content_type == "audio/ogg"
