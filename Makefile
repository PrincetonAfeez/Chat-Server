.PHONY: install test test-fast lint format format-check typecheck check demo all

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

# Skip the socket/timing tests for a fast inner loop.
test-fast:
	python -m pytest -m "not slow"

cov:
	python -m pytest --cov --cov-report=term-missing --cov-fail-under=65

lint:
	python -m ruff check src tests

format:
	python -m ruff format src tests

format-check:
	python -m ruff format --check src tests

typecheck:
	python -m mypy

# Everything CI runs (includes coverage gate).
check: lint format-check typecheck cov

demo:
	python -m chatserver.cli.main demo all || chatserver demo all

all: check
