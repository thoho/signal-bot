import pytest

from app.events import SignalAttachment, SignalMessage
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


@pytest.mark.asyncio
async def test_process_inbound_message_replies_with_voice_note_transcript() -> None:
    signal_client = FakeSignalClient()
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
    )

    assert sent is True
    assert signal_client.sent_messages == [("ping", ["+15551234567"])]
