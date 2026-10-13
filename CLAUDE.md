@AGENTS.md

## Claude Code specifics

- Start the task with `/task-kickoff` (add `fable` to use `architect-fable`). Build with the `verify` skill.
- Subagents are in `.claude/agents/`. Give each one the unit, the files, and the proof command; ask for a short report.
- Skills in `.claude/skills/` can be invoked by you or by name (`/principle-model-the-domain`). Only one slash command is read per message, so name further skills in prose ("also apply principle-prove-it-works").
- `domain-modeling` expects `GLOSSARY.md` and `docs/adr/`; here the glossary is `docs/GLOSSARY.md` and ADRs are entries in `docs/DECISIONS.md`.
