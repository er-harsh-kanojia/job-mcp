# Job MCP

A local tool for searching and applying to jobs on Indian job portals and a few remote job boards. It runs on your own machine and drives a real browser with your own logged-in sessions.

You can use it three ways:

- a web app at http://127.0.0.1:8765 (`app.py`, or `start.bat` on Windows)
- a small interactive CLI (`run.py`)
- an MCP server for Claude Desktop and Claude Code (`server.py`)

## What it does

- Searches several portals at once and ranks the results against your profile (title, skills, experience, location). Filters for minimum match score, excluded companies and visa sponsorship.
- Bulk applies to the jobs you select. Every run can be a dry run first: it fills the forms but stops before the final submit.
- Autopilot: runs a search and apply on a schedule (by default 09:30 and 18:30), with a daily limit per platform. It starts switched off and in dry-run mode.
- Answers: when an application asks something the bot doesn't know, the question is saved on the Answers page. Answer it once and it is reused on every later job that asks the same thing.
- Applications tracker with history and stats, stored in a local SQLite file.
- Resume and prep (optional, needs an AI API key): resume review and ATS score, skill demand from live listings, a two-week prep plan and mock interviews.

## Supported sites

| Site | Login | Search | Apply |
| --- | --- | --- | --- |
| Naukri | your account | yes | automatic |
| Instahyre | your account | yes | automatic |
| Hirist | your account | yes | automatic |
| Himalayas | not needed | yes | on the site ("Apply on site") |
| YC job board | not needed | yes | on the site ("Apply on site") |

Planned: LinkedIn, Wellfound, Indeed, Welcome to the Jungle (needs an account even to search) and HiringCafe (blocks automated access).

"Apply on site" opens the job in a new tab and marks it as applied in the tracker. Jobs that are only applied to on the employer's site are skipped by bulk apply and autopilot.

## Setup

You need Python 3.10 or newer and Node.js. The setup script checks both (on Windows it can install them with winget), creates `.venv`, installs the Python packages and Playwright's Chromium, builds the web app, and creates `.env` and `config.json` from their templates.

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

or double-click `setup.bat`.

Linux, macOS or Git Bash:

```bash
chmod +x setup.sh start.sh
./setup.sh
```

Then fill in `config.json` (name, contact details, experience, notice period, expected CTC, preferred locations, and so on). These values are used to answer application forms. You can also edit them later on the Profile page.

`autofill.standard_answers` holds your answers to the common yes/no questions: relocation, visa sponsorship, work authorization, office/shift/commute conditions, background declarations and consent. Nothing is assumed: a question whose answer is left empty is saved to the Answers page instead of being guessed. Set `needs_visa_sponsorship` to `if_job_sponsors` to answer "Yes" for jobs marked as offering visa sponsorship and "No" for the rest.

All of your own data stays in files that git ignores: `config.json` (profile and answers), `.env` (API keys), `data/` (resume, saved answers, application history) and `.sessions/` (logins).

### AI features (optional)

Searching and applying work without any API key. The resume review, ATS score, prep plan and mock interviews need one key in `.env`:

```ini
ANTHROPIC_API_KEY=...
# or
OPENAI_API_KEY=...
```

With both set, you can switch providers under Profile > AI provider. Restart the app after editing `.env`.

## Running

```bash
start.bat
# or
.\.venv\Scripts\python.exe app.py
```

On Linux or macOS use `./start.sh` or `./.venv/bin/python app.py`. The app opens in your browser at http://127.0.0.1:8765. Stop it with Ctrl+C.

A typical first run:

1. Open Platforms and log in to Naukri, Instahyre and Hirist. A browser window opens and you sign in yourself, including any OTP. The session is saved under `.sessions/` and reused.
2. Run a search, select jobs and start a bulk apply in dry-run mode. Check the results, then switch to live mode.
3. Optional: turn on Autopilot once a dry run looks right.

Autopilot only runs while the app is running, so your computer needs to be on at the scheduled times. A slot that was missed by up to three hours still runs.

## CLI

```bash
.\.venv\Scripts\python.exe run.py
```

The menu has: log in to a platform, search and apply (starts with a dry run), application status, and search only.

## MCP server

Claude Code:

```bash
claude mcp add job-mcp -- <path-to-repo>\.venv\Scripts\python.exe <path-to-repo>\server.py
```

Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json` on Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "job-mcp": {
      "command": "<path-to-repo>\\.venv\\Scripts\\python.exe",
      "args": ["<path-to-repo>\\server.py"]
    }
  }
}
```

Tools: `list_platforms`, `login_platform`, `search_jobs`, `apply_to_jobs`, `application_status`, `review_resume`, `interview_prep`.

## Excluding companies

Add company names in the Exclude filter on the Search page for one search, or under Excluded companies on the Profile page to keep them excluded. Jobs from those companies are hidden and never applied to. The API and the `search_jobs` tool accept `exclude_companies` too.

## Project layout

```
api/            FastAPI routes and background tasks (search, apply, login, autopilot)
web/            React + Vite front end
tools/
  platforms/    one adapter per site (naukri, instahyre, hirist, himalayas, ycombinator)
  ai/           resume review, demand analysis, prep plan, mock interviews
  autofill.py   answers to application questions from your profile
  answers.py    saved answers and questions waiting for you
  autopilot.py  schedule, daily limits and job selection
  browser.py    Playwright sessions
  scoring.py    match and rank scores
  search.py     search across platforms
  tracker.py    SQLite store for jobs and applications
tests/          unit and API tests (python -m unittest discover -s tests -t .)
app.py          web app launcher
run.py          CLI
server.py       MCP server
```

## Privacy

- You log in yourself in a real browser window; the app keeps only the session cookies in `.sessions/`. It never types or uses a password. `config.json` has credential fields, but only the e-mail is used, to prefill the login form.
- `config.json`, `.env`, `.sessions/` and `data/` are in `.gitignore`. Keep your profile, keys and application history out of commits.
- The server listens on 127.0.0.1 only. Nothing is sent anywhere except to the job sites you use and, if you set a key, the AI provider for the resume and prep features.
