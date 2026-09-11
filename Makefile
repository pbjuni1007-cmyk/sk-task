PYTHON ?= .venv/bin/python
RUFF ?= $(PYTHON) -m ruff

.PHONY: lint format format-check test check
lint:
	$(RUFF) check .

format:
	$(RUFF) format .
	npm run format

format-check:
	$(RUFF) format --check .
	npm run format:check

test:
	$(PYTHON) -m pytest -q

check: lint format-check test
