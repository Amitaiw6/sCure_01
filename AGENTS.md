<!-- bmad:context -->
<!-- Verified 2026-08-17 against working tree (git HEAD 51e3f9f is an unrelated prototype). Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->
## sCure_01
Kiosk software for the sCure Box (UV post-curing enclosure for 3D prints) on a Raspberry Pi. React 19/TypeScript/Vite kiosk UI in `src/`, Python/Flask API in `server/`, hardware drivers in `io_controller/`, cloud portal in `cloud/`. Requirements: `docs/sCure_SRS.html`. Full architecture and reuse map: `docs/project-context.md`. BMAD planning/spec output: `_bmad-output/`.

## Policy
- REUSE BEFORE CREATE: search the repo and read `docs/project-context.md` before designing; modify existing functions/components/endpoints instead of adding parallel ones. A new file, class, service or abstraction needs a written reason why no existing one could be extended.
- Minimal, localized change: touch the fewest files, no unrelated refactoring, no redesign of working parts unless the requirement demands it. Preserve existing behavior unless the requirement explicitly changes it.
- Never commit `keys/scure-update.key`, `.mcp.json` tokens, `server/data/`, or `cloud/portal_config.json`; they hold secrets or device data.
- Legacy standalone drivers, Tk dashboards, the C++ hardware driver, bench-analysis scripts and UI prototypes were removed in the 2026-08 cleanup (recover from git commit `32997e0` under `Not_Relevant/` if ever needed); the live driver is `io_controller/io_controller.py` (via `server/io_bridge.py`).
- Process modules own no hardware: act only through `SystemController` verified functions (`set_and_verify`), never write PCA/GPIO directly from server code.
- Add error codes to `public/config/errors.json`; never invent inline codes. User-visible errors are raised via the alert registry (`triggerAlert` / `scure-alert` event).

## Where things are
- All frontend HTTP calls + `API_BASE`: `src/services/hardware-api.ts`; process limits: `src/lib/limits.ts`; live state: `src/context/HardwareContext.tsx`; cure state machine: `src/pages/CureProcessPage.tsx`; CSV/program rules: `parseCsv()` in `src/context/MaterialContext.tsx`.
- All API routes: `server/app.py`; hardware facade/simulation: `server/hardware_controller.py`; JSON persistence: `server/storage.py`; cloud agent: `server/cloud_sync.py`; API→hardware mapping: `server/io_bridge.py`; safety/interlocks: `SystemController` in `io_controller/io_controller.py`; tuning: `io_controller/components.json`.
- Team BMAD overrides: `_bmad/custom/*.toml` (workflow rules, review layers).

## Running and verifying
- Gates: `npm run build` (includes `tsc -b`), `npm run lint`, `npm test` (vitest, pure logic) for `src/`; `python -m pytest` (server/tests, io_controller/tests, simulation) and `python -m py_compile server/*.py io_controller/*.py` for Python; `qa-tool/index.html` against a running server for end-to-end. State in every plan which of these you ran.
- Off the Pi everything runs in simulation: `hardware-api.ts` returns `{ok:true, 'Simulated in dev mode'}` when the API is unreachable, and `server/app.py` simulates hardware when no IO board is present. Do not mistake simulated success for verified hardware behavior.
- BMAD skills need `uv` on PATH and UTF-8 stdout (`PYTHONUTF8=1`, set in `.claude/settings.json`).

## Conventions that differ from defaults
- No type hints in Python; contracts live in docstrings. Hardware ops return `(ok, reason)`; HTTP returns `{ok, code, message}`. JSON keys camelCase, Python/SQL snake_case.
- Frontend: fixed 800x480 canvas, dark-only, English-only (`translate="no"`), touch targets 44-48 px, `touch-manipulation` on interactive elements; network calls wrapped in `try/catch` + `AbortSignal.timeout` and degrade instead of throwing.
- Files must persist via the atomic write idiom (`tmp` → `flush` → `fsync` → `os.replace`) already used in `server/storage.py`.
- `*.sh` and `*.service` are LF-only (`.gitattributes`); they run on the Pi.

## Known pitfalls
- Process limits and step types have one source (`src/lib/limits.ts`, `ProcessType` in `MaterialContext`) and one `API_BASE`; do not re-declare them locally.
- Server validation limits (`server/app.py`: heat 30-80, cool 20-80, UV >= 10) intentionally differ from UI product limits (`limits.ts`: cool 30-75); do not "align" them.
<!-- /bmad:context -->

## Development workflow (BMAD, brownfield)

**Requirement → Codebase Analysis → Architect/Plan → Implementation → Simplification → Tests → Code Review**

| Step | Who / skill | What must happen |
|---|---|---|
| Requirement | you + `bmad-build` step 1 | Clarify intent; single goal per spec |
| Codebase analysis | Architect (`bmad-build` step 2, subagents) | Search the repo; list existing symbols to REUSE/MODIFY in the spec's Code Map |
| Architect / Plan | Architect (`bmad-build` step 2 → spec in `_bmad-output/implementation-artifacts/spec-*.md`) | Minimal file list, preserved behavior, verification commands; **human approves before code** |
| Implementation | Developer (`bmad-build` step 3, subagent) | Implement only the approved spec |
| Simplification | `simplification` review layer (+ dev self-pass) | Behavior-preserving shrink of the diff |
| Tests | spec `## Verification` commands | `npm run build`, `npm run lint`, py_compile / simulator / qa-tool |
| Code review | `bmad-build` step 4 layers: blind-hunter, edge-case, verification-gap, **reuse-audit**, **simplification** | Triage → patch / loop back / defer |

Entry points: `bmad-build "<requirement>"` for a feature/fix; `bmad-code-review` for a standalone review; `bmad-review` for reviewing a doc/spec; `bmad-project-context refresh` after significant architectural change; `bmad-help` when unsure. Larger multi-story work: `bmad-prd` → `bmad-architecture` → `bmad-create-epics-and-stories` → `bmad-build` per story.
