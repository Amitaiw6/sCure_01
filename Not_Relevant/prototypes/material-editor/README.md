# Not_Relevant/prototypes/material-editor/

Dead-end standalone program editor page (2026-08 cleanup). It was only reachable via the `/material-editor` route in
`src/App.tsx`; nothing navigated to it, and it is not in the SRS or the qa-tool. The live program editor is
`src/components/CsvBuilderModal.tsx` (opened from `HomePage`). These files also re-declared the step-type unions and
temperature limits now owned by `src/context/MaterialContext.tsx` / `src/lib/limits.ts`.

| Here | Original path |
|---|---|
| `MaterialEditorPage.tsx` | `src/pages/MaterialEditorPage.tsx` |
| `StepCard.tsx` | `src/components/StepCard.tsx` |
| `StepModal.tsx` | `src/components/StepModal.tsx` |
| `material-editor.png` | `docs/screenshots/material-editor.png` |

Imports inside these files still use the `@/` alias of their original locations; they will not compile as-is here.
