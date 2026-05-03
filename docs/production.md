# Production Operations

Production runs as the unprivileged `signal-bot` user via **user-mode systemd**, with two long-lived services:

- `signal-api.service`: a rootless Podman container running `signal-cli-rest-api`.
- `signal-bot.service`: the FastAPI bot running from `~signal-bot/signal-bot/`.

Runtime config and secrets live in `~signal-bot/.config/signal-bot.env` (mode 600, not tracked by git). Daily operations are run as `signal-bot` and require no `sudo`.

## First Install

The repo is expected at `~signal-bot/signal-bot/`. The `signal-bot` user holds an SSH deploy key for git pull/push.

### One-time root setup

These steps need root and only run once on a fresh host (or when migrating off the old root-managed setup). Run them from an account with `sudo`:

```sh
# 1. (Migration only) Stop and remove the old root-managed services
sudo systemctl stop signal-bot signal-api
sudo systemctl disable signal-bot signal-api
sudo rm -f /etc/systemd/system/signal-bot.service /etc/systemd/system/signal-api.service
sudo systemctl daemon-reload

# 2. (Migration only) Export the existing signal-cli-data volume so we don't have to re-link Signal
sudo podman volume export signal-cli-data -o /tmp/signal-cli-data.tar
sudo chown signal-bot:signal-bot /tmp/signal-cli-data.tar

# 3. (Migration only) Remove the old install tree and env file
sudo rm -rf /opt/signal-bot /etc/signal-bot.env

# 4. Allow signal-bot's user-mode systemd to start at boot without an active login
sudo loginctl enable-linger signal-bot
```

### Setup as `signal-bot`

SSH in as `signal-bot`:

```sh
cd ~/signal-bot
make dependencies              # checks for ffmpeg/podman/etc.; if anything is missing it
                               # prints the apt command for a sudoer to run, then re-run this
make build
make install                   # seeds ~/.config/signal-bot.env from .env.example, installs user units
$EDITOR ~/.config/signal-bot.env   # set SIGNAL_NUMBER, TRANSCRIPTION_API_KEY, etc.
```

If you exported the old volume in step 2 above, import it now so Signal stays linked:

```sh
make import-signal-volume
```

Otherwise you'll re-link via QR after `make start` — see [Signal Linking](#signal-linking).

Start the services:

```sh
make start
make test-api
```

## Signal Linking

The Signal REST API listens only on localhost in production. Tunnel it from your laptop:

```sh
ssh -L 18080:localhost:8080 signal-bot@production-host
```

Open:

```text
http://localhost:18080/v1/qrcodelink?device_name=signal-bot
```

Scan the QR code with Signal mobile under Settings > Linked devices. Account data persists in the rootless Podman volume `signal-cli-data` under `~signal-bot/.local/share/containers/`.

## Routine Updates (dev → prod)

Code moves from development to production through GitHub. The legacy `sync.sh`
rsync script has been removed and must not be reintroduced.

On the development host, after committing your changes:

```sh
make push
```

On the production host, to apply them:

```sh
ssh signal-bot@production-host
cd ~/signal-bot
make update
```

`make update` runs `make pull` (fast-forward pull from origin), then rebuilds
the venv, refreshes the user-mode systemd units, and restarts the services. No
`sudo`.

Verify the update:

```sh
make test-api
```

## Hot-fix Flow (prod → dev)

If a fix has to be made directly on the production host, push it back through
GitHub so the development checkout stays in sync:

1. On the production host, SSHed in as `signal-bot`, in `~/signal-bot`:

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

- `make install` preserves an existing `~/.config/signal-bot.env`.
- `signal-api.service` runs rootless Podman; the container is bound to `127.0.0.1:8080`.
- `signal-bot.service` binds uvicorn to `127.0.0.1:8000`.
- Voice messages may arrive as AAC; the bot uses `ffmpeg` to convert them to MP3
  before transcription.
