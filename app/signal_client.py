from typing import Any

import httpx


class SignalApiError(RuntimeError):
    pass


class SignalClient:
    def __init__(self, base_url: str, number: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.number = number

    async def send_message(self, message: str, recipients: list[str]) -> dict[str, Any]:
        payload = {
            "number": self.number,
            "recipients": recipients,
            "message": message,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{self.base_url}/v2/send", json=payload)
        if response.is_error:
            raise SignalApiError(
                f"signal-cli-rest-api send failed: {response.status_code} {response.text}"
            )
        if not response.content:
            return {}
        return response.json()

    async def receive(
        self,
        *,
        timeout_seconds: int,
        max_messages: int,
        send_read_receipts: bool,
        ignore_attachments: bool,
    ) -> Any:
        params = {
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
            response = await client.get(f"{self.base_url}/v1/attachments/{attachment_id}")
        if response.is_error:
            raise SignalApiError(
                "signal-cli-rest-api attachment download failed: "
                f"{response.status_code} {response.text}"
            )
        return response.content, response.headers.get("content-type")
