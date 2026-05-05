"""Coverage for FastAPI deps, the polling loop, lifespan, and webhook."""

import asyncio
import logging

import httpx
import pytest

from app.config import Settings
from app.main import (
    app,
    get_master_client,
    get_signal_client,
    get_transcription_client,
    handle_payload,
    poll_signal,
)


def test_get_signal_client_factory_uses_settings() -> None:
    settings = Settings(signal_api_url="http://s.test", signal_number="+1")
    client = get_signal_client(settings)

    assert client.base_url == "http://s.test"
    assert client.number == "+1"


def test_get_transcription_client_factory_uses_settings() -> None:
    settings = Settings(
        transcription_api_url="http://t.test",
        transcription_api_key="k",
        transcription_model="m",
        transcription_task="transcribe",
    )
    client = get_transcription_client(settings)

    assert client.api_url == "http://t.test"
    assert client.api_key == "k"
    assert client.model == "m"


def test_get_master_client_factory_uses_settings() -> None:
    settings = Settings(
        master_orchestrator_url="http://m.test",
        master_orchestrator_enabled=True,
        master_orchestrator_timeout_seconds=12.5,
    )
    client = get_master_client(settings)

    assert client.base_url == "http://m.test"
    assert client.enabled is True
    assert client.timeout_seconds == 12.5


def test_settings_defaults_are_lower_latency() -> None:
    settings = Settings()

    assert settings.poll_timeout_seconds == 10
    assert settings.poll_interval_seconds == 0.2


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_signal_webhook_routes_payload_through_processor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_handle_payload(payload, *_args, **_kwargs):
        captured["payload"] = payload
        return {"messages_received": 0, "replies_sent": 0}

    monkeypatch.setattr("app.main.handle_payload", fake_handle_payload)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post("/signal/webhook", json=[{"envelope": {}}])

    assert response.status_code == 200
    assert response.json() == {"messages_received": 0, "replies_sent": 0}
    assert captured["payload"] == [{"envelope": {}}]


@pytest.mark.asyncio
async def test_handle_payload_processes_dict_envelope_with_unknown_shape(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A dict (not a list) with no recognizable message keys → WARNING."""

    class DummyClient:
        async def get_attachment(self, _id):
            raise AssertionError("should not be called")

        async def send_message(self, *args, **kwargs):
            raise AssertionError("should not be called")

    class DummyTrans:
        async def transcribe(self, *_args, **_kwargs):
            raise AssertionError("should not be called")

    payload = {"envelope": {"sourceNumber": "+1", "mysteryMessage": {}}}

    with caplog.at_level(logging.DEBUG, logger="app.main"):
        result = await handle_payload(
            payload,
            DummyClient(),  # type: ignore[arg-type]
            DummyTrans(),  # type: ignore[arg-type]
            None,
        )

    assert result == {"messages_received": 0, "replies_sent": 0}
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


@pytest.mark.asyncio
async def test_handle_payload_skips_processing_when_payload_is_none() -> None:
    class DummyClient:
        async def get_attachment(self, _id): ...
        async def send_message(self, *args, **kwargs): ...

    class DummyTrans:
        async def transcribe(self, *_args, **_kwargs): ...

    result = await handle_payload(
        None, DummyClient(), DummyTrans(), None  # type: ignore[arg-type]
    )

    assert result == {"messages_received": 0, "replies_sent": 0}


@pytest.mark.asyncio
async def test_handle_payload_logs_when_signal_send_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.signal_client import SignalApiError

    class FailingSignal:
        async def send_message(self, *args, **kwargs):
            raise SignalApiError("send blew up")

        async def get_attachment(self, _id):
            raise AssertionError("not used")

    class DummyTrans:
        async def transcribe(self, *_args, **_kwargs): ...

    payload = [
        {"envelope": {"sourceNumber": "+15551234567", "dataMessage": {"message": "hi"}}}
    ]

    with caplog.at_level(logging.ERROR, logger="app.main"):
        result = await handle_payload(
            payload,
            FailingSignal(),  # type: ignore[arg-type]
            DummyTrans(),  # type: ignore[arg-type]
            None,
        )

    assert result == {"messages_received": 1, "replies_sent": 0}
    assert any("Failed to reply" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_poll_signal_loops_then_cancels_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify poll_signal calls receive + handle_payload, then exits on cancel."""

    settings = Settings(
        signal_number="+1",
        signal_api_url="http://signal.test",
        master_orchestrator_url="http://master.test",
        master_orchestrator_enabled=False,
        poll_interval_seconds=0.0,
    )

    receives: list[int] = []
    handles: list[object] = []

    class FakeReceiveClient:
        def __init__(self, *_args, **_kwargs) -> None: ...

        async def receive(self, **_kwargs):
            receives.append(1)
            if len(receives) >= 2:
                # Force cancellation on the 2nd loop so the test terminates.
                raise asyncio.CancelledError
            return [{"envelope": {}}]

    async def fake_handle_payload(payload, *args, **kwargs):
        handles.append(payload)
        return {"messages_received": 0, "replies_sent": 0}

    monkeypatch.setattr("app.main.SignalClient", FakeReceiveClient)
    monkeypatch.setattr("app.main.TranscriptionClient", lambda *a, **k: object())
    monkeypatch.setattr("app.main.MasterClient", lambda *a, **k: object())
    monkeypatch.setattr("app.main.handle_payload", fake_handle_payload)

    with pytest.raises(asyncio.CancelledError):
        await poll_signal(settings)

    assert len(receives) == 2
    assert handles == [[{"envelope": {}}]]


@pytest.mark.asyncio
async def test_poll_signal_swallows_unexpected_error_then_continues(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = Settings(
        signal_number="+1",
        master_orchestrator_enabled=False,
        poll_interval_seconds=0.0,
    )

    state = {"calls": 0}

    class BoomThenCancel:
        def __init__(self, *_args, **_kwargs) -> None: ...

        async def receive(self, **_kwargs):
            state["calls"] += 1
            if state["calls"] == 1:
                raise RuntimeError("transient")
            raise asyncio.CancelledError

    monkeypatch.setattr("app.main.SignalClient", BoomThenCancel)
    monkeypatch.setattr("app.main.TranscriptionClient", lambda *a, **k: object())
    monkeypatch.setattr("app.main.MasterClient", lambda *a, **k: object())

    with (
        caplog.at_level(logging.ERROR, logger="app.main"),
        pytest.raises(asyncio.CancelledError),
    ):
        await poll_signal(settings)

    assert state["calls"] == 2
    assert any("Signal polling failed" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_lifespan_starts_and_cancels_polling_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When poll_enabled=True, lifespan starts poll_signal and cancels it cleanly."""
    from app.main import lifespan

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_poll(_settings):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr("app.main.poll_signal", fake_poll)
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(poll_enabled=True, signal_number="+1"),
    )

    async with lifespan(app):
        await asyncio.wait_for(started.wait(), timeout=1.0)

    await asyncio.wait_for(cancelled.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_lifespan_requires_signal_number_when_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import lifespan

    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(poll_enabled=True, signal_number=""),
    )

    with pytest.raises(RuntimeError, match="SIGNAL_NUMBER"):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_skips_polling_task_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import lifespan

    called = False

    async def should_not_run(_settings):
        nonlocal called
        called = True

    monkeypatch.setattr("app.main.poll_signal", should_not_run)
    monkeypatch.setattr(
        "app.main.get_settings", lambda: Settings(poll_enabled=False)
    )

    async with lifespan(app):
        pass

    assert called is False


@pytest.mark.asyncio
async def test_process_inbound_message_returns_false_when_should_reply_is_false() -> None:
    from app.events import SignalMessage
    from app.main import process_inbound_message

    class DummyClient:
        async def send_message(self, *args, **kwargs):
            raise AssertionError("should not send")

        async def get_attachment(self, _id): ...

    class DummyTrans:
        async def transcribe(self, *args, **kwargs): ...

    # No text and no audio → should_reply is False.
    message = SignalMessage(sender="+1", message="", attachments=[], raw={})

    result = await process_inbound_message(
        message,
        DummyClient(),  # type: ignore[arg-type]
        DummyTrans(),  # type: ignore[arg-type]
        None,
    )

    assert result is False


@pytest.mark.asyncio
async def test_process_inbound_message_returns_false_when_response_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.events import SignalMessage
    from app.main import process_inbound_message

    class DummyClient:
        async def send_message(self, *args, **kwargs):
            raise AssertionError("should not send")

        async def get_attachment(self, _id): ...

    class DummyTrans:
        async def transcribe(self, *args, **kwargs): ...

    async def empty_response(*args, **kwargs):
        return None

    monkeypatch.setattr("app.main.build_master_or_local_response", empty_response)

    message = SignalMessage(sender="+1", message="hi", raw={})

    result = await process_inbound_message(
        message,
        DummyClient(),  # type: ignore[arg-type]
        DummyTrans(),  # type: ignore[arg-type]
        None,
    )

    assert result is False


@pytest.mark.asyncio
async def test_handle_payload_increments_replies_sent_on_success() -> None:
    from app.main import handle_payload

    sent: list[tuple[str, list[str]]] = []

    class OkClient:
        async def send_message(self, message: str, recipients: list[str]) -> dict:
            sent.append((message, recipients))
            return {}

        async def get_attachment(self, _id):
            raise AssertionError("not used")

    class DummyTrans:
        async def transcribe(self, *args, **kwargs): ...

    payload = [
        {"envelope": {"sourceNumber": "+15551234567", "dataMessage": {"message": "ping"}}}
    ]

    result = await handle_payload(
        payload,
        OkClient(),  # type: ignore[arg-type]
        DummyTrans(),  # type: ignore[arg-type]
        None,
    )

    assert result == {"messages_received": 1, "replies_sent": 1}
    assert sent == [("pong", ["+15551234567"])]


@pytest.mark.asyncio
async def test_handle_payload_drops_stale_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import handle_payload

    sent: list[tuple[str, list[str]]] = []

    class OkClient:
        async def send_message(self, message: str, recipients: list[str]) -> dict:
            sent.append((message, recipients))
            return {}

        async def get_attachment(self, _id):
            raise AssertionError("not used")

    class DummyTrans:
        async def transcribe(self, *args, **kwargs): ...

    monkeypatch.setattr("app.main.time.time", lambda: 1_710_000_600)

    payload = [
        {
            "envelope": {
                "sourceNumber": "+15551234567",
                "timestamp": 1_710_000_000_000,
                "dataMessage": {"message": "ping"},
            }
        }
    ]

    result = await handle_payload(
        payload,
        OkClient(),  # type: ignore[arg-type]
        DummyTrans(),  # type: ignore[arg-type]
        None,
        max_message_age_seconds=300,
    )

    assert result == {"messages_received": 0, "replies_sent": 0}
    assert sent == []


def test_summarize_payload_handles_unjson_serializable_objects() -> None:
    from app.main import _summarize_payload

    class NotJsonable:
        def __repr__(self) -> str:
            return "<custom>"

    assert _summarize_payload(NotJsonable()) == "<custom>"
