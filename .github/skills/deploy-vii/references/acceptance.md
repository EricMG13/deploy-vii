# Native acceptance checklist (none of it is accepted yet)

Offline, `tests/devtools/test_skill_package.py` checks the package shape only. Each item
below needs the real enterprise Copilot host and is NOT accepted:

- [ ] Org/repo skills are enabled and `.github/skills` loads; `/skills info deploy-vii` shows it.
- [ ] A prompt describing a Deploy VII run dispatches the skill by its description.
- [ ] Shell permission prompts appear per command (no `allowed-tools` is declared).
- [ ] A full CP-0 then CP-1 run completes through the commands in `SKILL.md`.
- [ ] Tool-output and context limits hold for large journal and step outputs (no numbers
      are documented by the host).
- [ ] Interrupt works, and a killed session or process resumes from the journal as
      `resume.md` describes.
- [ ] Backend injection blocking does not break source-derived text.
- [ ] The report files land where the user can open them.

Known product gaps are listed in `SKILL.md` and `docs/native-delivery.md`.
