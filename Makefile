.PHONY: help install dev-install format format-check lint types test check migrate revision reset-db run clean

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
SRC := src
TESTS := tests
ALEMBIC := $(PYTHON) -m alembic -c src/alembic.ini

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Установить рантайм-зависимости
	$(PIP) install -r requirements.txt

dev-install: ## Установить dev-зависимости (линтеры, тесты)
	$(PIP) install -r requirements-dev.txt

format: ## Авто-форматирование кода (black + isort)
	$(PYTHON) -m isort $(SRC) $(TESTS)
	$(PYTHON) -m black $(SRC) $(TESTS)

format-check: ## Проверка форматирования без изменений
	$(PYTHON) -m isort --check-only --diff $(SRC) $(TESTS)
	$(PYTHON) -m black --check --diff $(SRC) $(TESTS)

lint: ## Линтер (flake8)
	$(PYTHON) -m flake8 $(SRC) $(TESTS)

types: ## Проверка типов (mypy, мягкий режим)
	$(PYTHON) -m mypy --ignore-missing-imports --explicit-package-bases --install-types --non-interactive $(SRC)

test: ## Запуск тестов (pytest)
	$(PYTHON) -m pytest -q

check: format-check lint test ## Полный прогон проверок (формат + линт + тесты)
	@echo "✅ make check OK (types: запускайте отдельно через 'make types', см. TECH-006)"

migrate: ## Применить миграции Alembic локально (upgrade head)
	$(ALEMBIC) upgrade head

revision: ## Создать новую Alembic-ревизию (m="message")
	@if [ -z "$(m)" ]; then echo "Usage: make revision m=\"description\""; exit 1; fi
	$(ALEMBIC) revision -m "$(m)"

reset-db: ## Сбросить локальную БД (drop + create) — DESTRUCTIVE
	$(PYTHON) -m src.database.init_db

run: ## Запустить бота локально (long-polling)
	$(PYTHON) -m src.main

clean: ## Удалить .pyc / __pycache__ / .pytest_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.py[co]" -delete
	rm -rf .pytest_cache .mypy_cache .coverage
