# CLAUDE.md — sCure_01

@AGENTS.md

## How to work in this repo

This is a **brownfield project with working code**. Every task follows the BMAD workflow described in `AGENTS.md`:

**Requirement → Codebase Analysis → Architect/Plan → Implementation → Simplification → Tests → Code Review**

- For any feature, fix or change request: invoke the `bmad-build` skill with the request. It plans first (Architect writes a spec, you approve), then implements, then runs the review layers including the team's `reuse-audit` and `simplification` layers.
- Do not start editing application code from a bare request without a plan; if the change is a genuine one-liner with zero blast radius, `bmad-build` routes it to its one-shot path itself.
- Deeper map of modules, flows and reusable symbols: `docs/project-context.md` (read it before planning; it is also auto-loaded by the BMAD skills).
- Team BMAD customizations live in `_bmad/custom/*.toml`; personal ones go in `*.user.toml` (gitignored). Use the `bmad-customize` skill to change them.
- Never edit `_bmad/config.toml`, `_bmad/config.user.toml` or anything under `.claude/skills/bmad-*` by hand — the installer regenerates them.

## Core rules (apply even outside BMAD skills)

1. REUSE BEFORE CREATE — search first, extend existing code, no duplicate functionality.
2. Minimal, localized change; no unnecessary abstractions; do not redesign working parts unless required.
3. Preserve existing behavior unless the requirement explicitly changes it.
4. Run `npm run build` and `npm run lint` for `src/` changes, `python -m py_compile` (+ simulator / `qa-tool`) for Python changes, before calling anything done.
5. Prefer simple, readable, boring code.
