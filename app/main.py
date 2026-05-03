import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request

from app.config import Settings, get_settings
from app.events import SignalMessage, extract_messages
from app.master_client import MasterClient, MasterClientError
from app.processor import build_response, is_ping
from app.signal_client import SignalApiError, SignalClient
from app.transcription import TranscriptionClient, TranscriptionError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def get_signal_client(settings: Settings = Depends(get_settings)) -> SignalClient:
    return SignalClient(settings.signal_api_url, settings.signal_number)


def get_transcription_client(
    settings: Settings = Depends(get_settings),
) -> TranscriptionClient:
    return TranscriptionClient(
        settings.transcription_api_url,
        settings.transcription_api_key,
        settings.transcription_model,
        settings.transcription_task,
    )


def get_master_client(settings: Settings = Depends(get_settings)) -> MasterClient:
    return MasterClient(
        settings.master_orchestrator_url,
        settings.master_orchestrator_enabled,
        settings.master_orchestrator_timeout_seconds,
    )


async def process_inbound_message(
    message: SignalMessage,
    client: SignalClient,
    transcription_client: TranscriptionClient,
    master_client: MasterClient | None = None,
) -> bool:
    if not message.should_reply:
        return False

    if not message.message.strip() and message.audio_attachments:
        attachment = message.audio_attachments[0]
        audio, content_type = await client.get_attachment(attachment.id)
        transcript = await transcription_client.transcribe(audio, attachment, content_type)
        response = await build_master_or_local_response(
            message,
            text=transcript,
            transcript=transcript,
            master_client=master_client,
        )
        await client.send_message(response, [message.sender])
        return True

    response = await build_master_or_local_response(
        message,
        text=message.message,
        transcript=None,
        master_client=master_client,
    )
    if not response:
        return False

    await client.send_message(response, [message.sender])
    return True


async def build_master_or_local_response(
    message: SignalMessage,
    *,
    text: str,
    transcript: str | None,
    master_client: MasterClient | None,
) -> str | None:
    local_message = message.model_copy(update={"message": text})

    if is_ping(text):
        return await build_response(local_message)

    if master_client is not None:
        try:
            response = await master_client.send_signal_event(
                message,
                text=text,
                transcript=transcript,
            )
            if response:
                return response
        except MasterClientError:
            logger.exception("Master orchestrator request failed; falling back to local processor")

    return await build_response(local_message)


async def handle_payload(
    payload: Any,
    client: SignalClient,
    transcription_client: TranscriptionClient,
    master_client: MasterClient | None = None,
) -> dict[str, int]:
    messages = extract_messages(payload)
    replies_sent = 0

    if messages:
        logger.info("Received %s Signal message(s)", len(messages))
    elif payload not in (None, []):
        logger.warning("Signal payload did not contain processable messages: %s", _summarize_payload(payload))

    for message in messages:
        try:
            if await process_inbound_message(message, client, transcription_client, master_client):
                replies_sent += 1
        except (SignalApiError, TranscriptionError):
            logger.exception("Failed to reply to Signal message from %s", message.sender)

    logger.info("Sent %s Signal reply/replies", replies_sent)
    return {"messages_received": len(messages), "replies_sent": replies_sent}


def _summarize_payload(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=True)[:2000]
    except TypeError:
        return repr(payload)[:2000]


async def poll_signal(settings: Settings) -> None:
    client = SignalClient(settings.signal_api_url, settings.signal_number)
    transcription_client = TranscriptionClient(
        settings.transcription_api_url,
        settings.transcription_api_key,
        settings.transcription_model,
        settings.transcription_task,
    )
    master_client = MasterClient(
        settings.master_orchestrator_url,
        settings.master_orchestrator_enabled,
        settings.master_orchestrator_timeout_seconds,
    )
    while True:
        try:
            payload = await client.receive(
                timeout_seconds=settings.poll_timeout_seconds,
                max_messages=settings.max_messages,
                send_read_receipts=settings.send_read_receipts,
                ignore_attachments=settings.ignore_attachments,
            )
            await handle_payload(payload, client, transcription_client, master_client)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Signal polling failed")
        await asyncio.sleep(settings.poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    task: asyncio.Task[None] | None = None

    if settings.poll_enabled:
        if not settings.signal_number:
            raise RuntimeError("SIGNAL_NUMBER is required when POLL_ENABLED=true")
        task = asyncio.create_task(poll_signal(settings))
        logger.info("Started Signal polling loop")

    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Signal Bot", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/signal/webhook")
async def signal_webhook(
    request: Request,
    client: SignalClient = Depends(get_signal_client),
    transcription_client: TranscriptionClient = Depends(get_transcription_client),
    master_client: MasterClient = Depends(get_master_client),
) -> dict[str, int]:
    payload = await request.json()
    return await handle_payload(payload, client, transcription_client, master_client)
