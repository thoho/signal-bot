import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

import httpx

from app.events import SignalAttachment

logger = logging.getLogger(__name__)


class TranscriptionError(RuntimeError):
    pass


class TranscriptionClient:
    def __init__(self, api_url: str, api_key: str, model: str, task: str) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.task = task

    async def transcribe(
        self,
        audio: bytes,
        attachment: SignalAttachment,
        content_type: str | None,
    ) -> str:
        if not self.api_key:
            raise TranscriptionError("TRANSCRIPTION_API_KEY is not configured")

        audio, filename, media_type = await prepare_audio_for_transcription(
            audio,
            attachment,
            content_type,
        )
        headers = {"Authorization": f"Bearer {self.api_key}"}
        files = {"file": (filename, audio, media_type)}
        data = {"model": self.model, "task": self.task}

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                self.api_url,
                headers=headers,
                data=data,
                files=files,
            )

        if response.is_error:
            raise TranscriptionError(
                f"transcription failed: {response.status_code} {response.text}"
            )

        payload = response.json()
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise TranscriptionError("transcription response did not include text")

        return text.strip()


async def prepare_audio_for_transcription(
    audio: bytes,
    attachment: SignalAttachment,
    content_type: str | None,
) -> tuple[bytes, str, str]:
    filename = attachment.filename or attachment.id or "audio"
    media_type = content_type or attachment.content_type or "application/octet-stream"

    if not _should_convert(filename, media_type):
        return audio, filename, media_type

    if shutil.which("ffmpeg") is None:
        logger.warning("ffmpeg not found; sending original audio attachment to transcription API")
        return audio, filename, media_type

    return await _convert_audio_to_mp3(audio, filename)


def _should_convert(filename: str, media_type: str) -> bool:
    normalized_type = media_type.split(";")[0].strip().lower()
    normalized_filename = filename.lower()

    return normalized_type in {"audio/aac", "audio/x-aac"} or normalized_filename.endswith(".aac")


async def _convert_audio_to_mp3(audio: bytes, filename: str) -> tuple[bytes, str, str]:
    suffix = Path(filename).suffix or ".audio"

    with tempfile.TemporaryDirectory(prefix="signal-bot-audio-") as tmpdir:
        input_path = Path(tmpdir) / f"input{suffix}"
        output_path = Path(tmpdir) / "output.mp3"
        input_path.write_bytes(audio)

        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-codec:a",
            "libmp3lame",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error = stderr.decode("utf-8", errors="replace") or stdout.decode(
                "utf-8",
                errors="replace",
            )
            raise TranscriptionError(f"ffmpeg audio conversion failed: {error.strip()}")

        return output_path.read_bytes(), "audio.mp3", "audio/mpeg"
