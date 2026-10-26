.PHONY: replay live-probe live-module live-regression live-canary setup check format types test coverage coverage-shard product-static audit secrets diff dev-check dev-test rehearsal-check product-check linux-parity

setup:
	uv sync --locked
	uv run --locked prek install

check:
	uv lock --check
	uv run --locked prek run --all-files --show-diff-on-failure
	git diff --check
	git diff --cached --check

format:
	uv run --locked ruff format .

dev-check:
	uv run --locked ruff check devtools tests/devtools
	uv run --locked ruff format --check devtools tests/devtools
	uv run --locked mypy devtools
	$(MAKE) dev-test
	$(MAKE) rehearsal-check

dev-test:
	uv run --locked pytest tests/devtools

rehearsal-check:
	uv run --locked python -m devtools.skill_rehearsal --help

product-check: product-static
	$(MAKE) coverage

# Local-only Docker reproduction of docs/ci-gates.md; not part of hosted CI.
# shortcut: an 8 GiB Docker VM OOMs with two pytest workers; lift this cap when memory grows.
linux-parity:
	@set -eu; D=$$(mktemp -d "$(HOME)/deploy-vii-linux-parity.XXXXXX"); trap 'rm -rf "$$D"' EXIT; \
	git archive HEAD -o "$$D/tree.tar"; \
	printf '%s\n' '#!/bin/bash' 'set -eu' 'apt-get update -qq && apt-get install -y -qq curl ca-certificates git make nodejs' 'mkdir /w && tar -x -C /w -f /lx/tree.tar && cd /w' 'curl -LsSf https://astral.sh/uv/0.12.5/install.sh | sh' 'export PATH="/root/.local/bin:$$PATH"' 'uv sync --locked' 'uv run --locked playwright install --with-deps chromium' 'make product-check' > "$$D/run.sh"; \
	docker run --rm -e PYTEST_XDIST_AUTO_NUM_WORKERS=1 -v "$$D":/lx:ro ubuntu:24.04 bash /lx/run.sh

product-static:
	uv run --locked ruff check src tests/product
	uv run --locked ruff format --check src tests/product
	$(MAKE) types
	node --check src/deploy_vii/assets/app.js

types:
	uv run --locked mypy src scripts

test:
	uv run --locked pytest tests/product -m 'not live and not private'

coverage:
	uv run --locked pytest tests/product -m 'not live and not private' -n auto --dist loadfile --cov=deploy_vii --cov-branch --cov-report=term-missing

# One hosted shard of `coverage`: SHARD names a group in .github/shards/product.txt and
# COVERAGE_FILE the data file. The per-shard floor is off; CI enforces the existing floor
# on the combined data (docs/ci-gates.md).
coverage-shard:
	test -n "$(SHARD)" && files=$$(bash .github/scripts/shard_files.sh $(SHARD)) && uv run --locked pytest $$files -m 'not live and not private' -n auto --dist loadfile --cov=deploy_vii --cov-branch --cov-report= --cov-fail-under=0

audit:
	mkdir -p artifacts/dependency-audit
	uv export --locked --all-groups --no-emit-project --format requirements-txt --output-file artifacts/dependency-audit/requirements.txt --quiet
	uv run --locked pip-audit --strict --progress-spinner off -r artifacts/dependency-audit/requirements.txt

# Requires Gitleaks 8.30.1 on PATH. Scan files, staged changes AND reachable history.
secrets:
	test "$$(gitleaks version)" = "8.30.1"
	test "$$(git rev-parse --is-shallow-repository)" = "false"
	git rev-parse --verify HEAD
	gitleaks dir --redact --no-banner --no-color --ignore-gitleaks-allow .
	bash -o pipefail -c 'git diff --cached --no-ext-diff --no-textconv --binary | gitleaks stdin --redact --no-banner --no-color --ignore-gitleaks-allow'
	gitleaks git --log-opts='--all --full-history' --redact --no-banner --no-color --ignore-gitleaks-allow .

diff:
	git diff --stat origin/main
	git diff --numstat origin/main

# Live model tests (OpenRouter). The key comes from the DC-7 file in settings, never from make.
# CAP is a required USD amount bound to the batch ledger; DIRECTORY is the execution journal.
DIRECTORY ?= artifacts/execution
LIVE = uv run --locked python -m deploy_vii live
# live-module pass-through (task 7.0): each option is sent only when its variable is set.
LIVE_MODULE_OPTIONS = $(if $(MODELS), --models "$(MODELS)")$(if $(MAX_TOKENS), --max-tokens "$(MAX_TOKENS)")$(if $(TIMEOUT), --timeout "$(TIMEOUT)")$(if $(BATCH_ID), --batch-id "$(BATCH_ID)")$(if $(SEED), --seed "$(SEED)")

replay:
	uv run --locked pytest tests/product/test_replay.py -q -rs

live-probe:
	test -n "$(CAP)" || { echo "CAP=<usd> is required"; exit 2; }
	$(LIVE) probe --directory "$(DIRECTORY)" --cap "$(CAP)"

live-module:
	test -n "$(MODULE)" -a -n "$(CAP)" || { echo "MODULE=<id> and CAP=<usd> are required"; exit 2; }
	$(LIVE) module --directory "$(DIRECTORY)" --module "$(MODULE)" --cap "$(CAP)"$(LIVE_MODULE_OPTIONS)

live-regression:
	test -n "$(CAP)" || { echo "CAP=<usd> is required"; exit 2; }
	$(LIVE) regression --directory "$(DIRECTORY)" --cap "$(CAP)"

live-canary:
	test -n "$(CAP)" || { echo "CAP=<usd> is required"; exit 2; }
	$(LIVE) canary --directory "$(DIRECTORY)" --cap "$(CAP)"
