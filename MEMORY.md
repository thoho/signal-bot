# MEMORY.md — Session Continuation

This file is a handoff note from a session running on the dev host
(`/home/tomme/src/signal-bot`) to a session running on the production host
(`~signal-bot/signal-bot`). Read it first.

## Where we are right now (2026-05-03)

Mid-cutover from a root-managed systemd setup to a sudo-free, user-mode systemd
setup running as the unprivileged `signal-bot` user. The cutover is structurally
complete; we are in the **final verification step**: getting the bot to actually
receive a Signal message and reply.

## Immediate next step

The latest fix (commit 8ec623b) addresses a systemd quirk where
`EnvironmentFile=` shadowed the unit's `Environment=POLL_ENABLED=true`, leaving
polling silently off.

Run on prod as `signal-bot`:

```sh
cd ~/signal-bot
make pull                                                                  # picks up 8ec623b
make install                                                               # refreshes unit + daemon-reload
sed -i 's/^POLL_ENABLED=.*/POLL_ENABLED=true/' ~/.config/signal-bot.env    # if not already done
grep ^POLL_ENABLED ~/.config/signal-bot.env                                # confirm =true
make restart
journalctl --user-unit signal-bot.service -n 30 --no-pager
```

Success criteria:

1. Log shows `INFO:app.main:Started Signal polling loop`.
2. Sending `ping` from `+46709278320` to `+46702770276` produces `pong` back
   within a couple of seconds and a log line `Sent 1 Signal reply/replies`.

If polling logs appear but no message is seen on poll: check
`curl -s http://localhost:8080/v1/accounts; echo` → must list `+46702770276`.

## Phone numbers (DO NOT confuse — we already burned an hour on this)

- `+46702770276` — the **bot's** Signal account; what `signal-cli-rest-api` is
  linked as; what `SIGNAL_NUMBER` in the env file must equal; what messages are
  sent **to**.
- `+46709278320` — the user's **personal** phone; what test messages are sent
  **from**.

The user re-linked via QR earlier today (the original root-podman volume was
lost during cutover, so prior linking history is gone; account is fresh).

## Prod facts

- Host: `personal-assistant.protection-now.com`
- User: `signal-bot`, no sudo. For any root-required step, print the commands
  for the user to paste to a sudoer; do not attempt `sudo` from a Make recipe.
- Repo: `~/signal-bot/` — the cloned working tree IS the install (no `/opt`).
- Env file: `~/.config/signal-bot.env` (mode 600). **Single source of runtime
  config.** Do not add `Environment=` overrides to the unit.
- Systemd units: `~/.config/systemd/user/signal-{api,bot}.service` (user-mode,
  linger enabled).
- Services: `signal-api.service` (rootless Podman container of
  `signal-cli-rest-api`, MODE=native, bound to 127.0.0.1:8080) and
  `signal-bot.service` (uvicorn on 127.0.0.1:8000).
- Operator workflow is entirely via `make` — `make help` for the target list.

## Architectural decisions from this session (don't undo without good reason)

1. **Operator = `signal-bot` user, via direct SSH** (not `sudo -iu` from
   another account). User has its own SSH deploy key for git pull/push.
2. **No `User=` in unit files** — they run under signal-bot's user-mode
   systemd instance.
3. **Repo IS the install.** No rsync to `/opt`. `WorkingDirectory=%h/signal-bot`.
4. **Env file is single source of truth.** Do not re-add `Environment=` lines
   to the unit; systemd's merge order with `EnvironmentFile=` is unreliable.
5. **Rootless Podman** for signal-api; volume `signal-cli-data` under
   `~signal-bot/.local/share/containers/`.
6. **Makefile dependencies are checked, not auto-installed.** If anything is
   missing, the target prints the apt command and exits 1; the user pastes it
   to a sudoer. Same pattern for any other root-needing step.

## Known gotchas

- `systemctl --user` needs `XDG_RUNTIME_DIR`. The Makefile sets it; the user
  also has `export XDG_RUNTIME_DIR=/run/user/$(id -u)` in `~/.bashrc` for
  direct shell use.
- `loginctl enable-linger signal-bot` was run by the sudoer. Do not undo.
- `podman volume create` exits 125 if the volume already exists. The
  signal-api unit's `ExecStartPre` for it is prefixed with `-` to ignore that.
- `podman volume rm` races with `make stop` because the container's `--rm`
  cleanup hasn't finished. Always: `make stop && podman rm -f signal-api &&
  podman volume rm signal-cli-data`.
- After editing a unit file, run `make install` (it does `daemon-reload`);
  `make restart` alone does not pick up unit changes.
- `systemctl --user show <svc> -p Environment` shows ONLY the unit's
  `Environment=` directive, not the merged env. To see what the running
  process actually has:
  ```sh
  cat /proc/$(systemctl --user show signal-bot.service -p MainPID --value)/environ \
    | tr '\0' '\n' | grep -E '^(POLL|SIGNAL)'
  ```
- pydantic-settings precedence is correct (env > .env file). Don't blame
  pydantic for env-related surprises; suspect systemd merging first.

## Deferred work (out of scope until Signal comms are green)

- **Master orchestrator integration.** `MASTER_ORCHESTRATOR_*` settings exist
  in `app/config.py`; the plumbing in `app/master_client.py` +
  `app/main.py:build_master_or_local_response` forwards inbound text/transcripts
  to `/v1/events/signal` and uses any returned `reply`. Currently
  `MASTER_ORCHESTRATOR_ENABLED=false`. Pick up after ping/pong works.
- **Voice-message transcription** end-to-end on the new setup. Code path
  exists (`app/transcription.py`); requires `TRANSCRIPTION_API_KEY` set.

## Recent commits (newest first)

- `8ec623b` Drop POLL_ENABLED override from unit; default .env.example to true
- `e9ed5b6` Make signal-api volume create idempotent across restarts
- `d69faf7` Set XDG_RUNTIME_DIR in Makefile so systemctl --user works without pam_systemd
- `4730231` Run production as unprivileged signal-bot user via user-mode systemd
- `dd964bd` Add make push/pull targets and document bidirectional dev/prod sync
