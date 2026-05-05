import httpx
import pytest
import respx

from app.signal_client import SignalApiError, SignalClient


def _client() -> SignalClient:
    return SignalClient("http://signal.test", "+15550000000")


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
@respx.mock
async def test_receive_returns_payload_list() -> None:
    respx.get("http://signal.test/v1/receive/+15550000000").mock(
        return_value=httpx.Response(200, json=[{"envelope": {}}])
    )

    payload = await _client().receive(
        timeout_seconds=1,
        max_messages=10,
        send_read_receipts=True,
        ignore_attachments=False,
    )

    assert payload == [{"envelope": {}}]


@pytest.mark.asyncio
@respx.mock
async def test_receive_returns_empty_on_read_timeout() -> None:
    respx.get("http://signal.test/v1/receive/+15550000000").mock(
        side_effect=httpx.ReadTimeout("idle")
    )

    payload = await _client().receive(
        timeout_seconds=1,
        max_messages=10,
        send_read_receipts=True,
        ignore_attachments=False,
    )

    assert payload == []


@pytest.mark.asyncio
@respx.mock
async def test_receive_returns_empty_when_response_body_empty() -> None:
    respx.get("http://signal.test/v1/receive/+15550000000").mock(
        return_value=httpx.Response(200)
    )

    payload = await _client().receive(
        timeout_seconds=1,
        max_messages=10,
        send_read_receipts=True,
        ignore_attachments=False,
    )

    assert payload == []


@pytest.mark.asyncio
@respx.mock
async def test_receive_raises_on_5xx() -> None:
    respx.get("http://signal.test/v1/receive/+15550000000").mock(
        return_value=httpx.Response(500, text="bad")
    )

    with pytest.raises(SignalApiError, match="receive failed"):
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
