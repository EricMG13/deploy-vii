# Environment setup result

Status: environment implemented and locally verified. Published as
[draft PR #1](https://github.com/EricMG13/deploy-vii/pull/1); unmerged.
Hosted acceptance is blocked by GitHub account billing/spending eligibility.

The setup implements decision 0002: pinned Python/uv and development tools,
deterministic Git hooks and CI, development ICM, explicit worker launch settings,
the model-test/telemetry contract and the byte-preserved Direction C reference.
The restored research is reconciled with active configuration. No analytical
product, model runner or renderer has been implemented or qualified.

## Local checks

- Locked environment installed; dependency audit reports no known vulnerabilities.
- `make setup`, `make check` and `make secrets` pass. Ruff reports no applicable
  Python files; this is not a linted or tested product implementation.
- actionlint 1.7.12 accepts both workflows; its downloaded archive checksum was verified.
- CI selects `ubuntu-24.04` to avoid the announced `ubuntu-latest` OS migration.
  This pins the OS series, not every hosted-image package.
- All configuration formats and five Claude frontmatters parse.
- Invalid JSON/TOML/YAML and synthetic private-key inputs are rejected.
- Synthetic secret probes identified a gap between staged and working content;
  `make secrets` now scans working files, staged changes and reachable history.
- Codex native configuration readback confirms explicit model/effort flags.
  The initial project profile-table approach was removed after proving this CLI
  uses global profile-v2 files and silently accepts missing profile names.
- Native readback separately confirms GPT-6 Astra/high with a read-only sandbox.
  Neither readback invokes a model. Claude definitions are syntax/field checked;
  live host routing and account entitlement remain untested.
- Direction C copy matches the supplied file's SHA-256 exactly.
- All 112 local links across 32 Markdown documents resolve. Product type/test/
  coverage targets were deliberately exercised with no inputs and fail as intended.
- The separate lowercase checkout remains clean and untouched.

## GitHub settings

Readback confirms the repository remains private with main as default branch;
squash is the only enabled merge method, merged branches are deleted, and
automatic merging is disabled. The Actions default token was already read-only
and cannot approve PRs. The desired branch ruleset is saved but not applied:
the private-repository API returns HTTP 403 under the current account plan.

The initial PR head `5cf03a9c101a2657adb1b1c45146c760839b49ea` triggered
[development checks](https://github.com/EricMG13/deploy-vii/actions/runs/39505911468)
and [dependency audit](https://github.com/EricMG13/deploy-vii/actions/runs/39505911810).
All three jobs report failure with **zero steps executed**. Their annotations say
GitHub could not start the jobs because recent account payments failed or the
spending limit needs increasing. That is the provider's alternative explanation;
this setup has not inspected or changed billing. It is not a test failure or a
hosted pass. Re-enable account runner eligibility and rerun the current PR head
before treating hosted validation as complete.

The publication also confirmed the workflow blob on GitHub matches the local
committed file. A status listing initially displayed the old workflow label;
the run detail and exact blob identify the actual workflow as Development checks.

## Confidence review — complete environment candidate

Least confident about, in priority order:

1. **Native worker settings might silently do nothing.** A nonexistent Codex
   profile returned success too. Local CLI help identified global profile-v2
   lookup as the cause. **Confirmed and fixed:** replaced project profile tables
   with explicit native Make launch commands. Config API readback verifies the
   feature and read-only architecture selections. Live execution remains open.
2. **Secret scans might miss the actual commit candidate.** A synthetic token
   staged in Git but absent from the working file passed directory/history scans.
   **Confirmed and fixed:** an additional staged-diff scan rejects it; pipefail
   preserves upstream Git failures. The full candidate passes all three scans.
3. **Research could become accidental policy.** Older plugin/setup text rejected
   a review skill required by the user and claimed no installed environment.
   **Confirmed and fixed:** updated current instructions/docs and labelled the
   retained historical snapshots; explicit review requirements take precedence.
4. **Empty code/tests could produce misleading green gates.** **Verified fine:**
   current CI checks environment hygiene/secrets; type/test/coverage commands fail
   without product inputs. No product, live-model or browser pass is claimed.
5. **Lock/hooks/workflows could disagree.** **Verified fine:** locked sync, actual
   prek execution, format parsers, negative input probes and actionlint pass.
   Actions/Gitleaks downloads use verified pins/checksums. Hosted jobs were
   requested but blocked before any step. Local success cannot establish them.
6. **Reference or unrelated checkout could be changed.** **Verified fine:** the
   supplied/copy SHA-256 and bytes match; the lowercase checkout is still clean;
   this branch retains the existing `f49845d` ancestor. No Deploy VI code is copied.
7. **Saved repository JSON could imply enforced protection.** **Partly verified,
   enforcement open:** supported settings were applied/read back. Ruleset access
   is denied by the account plan. The desired JSON is explicitly unapplied.
8. **Model/telemetry settings could overstate implementation.** **By design:**
   they encode the future runner contract, with absent-runner flags and retained
   unknowns. Provider capability and actual output persistence need later tests.

Fixed: worker configuration compatibility, staged secret coverage and stale
policy/status claims. Remaining unknowns are bounded below. Rewrite-tournament
does not apply: the
change consists of docs/configuration, a generated lock and an unchanged design
reference; no product function was written or modified.

Live worker routing, provider entitlement, high/xhigh mappings, model selection
and telemetry retention require real later execution. Hosted checks and branch
enforcement are separate from local success. Raw validation logs stay in ignored
`artifacts/setup/`.
