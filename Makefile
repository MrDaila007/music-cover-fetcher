PYTHON = .venv/Scripts/python
PIP = .venv/Scripts/pip
VENV = .venv
SRC = music_cover_fetcher.py

# Default music directory (override: make tag MUSIC=C:\path\to\music)
MUSIC ?= $(USERPROFILE)/Music

.PHONY: setup install run tag interactive dry-run strip-covers clean help

help: ## Show this help
	@echo Usage: make [target] [MUSIC=path]
	@echo.
	@findstr /R "^[a-z].*:.*##" Makefile

setup: $(VENV) install ## Full setup: create venv + install deps

$(VENV):
	python -m venv $(VENV)

install: $(VENV) ## Install dependencies into venv
	$(PIP) install --upgrade pip -q
	$(PIP) install -e . -q

run: ## Run with custom args: make run ARGS="path -i --force"
	$(PYTHON) $(SRC) $(ARGS)

tag: ## Auto-fill metadata: make tag MUSIC=path
	$(PYTHON) $(SRC) "$(MUSIC)" --tag

interactive: ## Interactive mode: make interactive MUSIC=path
	$(PYTHON) $(SRC) "$(MUSIC)" -i

dry-run: ## Preview changes: make dry-run MUSIC=path
	$(PYTHON) $(SRC) "$(MUSIC)" --tag --dry-run

strip-covers: ## Remove all cover art: make strip-covers MUSIC=path
	$(PYTHON) $(SRC) "$(MUSIC)" --strip-covers

clean: ## Remove venv and cache files
	if exist $(VENV) rmdir /s /q $(VENV)
	if exist __pycache__ rmdir /s /q __pycache__
