import pytest

from app.events import SignalAttachment, SignalMessage
from app.master_client import MasterClientError
from app.main import process_inbound_message


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
    async def transcribe(self, audio: bytes, attachment: SignalAttachment, content_type: str) -> str:
        assert audio == b"audio-bytes"
        assert attachment.id == "voice-note-1"
        assert content_type == "audio/ogg"
        return "ping"


class FakeMasterClient:
    def __init__(self, reply: str | None, should_fail: bool = False) -> None:
        self.reply = reply
        self.should_fail = should_fail
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


@pytest.mark.asyncio
async def test_process_inbound_message_routes_voice_note_transcript_to_master() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient("pong")
    message = SignalMessage(
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

    sent = await process_inbound_message(
        message,
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient(),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [("pong", ["+15551234567"])]
    assert master_client.events == [("ping", "ping")]


@pytest.mark.asyncio
async def test_process_inbound_message_falls_back_without_master_reply() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient(None)
    message = SignalMessage(sender="+15551234567", message="ping", raw={})

    sent = await process_inbound_message(
        message,
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient(),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [("pong", ["+15551234567"])]
    assert master_client.events == [("ping", None)]


@pytest.mark.asyncio
async def test_process_inbound_message_falls_back_when_master_fails() -> None:
    signal_client = FakeSignalClient()
    master_client = FakeMasterClient(None, should_fail=True)
    message = SignalMessage(sender="+15551234567", message="ping", raw={})

    sent = await process_inbound_message(
        message,
        signal_client,  # type: ignore[arg-type]
        FakeTranscriptionClient(),  # type: ignore[arg-type]
        master_client,  # type: ignore[arg-type]
    )

    assert sent is True
    assert signal_client.sent_messages == [("pong", ["+15551234567"])]
    assert master_client.events == [("ping", None)]
