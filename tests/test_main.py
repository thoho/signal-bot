import logging

import pytest

from app.events import SignalAttachment, SignalMessage
from app.main import handle_payload, process_inbound_message
from app.master_client import MasterClientError


class FakeSignalClient:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, list[str]]] = []

    async def get_attachment(self, attachment_id: str) -> tuple[bytes, str]:
        assert attachment_id == "voice-note-1"
        return b"audio-bytes", "audio/ogg"

    async def send_message(self, message: str, recipients: list[str]) -> dict:
        self.sent_messages.append((message, recipients))
        return {}


class FakeTranscriptionClient:
    def __init__(self, transcript: str = "ping") -> None:
        self.transcript = transcript

    async def transcribe(
        self, audio: bytes, attachment: SignalAttachment, content_type: str
    ) -> str:
        assert audio == b"audio-bytes"
        assert attachment.id == "voice-note-1"
        assert content_type == "audio/ogg"
        return self.transcript


class FakeMasterClient:
    def __init__(
        self, reply: str | None, should_fail: bool = False, enabled: bool = True
    ) -> None:
        self.reply = reply
        self.should_fail = should_fail
        self.enabled = enabled
        self.events: list[tuple[str, str | None]] = []

    async def send_signal_event(
        self,
        message: SignalMessage,
        *,
        text: str,
        transcript: str | None = None,
    ) -> str | None:
        self.events.append((text, transcript))
        if self.should_fail:
            raise MasterClientError("boom")
        return self.reply


def _voice_message() -> SignalMessage:
    return SignalMessage(
        sender="+15551234567",
        message="",
        attachments=[
            SignalAttachment(
                id="voice-note-1",
                content_type="audio/ogg",
                filename="voice.ogg",
                raw={},
            )
        ],
        raw={},
    )


@pytest.mark.asyncio
async def test_voice_note_ping_transcript_replies_locally_without_master() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient("from-master")

    sent = await process_inbound_message(
        _voice_message(),
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient("ping"),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [("pong", ["+15551234567"])]
    assert master_client.events == []


@pytest.mark.asyncio
async def test_voice_note_ping_prefix_transcript_echoes_remainder_locally() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient("from-master")

    sent = await process_inbound_message(
        _voice_message(),
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient("ping check this out"),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [("Pong: check this out", ["+15551234567"])]
    assert master_client.events == []


@pytest.mark.asyncio
async def test_voice_note_non_ping_transcript_routes_to_master() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient("from-master")

    sent = await process_inbound_message(
        _voice_message(),
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient("status please"),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [
        ("[thinking]", ["+15551234567"]),
        ("from-master", ["+15551234567"]),
    ]
    assert master_client.events == [("status please", "status please")]


@pytest.mark.asyncio
async def test_process_inbound_message_falls_back_without_master_reply() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient(None)
    message = SignalMessage(sender="+15551234567", message="hello", raw={})

    sent = await process_inbound_message(
        message,
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient(),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [
        ("[thinking]", ["+15551234567"]),
        ("You said: hello", ["+15551234567"]),
    ]
    assert master_client.events == [("hello", None)]


@pytest.mark.asyncio
async def test_process_inbound_message_falls_back_when_master_fails() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient(None, should_fail=True)
    message = SignalMessage(sender="+15551234567", message="hello", raw={})

    sent = await process_inbound_message(
        message,
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient(),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [
        ("[thinking]", ["+15551234567"]),
        ("You said: hello", ["+15551234567"]),
    ]
    assert master_client.events == [("hello", None)]


@pytest.mark.asyncio
async def test_process_inbound_message_ping_text_skips_master() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient("from-master")
    message = SignalMessage(sender="+15551234567", message="ping status?", raw={})

    sent = await process_inbound_message(
        message,
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient(),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [("Pong: status?", ["+15551234567"])]
    assert master_client.events == []


@pytest.mark.asyncio
async def test_process_inbound_message_does_not_send_thinking_for_direct_ping() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient("from-master")
    message = SignalMessage(sender="+15551234567", message="ping", raw={})

    sent = await process_inbound_message(
        message,
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient(),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [("pong", ["+15551234567"])]
    assert master_client.events == []


@pytest.mark.asyncio
async def test_handle_payload_logs_receipt_only_payload_at_debug(caplog) -> None:
    signal_client = FakeSignalClient()
    payload = [
        {"envelope": {"source": "uuid", "receiptMessage": {"isDelivery": True}}},
        {"envelope": {"source": "uuid", "receiptMessage": {"isRead": True}}},
    ]

    with caplog.at_level(logging.DEBUG, logger="app.main"):
        result = await handle_payload(
            payload,
            signal_client,  # type: ignore[arg-type]
            FakeTranscriptionClient(),  # type: ignore[arg-type]
            FakeMasterClient(None),  # type: ignore[arg-type]
        )

    assert result == {"messages_received": 0, "replies_sent": 0}
    assert any(
        record.levelno == logging.DEBUG and "receipt/typing/call" in record.message
        for record in caplog.records
    )
    assert not any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.asyncio
async def test_handle_payload_warns_on_unknown_payload_shape(caplog) -> None:
    signal_client = FakeSignalClient()
    payload = [{"envelope": {"source": "uuid", "mysteryMessage": {}}}]

    with caplog.at_level(logging.DEBUG, logger="app.main"):
        result = await handle_payload(
            payload,
            signal_client,  # type: ignore[arg-type]
            FakeTranscriptionClient(),  # type: ignore[arg-type]
            FakeMasterClient(None),  # type: ignore[arg-type]
        )

    assert result == {"messages_received": 0, "replies_sent": 0}
    assert any(record.levelno == logging.WARNING for record in caplog.records)
