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

setup:  ## Setup build folder.
	mkdir -p $(BUILD)
	meson setup . $(BUILD)

translate:
	$(MAKE) setup
	meson compile keeneticmanager-pot -C _build
	meson compile keeneticmanager-update-po -C _build

local:  ## Configure a local build.
	meson configure $(BUILD) -Dprefix=$$(pwd)/$(BUILD)/testdir

develop:  ## Configure a local build with debugging.
	meson configure $(BUILD) -Dprefix=$$(pwd)/$(BUILD)/testdir -Dprofile=development

run:  ## Run the local build.
	$(MAKE) install
	LC_ALL=en_GB.UTF-8 keeneticmanager

russian:
	$(MAKE) install
	LC_ALL=ru_RU.UTF-8 keeneticmanager

install:  ## Install system-wide.
	$(MAKE) setup
	ninja -C $(BUILD) install

test:  ## Run tests.
	ninja -C $(BUILD) install
	ninja -C $(BUILD) test
	TEST_PATH=$(TEST_PATH) ninja -C $(BUILD) tests

clean:  ## Clean build files.
	rm -r $(BUILD)
