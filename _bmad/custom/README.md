# Team customizations for BMAD (sCure_01)

TOML overrides for the installed BMAD skills (`.claude/skills/bmad-*`). Committed; apply to everyone.
`*.user.toml` files are personal and gitignored.

| File | Purpose |
|---|---|
| `bmad-build.toml` | Main workflow: Requirement -> Analysis -> Architect/Plan -> Implement -> Simplify -> Tests -> Review. Adds REUSE/MINIMAL/VERIFY facts, the Architect reuse-investigation prepend step, and the `reuse-audit` + `simplification` review layers. |
| `bmad-code-review.toml` | Standalone review with the same extra layers. |
| `bmad-review.toml` | Adds a `simplification` lens to the generic reviewer. |
| `bmad-agent-architect.toml` / `bmad-agent-dev.toml` | Persona principles for Architect (Winston) and Dev (Amelia). |
| `config.toml` / `config.user.toml` | Central config overrides (installer-provided placeholders). |

Merge rules: scalars override, arrays append, arrays-of-tables keyed by `id`/`code` replace on match.
Edit with the `bmad-customize` skill or by hand; verify with
`uv run _bmad/scripts/resolve_customization.py --skill .claude/skills/<skill> --key workflow --project-root .`
