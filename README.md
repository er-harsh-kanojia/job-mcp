# Job MCP

Search and apply to jobs on **Naukri**, **Instahyre**, and **Hirist (hirist.tech)** from one unified interface:
- **Local Web UI** (`app.py` / `start.bat`) running at [http://127.0.0.1:8765](http://127.0.0.1:8765)
- **Interactive CLI** (`run.py`)
- **MCP Server** (`server.py`) for Claude Desktop and Claude Code

The web UI also includes an AI **Resume and prep** suite:
- **Resume Review & ATS Scoring**: In-depth review scored on accuracy, ATS compatibility, role fit, and impact.
- **Skill Demand Analysis**: Aggregated from real live job listings.
- **2-Week Prep Plan**: Structured roadmap tailored to your target role.
- **Interactive Mock Interviews**: Real-time mock interview sessions with immediate AI feedback.

---

## ⚡ Quick Start / One-Command Setup

You can run setup in **one command**—either directly yourself or by telling **Claude Code / Cursor / Any AI Assistant**:

> *"Run setup.bat to set up everything automatically."*

### On Windows (CMD / PowerShell / Double-click)

Run `setup.bat` or run in PowerShell:
```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```
*(Or simply double-click `setup.bat` in File Explorer).*

### On Linux / macOS / Git Bash

```bash
chmod +x setup.sh start.sh
./setup.sh
```

### What the Setup Script Automates:
1. **Python Check**: Verifies Python 3.10+ is installed (automatically installs Python 3.12 via `winget` if missing on Windows).
2. **Node.js & npm Check**: Verifies Node.js & npm are present (automatically installs Node.js LTS via `winget` if missing).
3. **Virtual Environment**: Creates `.venv` if not already present.
4. **Python Dependencies**: Upgrades `pip` and installs all packages from `requirements.txt`.
5. **Playwright Chromium**: Downloads the Chromium browser for scraping and applications.
6. **Frontend Build**: Runs `npm install` and `npm run build` in `web/` to produce the production bundle.
7. **Config & Environment**: Generates `.env` from `.env.example` and `config.json` from `config.example.json` if they don't exist yet.

---

## 🔑 AI Resume & Prep Setup (Adding Your API Key)

> [!IMPORTANT]
> **API Key Required for AI Features**:
> Core job searching and automated applications (Naukri, Instahyre, Hirist) work **completely free without any AI keys**.
>
> However, to use the AI **Resume Review**, **ATS Scorer**, and **Mock Interview** features, you must provide your own API key in `.env`.

### 1. Create your `.env` file
If not created automatically by `setup.bat`, copy the template:
```bash
# Windows
copy .env.example .env

# Linux / Mac / PowerShell
cp .env.example .env
```

### 2. Add your Anthropic or OpenAI API Key
Open `.env` in any text editor and paste your key:

```ini
# Claude (Anthropic): https://console.anthropic.com/settings/keys
ANTHROPIC_API_KEY=sk-ant-api03-...

# OR ChatGPT (OpenAI): https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-proj-...
```

- You need **at least one** key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`).
- If you provide both, you can toggle between Claude and OpenAI directly inside the Web UI (**Profile > AI Provider**).
- Restart the app after editing `.env`. Keys are read only locally on your machine and are never sent anywhere else.

---

## 🚀 Running the Web UI

### Option 1: Double-click `start.bat`
```bash
.\start.bat
```

### Option 2: Run via Python directly
```bash
.\.venv\Scripts\python.exe app.py
```
*(On Linux/Mac: `./.venv/bin/python app.py` or `./start.sh`)*

- Opens automatically in your default browser at: **[http://127.0.0.1:8765](http://127.0.0.1:8765)**
- To stop the server, press `Ctrl + C` in the terminal window.

---

## 🖥️ Using the Interactive CLI

```bash
.\.venv\Scripts\python.exe run.py
```

1. **Login**: Opens a visible browser window for one platform. Sign in manually once; your session cookies are stored securely under `.sessions/<platform>` and reused for future runs. Passwords are never typed or stored by code.
2. **Search & Apply**: Always starts in **Dry Run** mode first. A dry run navigates forms and fills details, but **never clicks the final submit button**, allowing you to inspect results safely.
3. **Status**: Shows your application history and statistics from `data/applications.db`.
4. **Search only**: Search and rank jobs across platforms without applying.

---

## 🤖 Register with Claude (MCP Server)

Job MCP provides a full **Model Context Protocol (MCP)** server for Claude Desktop and Claude Code.

### Claude Code CLI:
```bash
claude mcp add job-mcp -- D:\Job-MCP\.venv\Scripts\python.exe D:\Job-MCP\server.py
```

### Claude Desktop
Add to your `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac):

```json
{
  "mcpServers": {
    "job-mcp": {
      "command": "D:\\Job-MCP\\.venv\\Scripts\\python.exe",
      "args": ["D:\\Job-MCP\\server.py"]
    }
  }
}
```

### Available MCP Tools:
- `list_platforms`: Check active and planned platforms and login status.
- `login_platform`: Launch interactive login in a visible browser.
- `search_jobs`: Search and rank jobs with match score, profile comparison, and `exclude_companies` filter.
- `apply_to_jobs`: Automated application with safe dry-run mode (skips excluded companies).
- `application_status`: View application history and tracker stats.
- `review_resume`: Extract resume details and run ATS review.
- `interview_prep`: Generate interview questions and prep roadmap.

---

## 🚫 Company Exclusion (Blacklist)

Want to skip specific companies (e.g. WITCH companies or current employers)?
Job MCP lets you exclude companies seamlessly across the platform:

1. **In the Web UI (Search Page)**:
   - Type any company name (e.g., `TCS`, `Infosys`, `Wipro`) in the **Exclude** filter and hit **Enter**.
   - Matching jobs are immediately filtered out in real time and excluded from all automated applications.
   - Click `✕` on any chip to remove the exclusion anytime.
2. **In Profile Settings (`/profile`)**:
   - Add permanent excluded companies under **Excluded companies** and click **Save profile**.
   - They are saved to `config.json` under `"excluded_companies": [...]` and automatically apply to future searches.
3. **In MCP & REST API**:
   - Pass `"exclude_companies": ["TCS", "Infosys"]` in `/api/search` or to the `search_jobs` MCP tool.
   - Jobs from excluded companies are automatically marked as `excluded_company` and skipped during bulk apply.

---

## 🌐 Platform Support Matrix

| Platform | Status | Features |
| :--- | :--- | :--- |
| **Naukri** | ✅ **Active / Live** | Search, Profile matching, One-click Apply |
| **Instahyre** | ✅ **Active / Live** | Search API, Profile matching, One-click Apply |
| **Hirist** | ✅ **Active / Live** | Tech search, Preloaded state parsing, Direct Apply |
| **Indeed** | ⏳ *Planned (Upcoming)* | External and Indeed Apply flow integration |
| **LinkedIn** | ⏳ *Planned (Upcoming)* | Easy Apply and search integration |
| **Wellfound** | ⏳ *Planned (Upcoming)* | Startup roles with salary & equity filtering |

---

## 📁 Project Structure

```
Job-MCP/
├── setup.bat          # 1-click Windows setup launcher (checks Python, npm, installs all)
├── setup.ps1          # PowerShell automated setup script
├── setup.sh           # Bash automated setup script (Linux / Mac)
├── start.bat          # Launch Web UI on Windows (http://127.0.0.1:8765)
├── start.sh           # Launch Web UI on Linux / Mac
├── app.py             # FastAPI + Uvicorn server launcher
├── run.py             # Interactive CLI application
├── server.py          # Model Context Protocol (MCP) server
├── requirements.txt   # Python dependencies
├── .env.example       # Template for Anthropic & OpenAI API keys
├── config.example.json# Template for user profile & autofill preferences
├── api/               # REST API endpoints & background task runners
├── web/               # Modern React + Vite + Tailwind frontend
├── tools/             # Core business logic:
│   ├── platforms/     # Adapters: naukri.py, instahyre.py, hirist.py, indeed.py
│   ├── ai/            # Resume review, ATS scorer, mock interview logic
│   ├── browser.py     # Playwright session management & human pauses
│   ├── tracker.py     # SQLite tracker for jobs and applications
│   └── search.py      # Multi-platform aggregated search & ranking
└── tests/             # Comprehensive unit & integration tests
```

---

## 🔒 Security & Privacy Notice
- **Passwords are NEVER stored**: You log in manually in a real browser window. Job MCP only stores session cookies in the local `.sessions/` directory.
- **Dry-run by default**: Bulk apply always starts in dry-run mode so you can verify each application before committing.
- **Local only**: The server binds to `127.0.0.1` only. Your resume, profile, and application history stay on your local disk.
