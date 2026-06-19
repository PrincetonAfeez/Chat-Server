.PHONY: install test test-fast lint format typecheck check demo all

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

# Skip the socket/timing tests for a fast inner loop.
test-fast:
	python -m pytest -m "not slow"

cov:
	python -m pytest --cov --cov-report=term-missing

lint:
	python -m ruff check src tests

format:
	python -m ruff format src tests

typecheck:
	python -m mypy

# Everything CI runs.
check: lint typecheck test

demo:
	python -m chatserver.cli.main demo all || chatserver demo all

all: check
