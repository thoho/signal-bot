import re

from app.events import SignalMessage

_PING_PREFIX = re.compile(r"^\s*/?ping\b\s*", re.IGNORECASE)


def is_ping(text: str) -> bool:
    return bool(_PING_PREFIX.match(text or ""))


def build_ping_reply(text: str) -> str:
    rest = _PING_PREFIX.sub("", text or "", count=1).strip()
    if not rest:
        return "pong"
    return f"Pong: {rest}"


async def build_response(message: SignalMessage) -> str | None:
    text = message.message.strip()
    lowered = text.lower()

    if is_ping(text):
        return build_ping_reply(text)

    if lowered in {"help", "/help"}:
        return "Send 'ping' and I will reply with 'pong'. Otherwise I echo your message."

    return f"You said: {text}"
