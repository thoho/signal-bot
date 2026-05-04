from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SignalAttachment(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    content_type: str | None = None
    filename: str | None = None
    raw: dict[str, Any]

    @property
    def is_audio(self) -> bool:
        content_type = (self.content_type or "").lower()
        filename = (self.filename or self.id).lower()

        if content_type.startswith("audio/"):
            return True

        if content_type in {"application/ogg", "video/ogg"}:
            return True

        return filename.endswith(
            (".aac", ".aiff", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".webm")
        )


class SignalMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    sender: str
    message: str
    timestamp: int | None = None
    group_id: str | None = None
    attachments: list[SignalAttachment] = Field(default_factory=list)
    raw: dict[str, Any]

    @property
    def should_reply(self) -> bool:
        return bool(self.sender and (self.message.strip() or self.audio_attachments))

    @property
    def audio_attachments(self) -> list[SignalAttachment]:
        return [attachment for attachment in self.attachments if attachment.is_audio]


def extract_messages(payload: Any) -> list[SignalMessage]:
    """Normalize signal-cli-rest-api receive/webhook payloads into bot messages."""
    if payload is None:
        return []

    if isinstance(payload, list):
        items = payload
    else:
        items = [payload]

    messages: list[SignalMessage] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        envelope = _extract_envelope(item)
        data = _extract_data_message(envelope)
        if not isinstance(data, dict):
            continue

        sender = (
            envelope.get("sourceNumber")
            or envelope.get("source")
            or envelope.get("sourceUuid")
            or ""
        )
        if not isinstance(sender, str) or not sender:
            continue

        body = data.get("message") or data.get("body")
        if not isinstance(body, str):
            body = ""

        attachments = _extract_attachments(data)
        if not body.strip() and not attachments:
            continue

        group_id = None
        group_info = data.get("groupInfo")
        if isinstance(group_info, dict):
            group_id_value = group_info.get("groupId")
            if isinstance(group_id_value, str):
                group_id = group_id_value

        timestamp = envelope.get("timestamp") or data.get("timestamp")
        if not isinstance(timestamp, int):
            timestamp = None

        messages.append(
            SignalMessage(
                sender=sender,
                message=body.strip(),
                timestamp=timestamp,
                group_id=group_id,
                attachments=attachments,
                raw=item,
            )
        )

    return messages


def _extract_envelope(item: dict[str, Any]) -> dict[str, Any]:
    envelope = item.get("envelope")
    if isinstance(envelope, dict):
        return envelope

    params = item.get("params")
    if isinstance(params, dict):
        result = params.get("result")
        if isinstance(result, dict) and isinstance(result.get("envelope"), dict):
            return result["envelope"]

        if isinstance(params.get("envelope"), dict):
            return params["envelope"]

    return item


def _extract_data_message(envelope: dict[str, Any]) -> dict[str, Any] | None:
    data_message = envelope.get("dataMessage")
    if isinstance(data_message, dict):
        return data_message

    sync_message = envelope.get("syncMessage")
    if isinstance(sync_message, dict):
        sent_message = sync_message.get("sentMessage")
        if isinstance(sent_message, dict):
            return sent_message

    return None


_KNOWN_NON_MESSAGE_KEYS = ("receiptMessage", "typingMessage", "callMessage")


def is_known_non_message_envelope(item: Any) -> bool:
    """True if the item is a Signal envelope we recognize but won't reply to.

    Signal-cli forwards delivery/read receipts, typing indicators, call
    signaling, and sync receipts alongside real messages. They are
    expected traffic, not a sign of a malformed payload.
    """
    if not isinstance(item, dict):
        return False
    envelope = _extract_envelope(item)
    if any(isinstance(envelope.get(k), dict) for k in _KNOWN_NON_MESSAGE_KEYS):
        return True
    sync_message = envelope.get("syncMessage")
    if isinstance(sync_message, dict) and not isinstance(sync_message.get("sentMessage"), dict):
        return True
    return False


def _extract_attachments(data: dict[str, Any]) -> list[SignalAttachment]:
    raw_attachments = data.get("attachments")
    if not isinstance(raw_attachments, list):
        return []

    attachments: list[SignalAttachment] = []
    for raw_attachment in raw_attachments:
        if not isinstance(raw_attachment, dict):
            continue

        attachment_id = (
            raw_attachment.get("id")
            or raw_attachment.get("attachmentId")
            or raw_attachment.get("filename")
        )
        if not isinstance(attachment_id, str) or not attachment_id:
            continue

        content_type = raw_attachment.get("contentType") or raw_attachment.get("content_type")
        if not isinstance(content_type, str):
            content_type = None

        filename = raw_attachment.get("filename")
        if not isinstance(filename, str):
            filename = None

        attachments.append(
            SignalAttachment(
                id=attachment_id,
                content_type=content_type,
                filename=filename,
                raw=raw_attachment,
            )
        )

    return attachments
