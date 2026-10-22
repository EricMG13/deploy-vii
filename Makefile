.PHONY: replay live-probe live-module live-regression live-canary setup check format types test coverage audit secrets diff dev-check dev-test product-check

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

dev-test:
	uv run --locked pytest tests/devtools

product-check:
	uv run --locked ruff check src tests/product
	uv run --locked ruff format --check src tests/product
	$(MAKE) types
	node --check src/deploy_vii/assets/app.js
	$(MAKE) coverage

types:
	uv run --locked mypy src

test:
	uv run --locked pytest tests/product -m 'not live and not private'

coverage:
	uv run --locked pytest tests/product -m 'not live and not private' --cov=deploy_vii --cov-branch --cov-report=term-missing

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

replay:
	uv run --locked pytest tests/product/test_replay.py -q -rs

live-probe:
	test -n "$(CAP)" || { echo "CAP=<usd> is required"; exit 2; }
	$(LIVE) probe --directory "$(DIRECTORY)" --cap "$(CAP)"

live-module:
	test -n "$(MODULE)" -a -n "$(CAP)" || { echo "MODULE=<id> and CAP=<usd> are required"; exit 2; }
	$(LIVE) module --directory "$(DIRECTORY)" --module "$(MODULE)" --cap "$(CAP)"

live-regression:
	test -n "$(CAP)" || { echo "CAP=<usd> is required"; exit 2; }
	$(LIVE) regression --directory "$(DIRECTORY)" --cap "$(CAP)"

live-canary:
	test -n "$(CAP)" || { echo "CAP=<usd> is required"; exit 2; }
	$(LIVE) canary --directory "$(DIRECTORY)" --cap "$(CAP)"
