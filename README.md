# Signal Bot

Small FastAPI service that receives Signal messages through
[`signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api),
processes them, and replies through the `/v2/send` endpoint.

## What it does

- `POST /signal/webhook` accepts webhook-style payloads from `signal-cli-rest-api`.
- Optional polling opens `ws://.../v1/receive/{number}` and processes received messages.
- Replies are sent with `POST /v2/send`.
- Voice-message attachments are downloaded from `GET /v1/attachments/{id}`,
  converted to MP3 when needed, transcribed, and echoed back as transcript text.
- The initial processor replies `pong` to `ping` or `/ping`, returns help for `help`, and echoes everything else.

## Local setup

Create your environment file:

```sh
cp .env.example .env
```

Set `SIGNAL_NUMBER` in `.env` to the Signal number registered or linked with
`signal-cli-rest-api`, using international format.

Set `TRANSCRIPTION_API_KEY` in `.env` for voice-message transcription. Keep
`IGNORE_ATTACHMENTS=false`; attachments must be downloaded for voice messages to
be transcribed.

Run both services with Docker Compose where available:

```sh
docker compose up --build
```

Link Signal as a secondary device by opening:

```text
http://localhost:8080/v1/qrcodelink?device_name=signal-bot
```

Then scan the QR code from Signal on your phone under Settings > Linked devices.

This development server currently uses Podman directly for `signal-cli-rest-api`;
see [Development](docs/development.md) for those commands.

## Run without Docker

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Set `POLL_ENABLED=true` only when `signal-cli-rest-api` is already running and
`SIGNAL_NUMBER` is configured.

## Webhook mode

The app also accepts events at:

```text
POST http://localhost:8000/signal/webhook
```

Use that endpoint from a `signal-cli-rest-api` JSON-RPC webhook setup when you
prefer push delivery over polling. Polling remains the default Docker Compose
path because it works with native mode.

## Customize responses

Edit `app/processor.py`. Keep the function returning `str | None`; returning
`None` means no reply is sent.

For now, voice-message transcripts bypass the text processor and are returned
directly to the sender. Typed text still goes through `app/processor.py`.

Signal voice notes can arrive as AAC files. The bot converts AAC to MP3 with
`ffmpeg` before sending audio to the transcription endpoint, because the endpoint
may reject raw AAC.

The transcription request sends `task=transcribe` and leaves `language` unset, so
the model should preserve the detected spoken language instead of translating.

## Tests

```sh
pip install -r requirements-dev.txt
pytest
```

## Production

Production deployment and operations are documented in
[Production Operations](docs/production.md). Running `make` lists the available
production targets and their descriptions.

Code moves between dev and prod through GitHub: `make push` from one side,
`make pull` (or `make update` on prod, which also rebuilds and restarts) on the
other. The same flow works in reverse for hot-fixes made directly on
production. See the production doc for details.
