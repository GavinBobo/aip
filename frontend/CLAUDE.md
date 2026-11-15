<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

@AGENTS.md

## Frontend Rules

- **Next.js 16**: Has breaking changes from prior versions. Read `node_modules/next/dist/docs/` before writing Next.js-specific code. See `frontend/AGENTS.md` for details.
- **Formatting**: Prettier. **After editing ANY frontend file, ALWAYS run `pnpm format` (or `cd frontend && npx prettier --write <file>`) to auto-format it.** Never rely on manual formatting — always let Prettier handle it. CI will reject unformatted code.
- **Linting**: ESLint. Fix all lint errors; do not disable rules without a comment explaining why.
- **Components**: Arrow function components. No class components.
- **Styling**: Tailwind CSS 4. Do not write inline styles or separate CSS files for component styling.
- **Types**: TypeScript strict mode. No `any` without a comment. Types go in `/frontend/types`, enums in `/frontend/enums`.
- **API layer**: Use the `requests` wrapper from `frontend/api/requests.ts` — do not call axios directly. Base URL and error handling are already centralised there.
- **Pure logic goes in `lib/`**: anything that does not need React (geometry, layout, undo stacks, serialisation, export) belongs in `frontend/lib/<area>/` as plain functions or classes. Page components compose; they do not own rules. `components/` may import `lib/`, never the reverse.
- **Unit tests**: `pnpm test` (vitest, `frontend/vitest.config.ts`) covers `lib/**/*.test.ts`. Add a test next to the module when you add a rule there — the canvas has no DOM tests, so `lib/` is the only place a geometry or history regression gets caught before the browser.

## Localization

The UI ships in English and Simplified Chinese; the switch sits beside the account
menu (`i18n/LanguageToggle.tsx`) and the choice is kept in `localStorage`.

- Wrap every user-facing string in `t(...)` from `@/i18n` and add its Chinese copy
  to `i18n/messages/zh.ts`. The English text in the component is the key, so an
  untranslated string falls back to English instead of showing a key name.
- Interpolate with named or positional placeholders — `t('{0} rows', { 0: count })`,
  `t('Delete "{0}"?', { 0: name })` — rather than concatenating translated
  fragments, whose word order differs between the two languages.
- Module-level label maps (navigation items, table column definitions, option
  lists) must keep English and be translated where they are rendered
  (`t(MAP[key])`): values evaluated at import time would freeze the first locale.
- Backend-provided strings that reach the screen (agent step labels, for example)
  are translated at the display site when the dictionary has an entry.
