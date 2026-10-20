# Research foundation verification — 2026-10-20

Historical snapshot from the removed setup attempt, not current Deploy VII status.
See the [current index](../README.md) and [later findings](recovered-follow-up-findings.md).

The private repository `EricMG13/deploy-vii` was created and its Private badge
verified in the signed-in GitHub UI. Local project: `Documents/deploy-vii`.
No product code, issuer tests, model calls or global hook changes were made.

## Local checks

- `uvx --from pre-commit==4.6.2 pre-commit run --all-files --show-diff-on-failure`:
  exit 0; all seven hygiene hooks pass.
- `gitleaks dir --redact --no-banner --no-color --ignore-gitleaks-allow .`:
  exit 0; no leaks found before committing.
- `git diff --cached --check`: exit 0.
- `gitleaks git --log-opts='--all --full-history' --redact --no-banner
  --no-color --ignore-gitleaks-allow .`: exit 0; one commit scanned, no leaks.
- The workflow's complete change-size step ran locally on the initial commit:
  exit 0, within the 800-line cap. This does not establish a hosted CI result.
- Inline Python configuration audit: exit 0; job/ruleset contexts agree, Actions
  use full commit pins, workflow Bash parses, five agent profiles have intended
  model/effort/tool fields, and local Markdown links resolve.
- The workflow's exact size expression accepts 0/800 changed lines and rejects
  801, counting deletions as well as additions. Boundary-check command: exit 0.
- Official Gitleaks 8.30.1 checksums confirm the workflow's Linux x64 archive hash.

## Confidence review

Ranked doubts and results:
1. Accidental qualification claims: inspected README, policies and settings;
   future product/live gates are explicitly unimplemented. Fine by design.
2. Model routing drift: removed a proposed extra implementation role; retained
   mx-scaffold/mx-feature, with a fresh high-effort mx-feature for sensitive work.
   Profile fields validate; actual host routing remains open.
3. CI enforcement mismatch: checked job names against both settings files and
   GitHub's documented ruleset fields. Size boundaries pass; hosted execution
   remains open. GitHub's UI explicitly reports private ruleset enforcement
   unavailable under the current account setup; this is a confirmed limit.
4. Secret-scan completeness: retained full history, explicit nonempty and
   nonshallow guards, error refusal and checksum pin. Directory scan passes.
5. Hook-policy conflict: documented the inherited retired tournament injection;
   local policy rejects it. Effective hook behavior is still unmeasured.

Publication is pending: GitHub CLI authentication is invalid and Git HTTPS
credentials are unavailable. The local package is ready; the remote repository
is still empty. No credentials were extracted or changed.

The GitHub branch-ruleset form contains the default-branch target, zero required
approvals, resolved conversations, strict Repository hygiene/Secrets checks,
deletion/force-push restrictions and no bypass actors. Saving reached GitHub's
Confirm access dialog and awaits owner authentication; it is not confirmed saved.
Browser file upload also requires extension file-URL access, which was not enabled.
No paid plan, ownership or repository-visibility change was made.

Not verified: remote contents/CI, saved ruleset, model-profile loading,
OpenRouter or native Copilot acceptance, performance gains or method equivalence.
