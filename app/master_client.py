from typing import Any

import httpx

from app.events import SignalMessage


class MasterClientError(RuntimeError):
    pass


class MasterClient:
    def __init__(self, base_url: str, enabled: bool, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds

    async def send_signal_event(
        self,
        message: SignalMessage,
        *,
        text: str,
        transcript: str | None = None,
    ) -> str | None:
        if not self.enabled:
            return None

        payload: dict[str, Any] = {
            "sender": message.sender,
            "text": text,
            "transcript": transcript,
            "source_message_id": str(message.timestamp) if message.timestamp is not None else None,
            "message_timestamp": message.timestamp,
            "metadata": {
                "group_id": message.group_id,
                "attachment_count": len(message.attachments),
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/v1/events/signal", json=payload)
        except httpx.HTTPError as exc:
            raise MasterClientError(f"Master orchestrator request failed: {exc}") from exc

        if response.is_error:
            raise MasterClientError(
                f"Master orchestrator request failed: {response.status_code} {response.text}"
            )

        body = response.json()
        reply = body.get("reply")
        if isinstance(reply, str) and reply.strip():
            return reply
        return None
