# Development

Create a local environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Run the Signal REST API locally with Podman:

```sh
podman volume create signal-cli-data
podman run -d --name signal-api \
  -p 8080:8080 \
  -e MODE=native \
  -v signal-cli-data:/home/.local/share/signal-cli \
  docker.io/bbernhard/signal-cli-rest-api:latest
```

Run the bot:

```sh
POLL_ENABLED=true .venv/bin/uvicorn app.main:app --reload
```

Run tests:

```sh
make test
```

## Syncing with production

Pull the latest commits from GitHub into the dev checkout (e.g. after a
production hot-fix has been pushed back):

```sh
make pull
```

Push committed changes from dev so production can apply them with `make update`:

```sh
make push
```

Both targets refuse to run if the working tree is dirty. See
[Production Operations](production.md) for the full bidirectional flow.
