.PHONY: install check lint format typecheck arch test run

install:
	uv sync

check: lint typecheck arch test

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

arch:
	uv run lint-imports

test:
	uv run pytest

run:
	uv run uvicorn --factory shop.main:build_app --reload
