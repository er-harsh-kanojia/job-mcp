# Job MCP web

The local dashboard for Job MCP: search, bulk apply, the applications tracker, resume review and interview prep, platform sessions and the profile. It's built with React, TypeScript, Vite, Tailwind CSS v3, react-router and TanStack Query. It talks only to the local API described in `../docs/api-contract.md`.

## Requirements

Node 22 and npm 10. Install once:

```sh
cd web
npm install
```

## Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | Vite dev server on http://localhost:5173. `/api` is proxied to the backend at `http://127.0.0.1:8765`, so start the backend first (`python app.py`). |
| `npm run dev:mock` | The same UI against an in-memory mock API (no backend needed). Search, apply, resume analysis and the interview chat are simulated, including their SSE streams. |
| `npm run build` | Type-checks (`tsc --noEmit`), then builds to `web/dist`. The backend serves `dist` at `/` with an SPA fallback. |
| `npm run typecheck` | `tsc --noEmit` only. |
| `npm run lint` | ESLint. |
| `npm run preview` | Serves the built `dist` locally (the API isn't proxied; use the backend to serve `dist` instead). |

## Mock mode

`dev:mock` runs Vite with `--mode mock`, which loads `.env.mock` (`VITE_MOCK=1`). The mock lives in `src/mocks/` and is loaded with a dynamic import behind a compile-time flag (`__MOCK__`), so production builds don't contain it.

The mock keeps its state in memory, so a full page reload starts it fresh. To preview other states, add URL flags on first load. They're remembered for that browser tab.

| Flag | Effect |
| --- | --- |
| `?mock_ai=claude`, `openai` or `none` | Which AI providers have a key. The default is both. |
| `?mock_down=1` | The backend is unreachable (shows the banner; retries every 10 s). |
| `?mock_empty=1` | First run: no sessions, no applications, no review. |
| `?mock_captcha=1` | Indeed answers searches with `captcha_required`. |
| `?mock_expired=1` | The Instahyre session has expired. |

Open a new tab to clear the flags.

## Layout

```
src/
  api/          typed client: types.ts (contract types), http.ts (fetch + EventSource), sse.ts (POST stream parser), errors.ts
  mocks/        in-memory mock API and sample data (dev:mock only)
  state/        app-level state: UI (theme, Dry run/Live, palette), search, bulk apply, long-running tasks
  lib/          query hooks and formatting helpers
  components/   shared UI: icons, badges, pills, alerts, overlay
  features/     one folder per screen (dashboard, search, apply, applications, resume, platforms, profile, shell)
  styles/       design tokens (tokens.css) and component classes ported from the design (index.css)
```

## Notes

- Live mode is never remembered: every session starts in Dry run. A live run needs APPLY typed on the Confirm step, and the client then sends `confirm: "APPLY"`.
- The theme (light or dark) is saved in `localStorage` and applied before first paint.
- API keys are never entered or shown in the UI. They live in `D:\Job-MCP\.env`.
