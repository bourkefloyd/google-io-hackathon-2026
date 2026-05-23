# Makefile for Simulated Android Player Telemetry Ingest & Fleet Orchestration
# Supports setup, server execution, quality checks, diagnostics, and clean up.

.PHONY: help setup run status lint format test clean distclean

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ANSI color codes for premium console output
CYAN   := \033[1;36m
YELLOW := \033[1;33m
GREEN  := \033[1;32m
RED    := \033[1;31m
MAGENTA:= \033[1;35m
RESET  := \033[0m

help: ## Display this gorgeous interactive help menu
	@echo -e "$(CYAN)=====================================================================$(RESET)"
	@echo -e "⚡ $(CYAN)Android Player Fleet & Telemetry Ingest - Workflow Console$(RESET) ⚡"
	@echo -e "$(CYAN)=====================================================================$(RESET)"
	@echo -e "Usage: make $(YELLOW)<target>$(RESET)"
	@echo -e ""
	@echo -e "$(YELLOW)Available Targets:$(RESET)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-15s$(RESET) %s\n", $$1, $$2}'
	@echo -e "$(CYAN)=====================================================================$(RESET)"

setup: ## Set up Python virtual environment, install requirements, and resolve local SDK dependencies
	@echo -e "$(CYAN)🛠️  Initializing Python Virtual Environment and Installing Dependencies...$(RESET)"
	@if [ ! -d ".venv" ]; then \
		echo "Creating virtual environment in .venv..."; \
		python3 -m venv .venv; \
	else \
		echo "Virtual environment (.venv) already exists."; \
	fi
	@echo "Upgrading pip to latest version..."
	@.venv/bin/pip install --upgrade pip
	@echo "Installing python packages from backend/requirements.txt..."
	@.venv/bin/pip install -r backend/requirements.txt
	@echo "Handling Google Antigravity SDK dependency..."
	@WHEEL_SOURCE="/var/folders/mv/8d6zd4791vj28b4ngt54dxk00000gn/T/test_download.whl"; \
	WHEEL_DEST="backend/google_antigravity-0.1.0-py3-none-macosx_11_0_arm64.whl"; \
	if [ -f "$$WHEEL_SOURCE" ]; then \
		echo "Found downloaded google-antigravity wheel. Installing..."; \
		cp "$$WHEEL_SOURCE" "$$WHEEL_DEST"; \
		.venv/bin/pip install "$$WHEEL_DEST"; \
	elif [ -f "$$WHEEL_DEST" ]; then \
		echo "Found local google-antigravity wheel in destination. Installing..."; \
		.venv/bin/pip install "$$WHEEL_DEST"; \
	else \
		echo "Installing google-antigravity from registry..."; \
		.venv/bin/pip install google-antigravity; \
	fi
	@echo -e "$(GREEN)✅ Virtual environment setup and package installation complete!$(RESET)"

run: ## Launch the FastAPI local backend server with automatic live reload on port 8000
	@echo -e "$(CYAN)🚀 Launching FastAPI Telemetry Ingest Server on http://localhost:8000$(RESET)"
	@if [ ! -d ".venv" ]; then \
		echo -e "$(RED)❌ Error: Virtual environment (.venv) not found. Run 'make setup' first.$(RESET)"; \
		exit 1; \
	fi
	@if lsof -i :8000 -t >/dev/null; then \
		echo -e "$(YELLOW)⚠️  Port 8000 is currently in use. Cleaning up existing process(es)...$(RESET)"; \
		lsof -i :8000 -t | xargs kill -9 2>/dev/null || true; \
		sleep 1; \
	fi
	@PYTHONPATH=backend .venv/bin/python3 -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload --reload-dir backend

status: ## Run dynamic system diagnostics, verify ADB connections, and check GCP telemetry configs
	@echo -e "$(MAGENTA)=========================================$(RESET)"
	@echo -e "📋 $(MAGENTA)System and Environment Diagnostics$(RESET)"
	@echo -e "$(MAGENTA)=========================================$(RESET)"
	@echo -n "Python Version:                 "
	@if command -v python3 &>/dev/null; then python3 --version; else echo -e "$(RED)❌ Python3 not found$(RESET)"; fi
	@echo -n "Virtual Environment (.venv):    "
	@if [ -d ".venv" ]; then echo -e "$(GREEN)✅ Configured & Ready$(RESET)"; else echo -e "$(RED)❌ Missing$(RESET) (Run 'make setup')"; fi
	@echo -n "Android ADB Command-Line Tool:  "
	@if command -v adb &>/dev/null; then echo -e "$(GREEN)✅ Available$(RESET) ($(shell which adb))"; else echo -e "$(YELLOW)⚠️  Missing$(RESET) (Run 'brew install --cask android-platform-tools')"; fi
	@echo ""
	@echo -e "$(MAGENTA)--- Active Android Emulators / Devices ---$(RESET)"
	@if command -v adb &>/dev/null; then adb devices; else echo "ADB is unavailable"; fi
	@echo ""
	@echo -e "$(MAGENTA)--- GCP Production Telemetry Variables ---$(RESET)"
	@echo -n "GCP_PROJECT_ID:                 "
	@if [ -n "$$GCP_PROJECT_ID" ]; then echo -e "$(GREEN)$$GCP_PROJECT_ID$(RESET)"; else echo -e "$(YELLOW)Not configured$(RESET) (Local Fallback Mode)"; fi
	@echo -n "GCP_PUBSUB_TOPIC:               "
	@if [ -n "$$GCP_PUBSUB_TOPIC" ]; then echo -e "$(GREEN)$$GCP_PUBSUB_TOPIC$(RESET)"; else echo -e "$(YELLOW)Not configured$(RESET) (Local Fallback Mode)"; fi
	@echo -n "GOOGLE_APPLICATION_CREDENTIALS: "
	@if [ -n "$$GOOGLE_APPLICATION_CREDENTIALS" ]; then echo -e "$(GREEN)$$GOOGLE_APPLICATION_CREDENTIALS$(RESET)"; else echo -e "$(YELLOW)Not configured$(RESET)"; fi
	@echo ""
	@echo -e "$(MAGENTA)--- Server Process Status ---$(RESET)"
	@echo -n "FastAPI Backend Port 8000:       "
	@if lsof -i :8000 -t &>/dev/null; then echo -e "$(GREEN)✅ Running$(RESET) (PID: $(shell lsof -i :8000 -t))"; else echo -e "$(WHITE)Stopped$(RESET)"; fi
	@echo -e "$(MAGENTA)=========================================$(RESET)"

lint: ## Analyze and lint Python code quality using Ruff or Flake8
	@echo -e "$(CYAN)🔍 Running python code linters...$(RESET)"
	@if [ ! -d ".venv" ]; then \
		echo -e "$(RED)❌ Error: Virtual environment (.venv) not found. Run 'make setup' first.$(RESET)"; \
		exit 1; \
	fi
	@if [ -f ".venv/bin/ruff" ]; then \
		.venv/bin/ruff check backend; \
	elif [ -f ".venv/bin/flake8" ]; then \
		.venv/bin/flake8 backend; \
	else \
		echo "Installing ruff in virtualenv for automated lint checks..."; \
		.venv/bin/pip install ruff; \
		.venv/bin/ruff check backend; \
	fi
	@echo -e "$(GREEN)✅ Lint checking successfully completed!$(RESET)"

format: ## Format all Python code files automatically according to pep8 styles
	@echo -e "$(CYAN)🎨 Formatting python files...$(RESET)"
	@if [ ! -d ".venv" ]; then \
		echo -e "$(RED)❌ Error: Virtual environment (.venv) not found. Run 'make setup' first.$(RESET)"; \
		exit 1; \
	fi
	@if [ -f ".venv/bin/ruff" ]; then \
		.venv/bin/ruff format backend; \
	elif [ -f ".venv/bin/black" ]; then \
		.venv/bin/black backend; \
	else \
		echo "Installing ruff in virtualenv for formatting..."; \
		.venv/bin/pip install ruff; \
		.venv/bin/ruff format backend; \
	fi
	@echo -e "$(GREEN)✅ Code formatting complete!$(RESET)"

test: ## Execute modular import and path integration verification checks on backend controllers
	@echo -e "$(CYAN)🧪 Running import and module verification integrity checks...$(RESET)"
	@if [ ! -d ".venv" ]; then \
		echo -e "$(RED)❌ Error: Virtual environment (.venv) not found. Run 'make setup' first.$(RESET)"; \
		exit 1; \
	fi
	@echo "Checking FastAPI/Pydantic package readiness..."
	@.venv/bin/python3 -c "import fastapi; import uvicorn; import pydantic; print('  - FastAPI, Uvicorn, and Pydantic import successfully!')"
	@echo "Checking custom backend module load dynamics..."
	@.venv/bin/python3 -c "import sys; sys.path.append('backend'); import fleet_manager; import ingestion; import agent_runner; print('  - Custom orchestrator fleet_manager, telemetry ingestion, and agent_runner modules loaded perfectly!')"
	@echo -e "$(GREEN)=========================================$(RESET)"
	@echo -e "$(GREEN)🎉 INTEGRITY TEST: ALL BACKEND MODULES OK!$(RESET)"
	@echo -e "$(GREEN)=========================================$(RESET)"

clean: ## Clear temporary python builds, run artifacts, logs, and python bytecode caches
	@echo -e "$(YELLOW)🧹 Cleaning compiler caches and runtime outputs...$(RESET)"
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type d -name "*.egg-info" -exec rm -rf {} +
	@find . -type d -name ".pytest_cache" -exec rm -rf {} +
	@rm -rf builds/*
	@rm -rf runs/*
	@echo -e "$(GREEN)✅ Cleanup complete!$(RESET)"

distclean: clean ## Reset repository completely by purging virtual environment and telemetry database files
	@echo -e "$(RED)🚨 Performing Deep Repository Reset...$(RESET)"
	@echo "Removing Python virtual environment (.venv)..."
	@rm -rf .venv
	@echo "Purging local telemetry database events log..."
	@rm -rf data
	@echo -e "$(GREEN)✅ Entire repository reset successfully to a pristine state!$(RESET)"
