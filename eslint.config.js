import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'Not_Relevant', '.venv', 'design-handoff', 'qa-tool']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // HMR-only heuristic. The project convention deliberately exports
      // `XProvider` + `useX()` from one context file and cva variants from
      // shadcn primitives; the kiosk build does not rely on Fast Refresh.
      'react-refresh/only-export-components': 'off',
    },
  },
])
