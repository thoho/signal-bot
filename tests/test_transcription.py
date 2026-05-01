import pytest

from app.events import SignalAttachment
from app.transcription import prepare_audio_for_transcription


@pytest.mark.asyncio
async def test_prepare_audio_leaves_mp3_unchanged() -> None:
    attachment = SignalAttachment(
        id="voice-note-1",
        content_type="audio/mpeg",
        filename="voice.mp3",
        raw={},
    )

    audio, filename, media_type = await prepare_audio_for_transcription(
        b"mp3-bytes",
        attachment,
        "audio/mpeg",
    )

    assert audio == b"mp3-bytes"
    assert filename == "voice.mp3"
    assert media_type == "audio/mpeg"
