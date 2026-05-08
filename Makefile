BUILD := _build

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

help:
	@python3 -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

UNAME := $(shell uname)

ifeq ($(UNAME), Darwin)
BREW_PREFIX := $(shell brew --prefix 2>/dev/null || echo /opt/homebrew)
EXTRA_ENV := PATH="$(BREW_PREFIX)/bin:$$PATH" \
	GSETTINGS_SCHEMA_DIR="$$(pwd)/$(BUILD)/testdir/share/glib-2.0/schemas" \
	XDG_DATA_DIRS="$(BREW_PREFIX)/share:/usr/share"
else
EXTRA_ENV :=
endif

setup:  ## Setup build folder.
	mkdir -p $(BUILD)
	$(EXTRA_ENV) meson setup . $(BUILD)

translate:
	$(MAKE) setup
	meson compile keeneticmanager-pot -C _build
	meson compile keeneticmanager-update-po -C _build

local:  ## Configure a local build.
	$(MAKE) clean
	$(MAKE) setup
	$(EXTRA_ENV) meson configure $(BUILD) -Dprefix=$$(pwd)/$(BUILD)/testdir -Dbuildtype=debug
	$(EXTRA_ENV) ninja -C $(BUILD) install

start:
	$(MAKE) local
	$(EXTRA_ENV) LC_ALL=en_GB.UTF-8 $(BUILD)/testdir/bin/keeneticmanager

start-ru:
	$(MAKE) local
	$(EXTRA_ENV) LC_ALL=ru_RU.UTF-8 $(BUILD)/testdir/bin/keeneticmanager

install:  ## Install system-wide.
	$(MAKE) clean
	$(MAKE) setup
	ninja -C $(BUILD) install

uninstall:
	ninja -C $(BUILD) uninstall

test:  ## Run tests.
	ninja -C $(BUILD) install
	ninja -C $(BUILD) test
	TEST_PATH=$(TEST_PATH) ninja -C $(BUILD) tests

clean:  ## Clean build files.
	yes | rm -rf $(BUILD)

alt-deps: ## Устрановка зависимостей в Alt Linux для работы
	epmi python3-module-netifaces python3-module-requests python3-module-keyring meson cmake
