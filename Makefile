SHELL := /bin/sh

APP_NAME := signal-bot
INSTALL_DIR ?= /opt/$(APP_NAME)
ENV_FILE ?= /etc/$(APP_NAME).env
PYTHON ?= python3
VENV := $(INSTALL_DIR)/.venv
LOCAL_VENV := .venv
SIGNAL_API_IMAGE ?= docker.io/bbernhard/signal-cli-rest-api:latest

.DEFAULT_GOAL := help

.PHONY: help dependencies build install start stop restart status logs test test-api clean

help: ## List available targets.
	@awk 'BEGIN {FS = ":.*##"; printf "Available targets:\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dependencies: ## Install/check production dependencies: podman, ffmpeg, Python venv/pip, curl, rsync, systemd.
	@missing=""; \
	for cmd in podman ffmpeg curl rsync systemctl $(PYTHON); do \
		command -v $$cmd >/dev/null 2>&1 || missing="$$missing $$cmd"; \
	done; \
	tmpdir=$$(mktemp -d); \
	if ! $(PYTHON) -m venv "$$tmpdir/venv" >/dev/null 2>&1; then missing="$$missing python3-venv"; fi; \
	rm -rf "$$tmpdir"; \
	if [ -n "$$missing" ]; then \
		if command -v apt-get >/dev/null 2>&1; then \
			echo "Installing missing dependencies:$$missing"; \
			sudo apt-get update; \
			sudo apt-get install -y podman ffmpeg curl rsync python3-venv python3-pip; \
		else \
			echo "Missing dependencies:$$missing"; \
			echo "Install them with your OS package manager, then rerun make dependencies."; \
			exit 1; \
		fi; \
	else \
		echo "All required dependencies are present."; \
	fi

build: ## Build/install Python artifacts and pull container images on this host.
	@if [ -d "$(LOCAL_VENV)" ] && [ ! -x "$(LOCAL_VENV)/bin/python" ]; then \
		echo "Removing incomplete $(LOCAL_VENV)"; \
		rm -rf "$(LOCAL_VENV)"; \
	fi
	$(PYTHON) -m venv $(LOCAL_VENV)
	$(LOCAL_VENV)/bin/python -m ensurepip --upgrade
	$(LOCAL_VENV)/bin/python -m pip install --upgrade pip
	$(LOCAL_VENV)/bin/python -m pip install -r requirements-dev.txt
	podman pull $(SIGNAL_API_IMAGE)

install: dependencies ## Install app under /opt, env under /etc, and systemd units for autostart.
	sudo mkdir -p $(INSTALL_DIR)
	sudo rsync -a --delete \
		--exclude '.git' \
		--exclude '.venv' \
		--exclude '.env' \
		--exclude '.env~' \
		--exclude '__pycache__' \
		--exclude '.pytest_cache' \
		--exclude 'bot.log' \
		./ $(INSTALL_DIR)/
	@if [ -d "$(VENV)" ] && [ ! -x "$(VENV)/bin/python" ]; then \
		echo "Removing incomplete $(VENV)"; \
		sudo rm -rf "$(VENV)"; \
	fi
	sudo $(PYTHON) -m venv $(VENV)
	sudo $(VENV)/bin/python -m ensurepip --upgrade
	sudo $(VENV)/bin/python -m pip install --upgrade pip
	sudo $(VENV)/bin/python -m pip install -r $(INSTALL_DIR)/requirements.txt
	@if [ ! -f "$(ENV_FILE)" ]; then \
		if [ -f ".env" ]; then \
			echo "Creating $(ENV_FILE) from local .env"; \
			sudo install -m 600 .env $(ENV_FILE); \
		else \
			echo "Creating $(ENV_FILE) from .env.example; edit secrets before starting."; \
			sudo install -m 600 .env.example $(ENV_FILE); \
		fi; \
	else \
		echo "Keeping existing $(ENV_FILE)"; \
	fi
	sudo install -m 644 deploy/systemd/signal-api.service /etc/systemd/system/signal-api.service
	sudo install -m 644 deploy/systemd/signal-bot.service /etc/systemd/system/signal-bot.service
	sudo systemctl daemon-reload
	sudo systemctl enable signal-api.service signal-bot.service
	@echo "Installed. Edit $(ENV_FILE), then run: make restart"

start: ## Start production services.
	sudo systemctl start signal-api.service signal-bot.service

stop: ## Stop production services.
	sudo systemctl stop signal-bot.service signal-api.service

restart: ## Restart production services.
	sudo systemctl restart signal-api.service signal-bot.service

status: ## Show systemd status for production services.
	sudo systemctl status signal-api.service signal-bot.service --no-pager

logs: ## Show recent backend logs.
	sudo journalctl -u signal-bot.service -u signal-api.service -n 100 --no-pager

test: ## Run all local test suites.
	@if [ -x ".venv/bin/pytest" ]; then .venv/bin/pytest; else $(PYTHON) -m pytest; fi

test-api: ## Check local production HTTP endpoints.
	curl -fsS http://localhost:8080/v1/about
	curl -fsS http://localhost:8000/health

clean: ## Remove local test/build caches.
	rm -rf .pytest_cache app/__pycache__ tests/__pycache__
