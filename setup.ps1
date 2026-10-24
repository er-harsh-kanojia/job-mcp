# ==============================================================================
# Job MCP - Full Automated Setup Script (PowerShell)
# ==============================================================================
# This script sets up the entire Job MCP project from scratch.
# It can be executed directly by any AI Assistant (Claude, Cursor, etc.)
# or by a human user in PowerShell:
#     powershell -ExecutionPolicy Bypass -File setup.ps1
# ==============================================================================

[CmdletBinding()]
param (
    [switch]$SkipBrowserInstall,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

function Write-Step {
    param([string]$Text)
    Write-Host "`n====> $Text" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Text)
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "[!] $Text" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Text)
    Write-Host "[X] $Text" -ForegroundColor Red
}

Write-Host "============================================================" -ForegroundColor Magenta
Write-Host "               Job MCP Automated Setup                      " -ForegroundColor Magenta
Write-Host "============================================================" -ForegroundColor Magenta

# ------------------------------------------------------------------------------
# 1. Check & Install Python
# ------------------------------------------------------------------------------
Write-Step "Checking Python installation..."

$PythonCmd = $null
if (Test-Path "$ScriptDir\.venv\Scripts\python.exe") {
    $PythonCmd = "$ScriptDir\.venv\Scripts\python.exe"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCmd = "py -3"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCmd = "python"
}

if (-not $PythonCmd) {
    Write-Warn "Python 3 was not detected on your PATH."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Python 3.12 via winget..." -ForegroundColor Yellow
        try {
            winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            if (Get-Command py -ErrorAction SilentlyContinue) { $PythonCmd = "py -3" }
            elseif (Get-Command python -ErrorAction SilentlyContinue) { $PythonCmd = "python" }
        } catch {
            Write-Warn "Automatic installation via winget encountered an issue."
        }
    }
}

if (-not $PythonCmd) {
    Write-Fail "Python 3 could not be found or installed automatically."
    Write-Host "Please install Python 3.10+ from https://www.python.org/downloads/ (check 'Add Python to PATH') and re-run this script."
    exit 1
}

$PyVersion = Invoke-Expression "$PythonCmd --version" 2>&1
Write-Success "Found: $PyVersion"

# ------------------------------------------------------------------------------
# 2. Check & Install Node.js / npm
# ------------------------------------------------------------------------------
Write-Step "Checking Node.js & npm installation..."

$NpmInstalled = Get-Command npm -ErrorAction SilentlyContinue
if (-not $NpmInstalled) {
    Write-Warn "Node.js / npm was not detected on your PATH."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Node.js LTS via winget..." -ForegroundColor Yellow
        try {
            winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            $NpmInstalled = Get-Command npm -ErrorAction SilentlyContinue
        } catch {
            Write-Warn "Automatic Node.js installation via winget encountered an issue."
        }
    }
}

if ($NpmInstalled) {
    $NodeVer = node -v 2>&1
    $NpmVer = npm -v 2>&1
    Write-Success "Found Node $NodeVer, npm v$NpmVer"
} else {
    Write-Warn "Node.js / npm is not installed. If pre-built frontend exists, the app can still run."
    Write-Host "To develop or build the frontend, install Node.js from https://nodejs.org/" -ForegroundColor Gray
}

# ------------------------------------------------------------------------------
# 3. Create Python Virtual Environment (.venv)
# ------------------------------------------------------------------------------
Write-Step "Setting up Python virtual environment (.venv)..."

$VenvPython = "$ScriptDir\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment in .venv..." -ForegroundColor Gray
    Invoke-Expression "$PythonCmd -m venv `"$ScriptDir\.venv`""
    if (-not (Test-Path $VenvPython)) {
        Write-Fail "Failed to create virtual environment."
        exit 1
    }
    Write-Success "Created .venv successfully."
} else {
    Write-Success "Existing .venv found."
}

# ------------------------------------------------------------------------------
# 4. Install Python Dependencies
# ------------------------------------------------------------------------------
Write-Step "Installing Python packages from requirements.txt..."

& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r "$ScriptDir\requirements.txt" --quiet
Write-Success "Python packages installed."

# ------------------------------------------------------------------------------
# 5. Install Playwright Chromium Browser
# ------------------------------------------------------------------------------
if (-not $SkipBrowserInstall) {
    Write-Step "Installing Playwright Chromium browser..."
    & $VenvPython -m playwright install chromium
    Write-Success "Playwright Chromium browser ready."
}

# ------------------------------------------------------------------------------
# 6. Install Frontend Dependencies & Build
# ------------------------------------------------------------------------------
if ($NpmInstalled -and -not $SkipBuild) {
    Write-Step "Installing frontend dependencies & building production bundle..."
    Push-Location "$ScriptDir\web"
    try {
        if (-not (Test-Path "node_modules")) {
            Write-Host "Running npm install in web/..." -ForegroundColor Gray
            npm install --quiet
        }
        Write-Host "Building frontend (npm run build)..." -ForegroundColor Gray
        npm run build
        Write-Success "Frontend built successfully (web/dist ready)."
    } finally {
        Pop-Location
    }
} elseif (Test-Path "$ScriptDir\web\dist\index.html") {
    Write-Success "Existing web/dist build verified."
} else {
    Write-Warn "web/dist/index.html was not found and npm was not available to build it."
    Write-Host "Install Node.js from https://nodejs.org/ and run: cd web && npm install && npm run build"
}

# ------------------------------------------------------------------------------
# 7. Environment & Config Setup (.env and config.json)
# ------------------------------------------------------------------------------
Write-Step "Configuring environment files..."

# .env file setup
if (-not (Test-Path "$ScriptDir\.env")) {
    if (Test-Path "$ScriptDir\.env.example") {
        Copy-Item "$ScriptDir\.env.example" "$ScriptDir\.env"
        Write-Success "Created .env from .env.example"
    } else {
        New-Item -Path "$ScriptDir\.env" -ItemType File -Force | Out-Null
        Write-Success "Created blank .env file"
    }
    Write-Host "--> IMPORTANT: Open .env and add your ANTHROPIC_API_KEY or OPENAI_API_KEY" -ForegroundColor Yellow
    Write-Host "    to enable the AI Resume Review, ATS Scorer, and Mock Interview features!" -ForegroundColor Yellow
} else {
    Write-Success ".env file already exists."
}

# config.json file setup
if (-not (Test-Path "$ScriptDir\config.json")) {
    if (Test-Path "$ScriptDir\config.example.json") {
        Copy-Item "$ScriptDir\config.example.json" "$ScriptDir\config.json"
        Write-Success "Created config.json from config.example.json"
    }
    Write-Host "--> You can edit config.json with your experience, resume path, and autofill preferences." -ForegroundColor Gray
} else {
    Write-Success "config.json already exists."
}

# ------------------------------------------------------------------------------
# Summary & Next Steps
# ------------------------------------------------------------------------------
Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "              Job MCP Setup Complete!                      " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start the application:" -ForegroundColor White
Write-Host "  1. Double-click or run:  .\start.bat" -ForegroundColor Cyan
Write-Host "     (or: .\.venv\Scripts\python.exe app.py)" -ForegroundColor Gray
Write-Host "  2. Web UI URL:          http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host ""
Write-Host "To use AI Resume & Mock Interview features:" -ForegroundColor White
Write-Host "  * Open .env and paste your ANTHROPIC_API_KEY or OPENAI_API_KEY." -ForegroundColor Yellow
Write-Host ""
Write-Host "Platforms Supported:" -ForegroundColor White
Write-Host "  * Active / Live:  Naukri, Instahyre, Hirist" -ForegroundColor Green
Write-Host "  * Planned:        LinkedIn, Wellfound, Indeed" -ForegroundColor Gray
Write-Host "============================================================`n" -ForegroundColor Green
