.PHONY: help install install-dev test lint format type-check clean run

help:
	@echo "Brito Alerts - Available commands:"
	@echo ""
	@echo "  make install        Install dependencies"
	@echo "  make install-dev    Install dependencies with dev tools"
	@echo "  make test           Run tests with pytest"
	@echo "  make lint           Run linting checks (ruff)"
	@echo "  make format         Format code with black"
	@echo "  make type-check     Run type checking with mypy"
	@echo "  make clean          Remove cache and build files"
	@echo "  make run            Run the Udacity pricing monitor"
	@echo "  make check          Run all checks (lint, type-check, test)"
	@echo ""

install:
	pip install --upgrade pip
	pip install -r requirements.txt

install-dev: install
	pip install -e ".[dev]"
	pre-commit install

test:
	pytest -v

test-cov:
	pytest --cov=src --cov-report=html --cov-report=term

lint:
	ruff check src/ tests/

format:
	black src/ tests/
	ruff check src/ tests/ --fix

type-check:
	mypy src/

check: lint type-check test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .coverage htmlcov
	rm -rf build dist *.egg-info

run:
	python src/udacity_pricing.py

.DEFAULT_GOAL := help
