we are facing problem an update is taking place , very sorry please wait





# Codeably

An autonomous coding agent — 60 built-in tools, 8 AI providers, black-and-white UI.
Download the installer and open it. No Python, no terminal, no setup.

```
core/            Shared Python logic
├── tools/       All 60 tools
├── agent.py     Agent loop
├── providers.py Anthropic / OpenAI / Groq / Gemini / Mistral / Cohere / Ollama / OpenRouter
└── database.py  PostgreSQL (optional)

api/main.py      FastAPI server (frozen into a binary by PyInstaller)
cli/main.py      Terminal REPL
desktop/
├── ui/          HTML/CSS/JS frontend
└── electron/    Electron shell (main.js + preload.js)
```

## Download (recommended)

Go to **[Releases](../../releases)** and download the installer for your platform:

| Platform | File |
|----------|------|
| macOS (Intel + Apple Silicon) | `Codeably-2.0.0.dmg` |
| Windows | `Codeably-Setup-2.0.0.exe` |
| Linux | `Codeably-2.0.0.AppImage` or `.deb` |

Double-click to install. On first launch you'll be asked to verify your email
(one-time, code stored locally after that).

## Quick start (terminal / CLI)

```bash
git clone https://github.com/<you>/codeably.git
cd codeably
./install.sh          # macOS/Linux — venv + deps
# Windows: install.bat

python -m cli.main                               # interactive REPL
python -m cli.main "refactor my code"            # one-shot
python -m cli.main -p groq -m llama-3.3-70b-versatile "explain main.py"
```

## Quick start (browser UI, no build needed)

```bash
./run.sh    # or run.bat on Windows
# Opens http://127.0.0.1:8765/ui
```

## Build the desktop app yourself

### Prerequisites

- Python 3.11+
- Node 20+
- PyInstaller: `pip install pyinstaller`

### Steps

```bash
# 1. Freeze the Python API into a binary
pip install -r requirements.txt
pyinstaller pyinstaller.spec
# → dist/codeably-api  (or dist/codeably-api.exe)

# 2. Stage the binary
cp dist/codeably-api desktop/codeably-api    # mac/linux
# copy dist\codeably-api.exe desktop\        # windows

# 3. Build the Electron installer
cd desktop
npm install
npm run build        # all platforms
# or: npm run build:mac / build:win / build:linux
# → desktop/dist/*.dmg, *.exe, *.AppImage
```

### One-click release via GitHub Actions

Push a version tag and the CI builds + uploads installers automatically:

```bash
git tag v2.0.0
git push origin v2.0.0
```

Installers appear under **Releases** within ~10 minutes.

## Providers

| Provider   | Tool calling | Models |
|------------|:---:|---|
| anthropic  | ✅ | claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5 |
| openai     | ✅ | gpt-4o, gpt-4o-mini, o3, o4-mini |
| groq       | ✅ | llama-3.3-70b-versatile, mixtral-8x7b |
| gemini     | text-only | gemini-2.0-flash |
| mistral    | text-only | mistral-large-latest |
| cohere     | text-only | command-r-plus |
| ollama     | text-only | any local model |
| openrouter | text-only | any model |

## Configuration

API keys are entered in **Settings** inside the app (stored in localStorage).
Or set environment variables: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.

Optional Postgres: set `DATABASE_URL` to persist sessions and tool logs.
