SHELL := /bin/sh

APP_NAME := signal-bot
ENV_FILE ?= $(HOME)/.config/$(APP_NAME).env
SYSTEMD_USER_DIR ?= $(HOME)/.config/systemd/user
PYTHON ?= python3
LOCAL_VENV := .venv
SIGNAL_API_IMAGE ?= docker.io/bbernhard/signal-cli-rest-api:latest
VOLUME_TARBALL ?= /tmp/signal-cli-data.tar
SERVICES := signal-api.service signal-bot.service

# Ensure systemctl --user works even in SSH sessions where pam_systemd didn't
# set XDG_RUNTIME_DIR. Requires linger to be enabled for this user.
export XDG_RUNTIME_DIR ?= /run/user/$(shell id -u)

.DEFAULT_GOAL := help

.PHONY: help dependencies build install start stop restart status logs test test-api push pull update clean import-signal-volume

help: ## List available targets.
	@awk 'BEGIN {FS = ":.*##"; printf "Available targets:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

push: ## Push committed changes on the current branch to origin (dev->GitHub or prod hot-fix->GitHub).
	@branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ -n "$$(git status --porcelain)" ]; then \
		echo "Working tree is dirty. Commit or stash before pushing:"; \
		git status --short; \
		exit 1; \
	fi; \
	echo "Pushing $$branch to origin..."; \
	git push origin $$branch

pull: ## Fast-forward pull the current branch from origin (dev sync or prod update step).
	@branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ -n "$$(git status --porcelain)" ]; then \
		echo "Working tree is dirty. Commit or stash before pulling:"; \
		git status --short; \
		exit 1; \
	fi; \
	echo "Pulling $$branch from origin..."; \
	git fetch origin; \
	git pull --ff-only origin $$branch

update: pull build install restart ## Pull latest changes and update the production installation (= pull + build + install + restart).

dependencies: ## Check production dependencies. If anything is missing, print the root command needed.
	@missing=""; \
	for cmd in podman ffmpeg curl systemctl $(PYTHON); do \
		command -v $$cmd >/dev/null 2>&1 || missing="$$missing $$cmd"; \
	done; \
	tmpdir=$$(mktemp -d); \
	if ! $(PYTHON) -m venv "$$tmpdir/venv" >/dev/null 2>&1; then missing="$$missing python3-venv"; fi; \
	rm -rf "$$tmpdir"; \
	if [ -z "$$missing" ]; then \
		echo "All required dependencies are present."; \
	else \
		echo "Missing dependencies:$$missing"; \
		echo ""; \
		echo "Ask a sudoer to run on this host:"; \
		echo "  sudo apt-get update && sudo apt-get install -y podman ffmpeg curl python3-venv python3-pip"; \
		echo ""; \
		echo "Then rerun: make dependencies"; \
		exit 1; \
	fi

build: ## Build the local Python venv and pull container images.
	@if [ -d "$(LOCAL_VENV)" ] && [ ! -x "$(LOCAL_VENV)/bin/python" ]; then \
		echo "Removing incomplete $(LOCAL_VENV)"; \
		rm -rf "$(LOCAL_VENV)"; \
	fi
	$(PYTHON) -m venv $(LOCAL_VENV)
	$(LOCAL_VENV)/bin/python -m ensurepip --upgrade
	$(LOCAL_VENV)/bin/python -m pip install --upgrade pip
	$(LOCAL_VENV)/bin/python -m pip install -r requirements-dev.txt
	podman pull $(SIGNAL_API_IMAGE)

install: ## Install env file (if missing) and user-mode systemd units. No sudo.
	@mkdir -p $(dir $(ENV_FILE))
	@if [ ! -f "$(ENV_FILE)" ]; then \
		echo "Creating $(ENV_FILE) from .env.example; edit secrets before starting."; \
		install -m 600 .env.example $(ENV_FILE); \
	else \
		echo "Keeping existing $(ENV_FILE)"; \
	fi
	@mkdir -p $(SYSTEMD_USER_DIR)
	install -m 644 deploy/systemd/signal-api.service $(SYSTEMD_USER_DIR)/signal-api.service
	install -m 644 deploy/systemd/signal-bot.service $(SYSTEMD_USER_DIR)/signal-bot.service
	systemctl --user daemon-reload
	systemctl --user enable $(SERVICES)
	@echo "Installed. Edit $(ENV_FILE) if needed, then run: make start"

import-signal-volume: ## Import signal-cli-data volume from $(VOLUME_TARBALL) into rootless podman.
	@if [ ! -f "$(VOLUME_TARBALL)" ]; then \
		echo "Tarball $(VOLUME_TARBALL) not found."; \
		echo "First, on a sudoer account, run:"; \
		echo "  sudo podman volume export signal-cli-data -o $(VOLUME_TARBALL)"; \
		echo "  sudo chown $$(id -un):$$(id -gn) $(VOLUME_TARBALL)"; \
		exit 1; \
	fi
	-podman volume create signal-cli-data
	podman volume import signal-cli-data $(VOLUME_TARBALL)
	rm -f $(VOLUME_TARBALL)
	@echo "Imported. Restart services with: make restart"

start: ## Start production services.
	systemctl --user start $(SERVICES)

stop: ## Stop production services.
	systemctl --user stop signal-bot.service signal-api.service

restart: ## Restart production services.
	systemctl --user restart $(SERVICES)

status: ## Show systemd status for production services.
	systemctl --user status $(SERVICES) --no-pager

logs: ## Tail backend logs (last 30 lines, then follow until Ctrl-C).
	journalctl --user-unit signal-bot.service --user-unit signal-api.service -n 30 -f

test: ## Run all local test suites.
	@if [ -x ".venv/bin/pytest" ]; then .venv/bin/pytest; else $(PYTHON) -m pytest; fi

test-api: ## Check local production HTTP endpoints.
	curl -fsS http://localhost:8080/v1/about
	curl -fsS http://localhost:8000/health

clean: ## Remove local test/build caches.
	rm -rf .pytest_cache app/__pycache__ tests/__pycache__
