# 0001 — Separate research foundation

Historical decision from the removed setup. Its policies/tool settings are not
adopted in this app project. See the [current scope](../../AGENTS.md).

Date: 2026-10-20. Status: adopted for repository setup; runtime architecture remains
a research recommendation. Owner requested `deploy-vii`, private.

Create a fresh repository with research, policy, model profiles and CI settings.
Do not copy Deploy VI production code, protected sources or accumulated history.
Later reuse requires identifying the tested source and preserving its invariants.
No product implementation or live model test is authorized by this setup.

The active workflow checks repository hygiene, secret exposure and change size.
Future product gates are declared but must be implemented with their first
applicable increment. Independent mandatory reviews and tournaments stay retired.

CI tools only: pre-commit 4.6.2; pre-commit-hooks v6.0.0 at
`3e8a8703264a2f4a69428a0aa4dcb512790b2c8c`; Gitleaks 8.30.1.
Actions: checkout v7.0.1 at `3d3c42e5aac5ba805825da76410c181273ba90b1`;
setup-uv v10.1.0 at `bec219d24cd3e171d82865faccec33120bb574f4`, uv 0.12.5.
Public Git tag resolutions were checked. The Linux Gitleaks release archive is
verified against the committed SHA256 before execution. These tools are development
dependencies, not runtime libraries. Pre-commit tool environments still need
registry access; a tool installation failure is a failed check.

No agent framework or runtime dependency is added. Start with native Copilot
skills/Python and compare a direct OpenRouter runner with Pydantic AI only when
implementation/testing is authorized. Preserve raw evidence and explicit limits.

Not verified: product viability, model/profile execution, hosted checks or applied
repository protection until the setup status records their actual results.
