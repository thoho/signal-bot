# Production Operations

Production is expected to run two long-lived services:

- `signal-api.service`: a Podman-managed `signal-cli-rest-api` container.
- `signal-bot.service`: the FastAPI bot running from `/opt/signal-bot`.

The bot reads secrets and runtime config from `/etc/signal-bot.env`. That file is
not tracked by git.

## First Install

Clone the repository to a suitable location (e.g., your home directory) on the production server:

```sh
git clone https://github.com/thoho/signal-bot.git
cd signal-bot
```

Then run the installation targets:

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

## Routine Updates (dev → prod)

Code moves from development to production through GitHub. The legacy `sync.sh`
rsync script has been removed and must not be reintroduced.

On the development host, after committing your changes:

```sh
make push
```

On the production host, to apply them:

```sh
make update
```

`make update` runs `make pull` (fast-forward pull from origin), then rebuilds the
local environment, reinstalls files to `/opt/signal-bot`, and restarts the
services.

Verify the update:

```sh
make test-api
```

## Hot-fix Flow (prod → dev)

If a fix has to be made directly on the production host, push it back through
GitHub so the development checkout stays in sync:

1. On the production host, in the production checkout (typically the cloned
   repo, not `/opt/signal-bot`):

   ```sh
   make pull              # make sure prod has any pending dev commits first
   # edit files, then:
   git add <changed-files>
   git commit -m "<hot-fix description>"
   make push
   ```

2. Apply the change to the running services:

   ```sh
   make update
   ```

3. On the development host:

   ```sh
   make pull
   ```

The `make pull` step on the development host pulls the hot-fix commit into the
working tree without rebuilding or restarting anything.

If `make push` reports that the working tree is dirty or that origin has
diverging commits, resolve those first — never force-push from production.

## Useful Targets

```sh
make            # same as `make help`; lists all targets
make push
make pull
make update
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
