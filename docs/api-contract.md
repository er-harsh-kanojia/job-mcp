# Job MCP local web API: contract (v1)

The backend (FastAPI, `api/`) and the frontend (React, `web/`) are built against this file. If you need to change it, change this file first and keep both sides in sync.

- Base: `http://127.0.0.1:8765`. The server binds to localhost only.
- The API lives under `/api`. The built frontend (`web/dist`) is served at `/`, with SPA fallback to `index.html`.
- In dev, Vite runs on `:5173` and proxies `/api` to `:8765`.
- JSON everywhere. Times are ISO 8601 local time strings.
- Errors use the shape `{"error": {"code": "snake_case", "message": "Human readable", "detail": {...}?}}` with a fitting HTTP status.
- Long-running work (search, apply, login, resume analysis) is a **task**. Starting one returns `{"task_id": "..."}`. Progress streams as Server-Sent Events from `GET /api/tasks/{task_id}/events`. Each SSE message has `event: <type>` and `data: <json>`. The stream always ends with a `done` or `error` event. `GET /api/tasks/{task_id}` returns the latest snapshot `{id, kind, status: "running"|"done"|"error"|"cancelled", result?, error?}`, and `POST /api/tasks/{task_id}/cancel` asks the task to stop.

## Shared types

```ts
type Platform = "naukri" | "instahyre" | "indeed";          // live ones; GET /api/platforms is the source of truth
type Job = {
  platform: Platform; job_id: string; title: string; company: string; location: string;
  salary: string;            // "18–28 LPA" or "Not disclosed"
  apply_url: string;         // unique key
  description: string; skills: string[];
  exp_min: number; exp_max: number;   // -1 = unknown, 99 = open-ended "N+"
  posted_days_ago: number;            // -1 = unknown
  match_score: number; rank_score: number;   // 0–1
  easy_apply: boolean;
  already_applied: boolean;           // from the tracker
};
type AppStatus = "applied" | "failed" | "skipped" | "dry_run";
type Application = { id: number; platform: Platform; job_id: string; title: string; company: string;
  location: string; apply_url: string; status: AppStatus; error: string | null; applied_at: string };
```

## Health and platforms

- `GET /api/health` returns `{ok: true, version, mcp_tools: number, ai: {configured: boolean, provider: "anthropic"|"openai", provider_name: string, model: string|null}}`. `configured` describes the selected provider.

## AI provider settings

There are two providers: Anthropic (Claude) and OpenAI (ChatGPT). API keys live only in `.env` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) and are never sent or returned over the API. The selected provider is stored in `config.json` under `"ai": {"provider": "anthropic"|"openai"}` (default `anthropic`; falls back to whichever one has a key).

- `GET /api/settings/ai` returns `{provider, providers: [{id: "anthropic", name: "Claude (Anthropic)", short: "Claude", configured: boolean, model: string}, {id: "openai", name: "ChatGPT (OpenAI)", short: "ChatGPT", configured: boolean, model: string}]}`
- `PUT /api/settings/ai` takes `{provider}` and returns the same shape. It returns 400 `provider_not_configured` if that provider has no key.
- UI copy uses the selected provider's `short` name: "Practise with Claude" / "Practise with ChatGPT", and "Reviewed … by ChatGPT".
- `GET /api/platforms` returns `{platforms: [{id, name, live: boolean, session: "logged_in"|"expired"|"not_set_up"|"unknown", last_checked: string|null}]}`. It includes the planned ones (linkedin, wellfound, hirist) with `live: false`.
- `POST /api/platforms/{id}/check` re-checks the session headlessly and returns the platform object.
- `POST /api/platforms/{id}/login` starts a task that opens a visible browser for a manual login. Events: `status {state: "waiting_for_user"|"captcha"|"logged_in"|"timeout"}`, then `done {platform}`.

## Search

- `POST /api/search` takes `{keywords: string[], location: string, experience_years: number, platforms: Platform[], min_match_score: number}` and returns `{task_id}`.
- Events:
  - `platform {platform, state: "queued"|"fetching"|"done"|"failed"|"skipped", count?: number, reason?: "captcha_required"|"session_expired"|"timeout"|"error", message?: string}`
  - `jobs {platform, jobs: Job[]}` (partial results as each platform finishes)
  - `done {total: number, shown: number, jobs: Job[]}` (the final list: scored, deduped, filtered by min score, sorted by rank_score desc)
- `GET /api/search/last` returns the last finished search `{params, finished_at, platforms: [...platform events], jobs: Job[]} | null`. Results are also cached to SQLite so the resume features can use them.

## Bulk apply

- `POST /api/apply` takes `{apply_urls: string[], max_applications: number, dry_run: boolean, confirm?: "APPLY"}` and returns `{task_id}`.
  - Live runs (`dry_run: false`) require `confirm: "APPLY"`. Without it the server returns 400 `confirm_required`.
  - The jobs are looked up from the last search cache by `apply_url`.
- `POST /api/apply/preview` takes `{apply_urls, max_applications}` and returns `{will_apply: Job[], will_skip: [{job: Job, reason: "already_applied"|"not_easy_apply"|"over_limit"|"session_expired"}]}`. No browser is used.
- Events:
  - `job {apply_url, title, company, platform, state: "queued"|"applying"|"applied"|"dry_run"|"failed"|"skipped", error?: string, permanent?: boolean}`
  - `progress {done: number, total: number}`
  - `done {summary: {dry_run, attempted, applied, would_apply, failed, skipped, already_applied, by_platform}, applied: [...], failed: [...], skipped: [...]}`
- Cancelling stops after the current job finishes.

## Applications tracker

- `GET /api/applications?days=7&status=applied,failed&platform=naukri` returns `{applications: Application[]}`. `days` is omitted or `0` for all time.
- `GET /api/stats` returns `{applied_today, applied_week, success_rate /*0–1, applied/(applied+failed) over 30d*/, by_platform: {[p]: {applied, failed, skipped, dry_run}}, recent: Application[] /*last 10*/}`

## Profile

- `GET /api/profile` returns `{name, email, phone, location, experience_years, resume: {filename, size_bytes, uploaded_at} | null, autofill: {current_ctc, expected_ctc, total_experience, notice_period, gender, highest_qualification, graduation_year, primary_cloud, contract_based, offer_in_hand, last_working_day, experience: {[skill]: string}, preferred_locations: string[]}}`. **Credentials are never returned.**
- `PUT /api/profile` takes the same shape (partial is OK) and returns the updated profile. Validation errors return 422 `{error: {code: "validation", detail: {field: message}}}`. It writes `config.json` and keeps the `credentials` block untouched.
- `POST /api/profile/resume` takes multipart `file` (.pdf/.doc/.docx, ≤ 5 MB) and returns `profile.resume`. The file is stored under `data/resume/`, and `resume_path` in `config.json` is updated.

## Resume review and prep (AI, Claude API)

AI endpoints use the selected provider (see AI provider settings). They return 503 `ai_not_configured` when that provider's key is missing (read from env or `.env`), and the UI shows a setup state. `Review` also carries `provider: "anthropic"|"openai"`.

```ts
type Severity = "mistake" | "change" | "polish";
type ScoreKey = "accuracy" | "ats" | "fit" | "impact";
type Issue = { id: string; severity: Severity; title: string; where: string; why: string;
  before: string; after: string; note: string; gain: Partial<Record<ScoreKey, number>>;
  line_ids: string[];                         // which resume lines it highlights
  status: "open" | "fixed" | "dismissed" };
type ResumeLine = { id: string; text: string; kind: "name"|"role"|"text"|"bullet" };
type ResumeSection = { title: string; lines: ResumeLine[] };
type DemandRow = { skill: string; jobs: number; you: "strong" | "some" | "gap" };
type PlanItem = { id: string; week: 1 | 2; text: string; type: "Resume"|"Learn"|"Build"|"Practice"; time: string; hours: number; done: boolean };
type Question = { id: string; round: "llm"|"design"|"fund"|"code"|"behav"; q: string; why: string;
  outline: string[]; from_resume: string; practised: boolean };
type Review = {
  analysed_at: string; resume_filename: string; target_role: string; model: string;
  scores: Record<ScoreKey, number>;           // 0–100 each, as analysed
  overall: number;                            // 0–100 now (open issues), recomputed from statuses
  projected: number;                          // if every open issue were fixed
  issues: Issue[]; sections: ResumeSection[];
  prep: { matched_jobs: number; demand: DemandRow[]; plan: PlanItem[]; questions: Question[] } | null;
};
```

- `GET /api/resume/review?role=GenAI%20Engineer` returns `Review | null`, the stored review for that role (the latest one).
- `POST /api/resume/analyse` takes `{target_role: string}` and returns `{task_id}`. Events: `step {index: 0..3, label, state: "running"|"done"}`, using the four steps "Reading <file>", "Checking facts against your profile", "Comparing with N matched <role> jobs" and "Writing suggestions and a prep plan". Then `done {review: Review}`.
- `PATCH /api/resume/issues/{issue_id}` takes `{status: "open"|"fixed"|"dismissed"}` and returns `{overall, projected, issue}`.
- `PATCH /api/resume/plan/{item_id}` takes `{done: boolean}` and returns `{plan_item}`.
- `PATCH /api/resume/questions/{question_id}` takes `{practised: boolean}` and returns `{question}`.
- **Mock interview ("Practise with Claude"):**
  - `POST /api/interview/sessions` takes `{question_id, role}` and returns `{session_id, messages: [{role: "assistant", content}]}`. Claude opens by asking the question as the interviewer.
  - `POST /api/interview/sessions/{id}/messages` takes `{content}` and returns `text/event-stream`. Events are `delta {text}` (streamed tokens) and `done {message: {role: "assistant", content}, feedback?: {score: 1-10, strengths: string[], improve: string[]}}`. Once the candidate has answered and Claude has finished its follow-ups, it scores the answer and sends `feedback`. Feedback marks the question as practised.
  - `GET /api/interview/sessions/{id}` returns `{session_id, question_id, messages, feedback}`.

## Backend additions (additive, optional to use)

Everything above is implemented as written. These extra fields and endpoints are additive; nothing above was renamed or removed.

- **Tasks:** the snapshot also has `created_at` and `finished_at`. Every SSE message carries an `id:` (0, 1, 2, …), and reconnecting with a `Last-Event-ID` header resumes after that event. Subscribing late replays the whole stream. An `error` event's data is `{code, message}`. Cancelling an apply task finishes the current job, reports the remaining ones as `job {state: "skipped", error: "cancelled"}`, and ends with `done` (`summary.cancelled: true`, task status `"cancelled"`). Cancelling any other task stops it immediately and ends with `error {code: "cancelled"}`.
- **Platforms:** `POST /api/platforms/{id}/check` may return `session: "unknown"` plus `error` when the check could not run. Planned platforms return 400 `platform_not_live` for check and login, and unknown ids return 404. Login takes an optional body `{timeout_seconds}` (30–1800, default 300). Its `status` events may include `message`, and its `done` is `{platform: id, status, platform_info: <platform object>}`.
- **Search:** the body also takes `limit_per_platform?: number`. A `platform` event with `state: "done"` can still carry `reason`/`message` when a platform returned partial results (for example, a captcha after page 1). `GET /api/search/last` also returns `total`.
- **Apply:** the preview also returns `not_found: string[]` (URLs not in the cache). `POST /api/apply` returns 400 `jobs_not_found` when none of the URLs are cached. The `done` summary also has `requested`, `considered` and `cancelled`.
- **Stats:** `window_days: 30` is included, and `by_platform` covers the same 30 days.
- **Profile:** `phone` is stored as the normalised 10-digit number (accepts `+91`, `0`, spaces and dashes). A wrong upload type returns 422 `validation` `{file}`, and an upload over 5 MB returns 413 `file_too_large`.
- **AI errors:** 503 `ai_not_configured` (selected provider has no key), 400 `provider_not_configured` (PUT settings), 429 `ai_rate_limited`, 422 `ai_refused`, and 502 for other upstream failures (`ai_auth`, `ai_model`, `ai_bad_request`, `ai_unavailable`, `ai_unreachable`, `ai_invalid_output`). `POST /api/resume/analyse` returns 400 `resume_missing` / `resume_legacy_doc` / `resume_empty` / `resume_unreadable` / `resume_type` before starting a task when the resume can't be read. Reading stored reviews and the PATCH endpoints work without a key.
- **Review:** the review also has `id` (number) and `provider`. `prep` also has `demand_source: "jobs" | "estimate"`, `demand_scale` (the denominator for `DemandRow.jobs`: `matched_jobs` when counted from cached jobs, or 100 when estimated per 100 typical postings because fewer than 5 matching jobs were cached) and `note` (one sentence on the demand basis). `GET /api/resume/review` with no `role` returns the latest review of any role. `GET /api/resume/reviews` returns `{reviews: [{review_id, target_role, analysed_at, overall, projected}]}` (the latest per role).
- **Interview:** in `POST /api/interview/sessions`, `role` is optional and defaults to the review's target role. The message stream can end with `error {code, message}` instead of `done` if the AI call fails mid-stream. Posting to a finished session (feedback already given) returns 409 `interview_finished`. `GET /api/interview/sessions/{id}` also returns `role`. Feedback comes at the latest after the candidate's third answer (the question plus two follow-ups).
- **Diagnostics:** `GET /api/diagnostics/browser` launches headless Chromium to `about:blank` from inside the API process and returns `{ok, browser_version?, url?, loop, error?}`.
