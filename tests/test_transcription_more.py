"""Coverage for TranscriptionClient and the ffmpeg conversion branch."""

import asyncio
import logging
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from app.events import SignalAttachment
from app.transcription import (
    TranscriptionClient,
    TranscriptionError,
    _convert_audio_to_mp3,
    _should_convert,
    prepare_audio_for_transcription,
)


def _attachment(
    *,
    aid: str = "voice-note-1",
    content_type: str | None = "audio/ogg",
    filename: str | None = "voice.ogg",
) -> SignalAttachment:
    return SignalAttachment(id=aid, content_type=content_type, filename=filename, raw={})


def test_should_convert_recognizes_aac_by_mime_and_extension() -> None:
    assert _should_convert("clip.aac", "audio/aac") is True
    assert _should_convert("clip.aac", "audio/x-aac") is True
    assert _should_convert("CLIP.AAC", "application/octet-stream") is True
    assert _should_convert("voice.ogg", "audio/ogg") is False


@pytest.mark.asyncio
async def test_transcription_client_unconfigured_raises_immediately() -> None:
    client = TranscriptionClient(
        "http://t.test/v1/audio/transcriptions",
        api_key="",
        model="m",
        task="transcribe",
    )

    with pytest.raises(TranscriptionError, match="not configured"):
        await client.transcribe(b"audio", _attachment(), "audio/ogg")


@pytest.mark.asyncio
@respx.mock
async def test_transcription_client_returns_text_on_success() -> None:
    respx.post("http://t.test/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": " hello world "})
    )
    client = TranscriptionClient(
        "http://t.test/v1/audio/transcriptions",
        api_key="k",
        model="m",
        task="transcribe",
    )

    result = await client.transcribe(b"audio-bytes", _attachment(), "audio/ogg")

    assert result == "hello world"


@pytest.mark.asyncio
@respx.mock
async def test_transcription_client_raises_on_5xx() -> None:
    respx.post("http://t.test/v1/audio/transcriptions").mock(
        return_value=httpx.Response(500, text="upstream down")
    )
    client = TranscriptionClient(
        "http://t.test/v1/audio/transcriptions",
        api_key="k",
        model="m",
        task="transcribe",
    )

    with pytest.raises(TranscriptionError, match="transcription failed"):
        await client.transcribe(b"audio-bytes", _attachment(), "audio/ogg")


@pytest.mark.asyncio
@respx.mock
async def test_transcription_client_raises_when_text_field_missing_or_blank() -> None:
    respx.post("http://t.test/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "   "})
    )
    client = TranscriptionClient(
        "http://t.test/v1/audio/transcriptions",
        api_key="k",
        model="m",
        task="transcribe",
    )

    with pytest.raises(TranscriptionError, match="did not include text"):
        await client.transcribe(b"audio-bytes", _attachment(), "audio/ogg")


@pytest.mark.asyncio
@respx.mock
async def test_transcription_client_retries_503_then_succeeds() -> None:
    respx.post("http://t.test/v1/audio/transcriptions").mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"text": "hello"}),
        ]
    )
    client = TranscriptionClient(
        "http://t.test/v1/audio/transcriptions",
        api_key="k",
        model="m",
        task="transcribe",
    )

    result = await client.transcribe(b"audio", _attachment(), "audio/ogg")

    assert result == "hello"


@pytest.mark.asyncio
async def test_prepare_audio_falls_back_when_ffmpeg_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("app.transcription.shutil.which", lambda _name: None)
    attachment = _attachment(aid="clip", content_type="audio/aac", filename="clip.aac")

    with caplog.at_level(logging.WARNING, logger="app.transcription"):
        audio, filename, media_type = await prepare_audio_for_transcription(
            b"raw-aac", attachment, "audio/aac"
        )

    assert audio == b"raw-aac"
    assert filename == "clip.aac"
    assert media_type == "audio/aac"
    assert any("ffmpeg not found" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_convert_audio_to_mp3_runs_ffmpeg_and_returns_mp3_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Stub out subprocess so we exercise the ffmpeg branch without ffmpeg."""

    async def fake_create_subprocess_exec(*args, **kwargs):
        # ffmpeg's last positional arg is the output path. Write a fake MP3 there.
        output_path = args[-1]
        with open(output_path, "wb") as f:
            f.write(b"ID3-fake-mp3")

        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    audio, filename, media_type = await _convert_audio_to_mp3(b"raw-aac", "clip.aac")

    assert audio == b"ID3-fake-mp3"
    assert filename == "audio.mp3"
    assert media_type == "audio/mpeg"


@pytest.mark.asyncio
async def test_convert_audio_to_mp3_raises_on_ffmpeg_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_subprocess_exec(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"unsupported codec"))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(TranscriptionError, match="unsupported codec"):
        await _convert_audio_to_mp3(b"raw-aac", "clip.aac")


@pytest.mark.asyncio
async def test_prepare_audio_invokes_conversion_when_aac_and_ffmpeg_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.transcription.shutil.which", lambda _name: "/usr/bin/ffmpeg")

    async def fake_create_subprocess_exec(*args, **kwargs):
        output_path = args[-1]
        with open(output_path, "wb") as f:
            f.write(b"converted")

        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    attachment = _attachment(aid="c", content_type="audio/aac", filename="c.aac")

    audio, filename, media_type = await prepare_audio_for_transcription(
        b"raw-aac", attachment, "audio/aac"
    )

    assert audio == b"converted"
    assert filename == "audio.mp3"
    assert media_type == "audio/mpeg"
