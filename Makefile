# python executable
PYTHON = python3 -B

# virtual environment path
VENV = venv

# command to activate the virtual environment
ACTIVATE = . $(VENV)/bin/activate

#
# testing
#

TESTS =

.PHONY: test
test: export PYTHONDONTWRITEBYTECODE = 1
test:
	$(PYTHON) -m unittest -f $(TESTS)

#
# building
#

build: ekernel.py pyproject.toml setup.py
	$(PYTHON) -m build --sdist

#
# code quality
#

FLAKE8_OPTS = --ignore E123,E124,E128,E201,E202,E211,E302,E306,E701

.PHONY: lint
lint: venv
	@$(ACTIVATE) && flake8 $(FLAKE8_OPTS) lib cli tests

#
# initialize environment
#

.PHONY: init
init: requirements

# disable pip's cache (under ~/.cache/pip)
export PIP_NO_CACHE_DIR ?= true

# install dependencies
.PHONY: requirements
requirements: $(VENV)
	$(ACTIVATE) && pip install -U -r requirements.txt

# create virtual environment
$(VENV):
	$(PYTHON) -m venv $(VENV)
	$(ACTIVATE) && pip install --upgrade pip wheel

# remove virtual environment
.PHONY: clean
clean:
	rm -rf $(VENV)
