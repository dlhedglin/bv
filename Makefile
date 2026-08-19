# The canonical invocation of every routine command in this repo.
#
# Targets run through `uv run`, never a bare `pytest` or `ty`, so no activated
# virtualenv is assumed and every machine uses the version pinned in uv.lock.
# Each target exits non-zero when its check fails, so the same target serves
# locally and in CI without a wrapper.
#
# `##` after a target name is what `help` prints. Keep it on the target line --
# a description anywhere else will not show up in the list.

.DEFAULT_GOAL := help

.PHONY: help hooks typecheck lint fmt test coverage check

help:  ## List the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# Points git at the version-controlled hook in .githooks/ rather than copying a
# script into .git/hooks, so the gate tracks with the repo and updates on pull.
# core.hooksPath is per-clone local config and never travels in a clone, so this
# is the one manual step -- run once after cloning.
hooks:  ## Install the pre-commit hook (runs make check before every commit)
	git config core.hooksPath .githooks
	@echo "pre-commit hook installed. Bypass one commit with 'git commit --no-verify'."

typecheck:  ## Type-check src/bv/ and tests/ with ty
	uv run ty check

# lint reports and never writes; fmt is the writing counterpart. Keeping them
# apart matters: a check target that quietly rewrites the tree is unusable in
# CI and surprising in a pre-commit hook.
lint:  ## Report lint and formatting problems with ruff
	uv run ruff check .
	uv run ruff format --check .

fmt:  ## Reformat and auto-fix with ruff
	uv run ruff format .
	uv run ruff check --fix .

# ARGS is forwarded straight to pytest, so the one target covers the full sweep
# and a single failing test: `make test ARGS="-k board"`, `make test ARGS=-x`.
# What to collect lives in [tool.pytest.ini_options], not here, so a bare
# `uv run pytest` behaves the same as this target.
test:  ## Run the test suite (make test ARGS="-k board")
	uv run pytest $(ARGS)

# Deliberately not folded into `test`. Coverage instrumentation traces every
# line the suite executes, and `test` is the target run on every save -- the
# fast one stays fast. What is measured and how it is reported lives in
# [tool.coverage.*], so this recipe only turns instrumentation on and picks the
# two outputs: term-missing to read here, htmlcov/ to open when actually
# filling a gap.
#
# Bare `--cov`, not `--cov=bv`. A value there is handed to coverage as `source`,
# which resolves a name that is not an existing directory by importing it -- and
# under the src layout `bv/` is not a directory in the invocation directory, so
# coverage imported the package after measurement had already started and warned
# `module-not-measured` on every run. With no value, pytest-cov leaves the
# selection to `source_pkgs` in [tool.coverage.run], which is where it was
# already declared.
coverage:  ## Run the suite under coverage and write htmlcov/
	uv run pytest --cov --cov-report=term-missing --cov-report=html $(ARGS)

# The one command to run before committing. Ordered cheapest-feedback-first:
# typecheck and lint fail in seconds and point at the exact line, while the
# suite takes long enough that a type error found after it is time already
# spent. Recursive $(MAKE) rather than prerequisites, because prerequisite
# order is not guaranteed under `make -j` and the point of this target is the
# order. Make stops at the first non-zero recipe line, so a lint failure never
# gets buried under the test output. coverage stays out: it re-runs the same
# suite slower, and it is a number to read rather than a gate to pass.
check:  ## Typecheck, lint and test -- run this before committing
	$(MAKE) typecheck
	$(MAKE) lint
	$(MAKE) test
