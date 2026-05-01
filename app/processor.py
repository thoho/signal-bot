from app.events import SignalMessage


async def build_response(message: SignalMessage) -> str | None:
    text = message.message.strip()
    lowered = text.lower()

    if lowered in {"ping", "/ping"}:
        return "pong"

    if lowered in {"help", "/help"}:
        return "Send 'ping' and I will reply with 'pong'. Otherwise I echo your message."

    return f"You said: {text}"
