import asyncio
import json
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import websockets
from websockets.exceptions import InvalidStatus, WebSocketException

from app._retry import retry_request


class SignalApiError(RuntimeError):
    pass


class SignalClient:
    def __init__(self, base_url: str, number: str, max_attempts: int = 3) -> None:
        self.base_url = base_url.rstrip("/")
        self.number = number
        self.max_attempts = max_attempts

    async def send_message(self, message: str, recipients: list[str]) -> dict[str, Any]:
        payload = {
            "number": self.number,
            "recipients": recipients,
            "message": message,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await retry_request(
                lambda: client.post(f"{self.base_url}/v2/send", json=payload),
                attempts=self.max_attempts,
                label="signal-cli /v2/send",
            )
        if response.is_error:
            raise SignalApiError(
                f"signal-cli-rest-api send failed: {response.status_code} {response.text}"
            )
        if not response.content:
            return {}
        body: dict[str, Any] = response.json()
        return body

    async def receive(
        self,
        *,
        timeout_seconds: int,
        max_messages: int,
        send_read_receipts: bool,
        ignore_attachments: bool,
    ) -> Any:
        messages: list[Any] = []
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        try:
            async with websockets.connect(
                self._receive_websocket_url(),
                open_timeout=10,
                ping_interval=20,
                ping_timeout=20,
                proxy=None,
            ) as websocket:
                while len(messages) < max_messages:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                    except TimeoutError:
                        break
                    messages.append(_decode_websocket_message(raw))
        except InvalidStatus as exc:
            if exc.response.status_code != 200:
                raise SignalApiError(
                    f"signal-cli-rest-api websocket receive failed: {exc}"
                ) from exc
            return await self._receive_http(
                timeout_seconds=timeout_seconds,
                max_messages=max_messages,
                send_read_receipts=send_read_receipts,
                ignore_attachments=ignore_attachments,
            )
        except TimeoutError:
            return await self._receive_http(
                timeout_seconds=timeout_seconds,
                max_messages=max_messages,
                send_read_receipts=send_read_receipts,
                ignore_attachments=ignore_attachments,
            )
        except (OSError, WebSocketException) as exc:
            raise SignalApiError(f"signal-cli-rest-api websocket receive failed: {exc}") from exc
        return messages

    async def _receive_http(
        self,
        *,
        timeout_seconds: int,
        max_messages: int,
        send_read_receipts: bool,
        ignore_attachments: bool,
    ) -> Any:
        params: dict[str, str | int] = {
            "timeout": timeout_seconds,
            "max_messages": max_messages,
            "send_read_receipts": str(send_read_receipts).lower(),
            "ignore_attachments": str(ignore_attachments).lower(),
        }
        timeout = httpx.Timeout(
            timeout_seconds + 30,
            connect=10,
            read=timeout_seconds + 30,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/v1/receive/{self.number}", params=params
                )
            except httpx.ReadTimeout:
                return []
        if response.is_error:
            raise SignalApiError(
                f"signal-cli-rest-api receive failed: {response.status_code} {response.text}"
            )
        if not response.content:
            return []
        return response.json()

    async def get_attachment(self, attachment_id: str) -> tuple[bytes, str | None]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await retry_request(
                lambda: client.get(f"{self.base_url}/v1/attachments/{attachment_id}"),
                attempts=self.max_attempts,
                label="signal-cli /v1/attachments",
            )
        if response.is_error:
            raise SignalApiError(
                "signal-cli-rest-api attachment download failed: "
                f"{response.status_code} {response.text}"
            )
        return response.content, response.headers.get("content-type")

    def _receive_websocket_url(self) -> str:
        parsed = urlparse(self.base_url)
        if parsed.scheme == "https":
            scheme = "wss"
        elif parsed.scheme == "http":
            scheme = "ws"
        else:
            raise SignalApiError(f"Unsupported Signal API URL scheme: {parsed.scheme}")
        path = f"{parsed.path.rstrip('/')}/v1/receive/{self.number}"
        return urlunparse((scheme, parsed.netloc, path, "", "", ""))


def _decode_websocket_message(raw: str | bytes) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SignalApiError(f"signal-cli-rest-api receive returned non-JSON: {raw[:200]}") from exc
