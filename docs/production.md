# Production Operations

Production is expected to run two long-lived services:

- `signal-api.service`: a Podman-managed `signal-cli-rest-api` container.
- `signal-bot.service`: the FastAPI bot running from `/opt/signal-bot`.

The bot reads secrets and runtime config from `/etc/signal-bot.env`. That file is
not tracked by git.

## First Install

From a synced checkout on the production server:

```sh
make dependencies
make build
make install
```

Then edit:

```sh
sudoedit /etc/signal-bot.env
```

Required values:

```env
SIGNAL_NUMBER=+15551234567
TRANSCRIPTION_API_KEY=...
IGNORE_ATTACHMENTS=false
TRANSCRIPTION_TASK=transcribe
```

Start services:

```sh
make start
```

## Signal Linking

The Signal REST API listens only on localhost in production. Tunnel it from your
laptop:

```sh
ssh -L 18080:localhost:8080 user@production-host
```

Open:

```text
http://localhost:18080/v1/qrcodelink?device_name=signal-bot
```

Scan the QR code with Signal mobile under Settings > Linked devices.

Signal account data is stored in the Podman volume `signal-cli-data`, so it
persists across service restarts and host reboots.

## Routine Updates

The deployment now follows a GitHub-based workflow. After pushing changes from your development environment:

```sh
make update
```

This target performs a `git pull`, rebuilds the local environment, reinstalls files to `/opt/signal-bot`, and restarts the services.

Verify the update:

```sh
make test-api
```

## Useful Targets

```sh
make
make logs
make status
make stop
make start
make restart
make test
make test-api
```

## Notes

- `make install` preserves an existing `/etc/signal-bot.env`.
- `signal-api.service` binds `signal-cli-rest-api` to `127.0.0.1:8080`.
- `signal-bot.service` binds the bot to `127.0.0.1:8000`.
- Voice messages may arrive as AAC; the bot uses `ffmpeg` to convert them to MP3
  before transcription.
