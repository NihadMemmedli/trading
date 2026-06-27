.PHONY: sync test lint format typecheck check services-up services-down services-logs

sync:
	uv sync --all-groups

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src
	uv run pytest
	uv lock --check

services-up:
	docker compose up -d postgres redis

services-down:
	docker compose down

services-logs:
	docker compose logs -f postgres redis
