import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // `src-tauri` muss mit ignoriert werden: dort liegen nach einem Release
  // der gepackte Sidecar und der Rust-Build-Cache. `npm run lint` lief sonst
  // über fremde JS-Dateien (Tauri-Codegen, matplotlib-Web-Backend) und
  // meldete Parse-Fehler, die mit unserem Code nichts zu tun haben — die
  // Doku führte Lint deshalb als „rot", obwohl `eslint src` grün war.
  globalIgnores(['dist', 'src-tauri']),
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
  },
])
