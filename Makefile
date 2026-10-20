.PHONY: setup check format types test coverage audit secrets diff dev-check dev-test
.PHONY: codex-scaffold codex-feature codex-sensitive codex-research codex-architect

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

# Product targets intentionally fail until actual source/tests exist.
types:
	uv run --locked mypy src

test:
	uv run --locked pytest tests/product -m 'not live and not private'

coverage:
	uv run --locked pytest tests/product -m 'not live and not private' --cov --cov-branch --cov-report=term-missing

audit:
	uv run --locked pip-audit --strict --progress-spinner off

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

# Explicit interactive worker sessions; keep the current coordinator unchanged.
codex-scaffold:
	codex --model gpt-6.1-sol --config 'model_reasoning_effort="low"'

codex-feature:
	codex --model gpt-6.1-sol --config 'model_reasoning_effort="medium"'

codex-sensitive:
	codex --model gpt-6.1-sol --config 'model_reasoning_effort="high"'

codex-research:
	codex --model gpt-6.1-sol --config 'model_reasoning_effort="medium"' --sandbox read-only

codex-architect:
	codex --model gpt-6-astra --config 'model_reasoning_effort="high"' --sandbox read-only
