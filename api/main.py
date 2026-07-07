"""
api/main.py
FastAPI server — used by the desktop app (Tauri / webview calls these endpoints).
Endpoints: /run, /run/stream, /tools, /sessions, /projects, /config, /health
"""

import json, time, asyncio, threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

import sys, os

# When frozen by PyInstaller, __file__ points inside the temp extraction dir
# (_MEIPASS). The real resource root is sys._MEIPASS for onefile builds,
# or os.path.dirname(sys.executable) for onedir builds.
def _resource_root() -> str:
    """Return the base directory for bundled resources."""
    if getattr(sys, "frozen", False):
        # PyInstaller onefile: resources are unpacked to _MEIPASS
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
        # Fallback: onedir build — resources sit next to the binary
        return os.path.dirname(sys.executable)
    # Normal (un-frozen) execution: project root is two levels up from api/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_ROOT = _resource_root()
sys.path.insert(0, _ROOT)

from core.agent import run_agent
from core.providers import get_client, PROVIDERS, PROVIDER_MODELS, TOOL_CAPABLE_PROVIDERS
from core.database import DB
from core.tools.index import TOOL_DEFS, execute_tool

app = FastAPI(title="Codeably API", version="2.0.0")

app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db = DB()

# Serve desktop UI from desktop/ui/
# _ROOT is already the project root (or _MEIPASS when frozen), so the UI
# is bundled at desktop/ui/ relative to that root.
UI_DIR = Path(_ROOT) / "desktop" / "ui"
if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

# ── Models ────────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    task: str
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    session_id: Optional[int] = None
    project_id: Optional[int] = None

class ToolRequest(BaseModel):
    name: str
    input: dict

class SessionCreate(BaseModel):
    project_id: Optional[int] = None
    title: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None

class ProjectCreate(BaseModel):
    name: str
    path: str

class ConfigSet(BaseModel):
    key: str
    value: str

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "name": "Codeably",
        "version": "2.0.0",
        "tools": len(TOOL_DEFS),
        "tool_capable_providers": list(TOOL_CAPABLE_PROVIDERS),
    }

@app.get("/providers")
def list_providers():
    return {
        "providers": list(PROVIDERS.keys()),
        "models": PROVIDER_MODELS,
        "tool_capable": list(TOOL_CAPABLE_PROVIDERS),
    }

@app.get("/tools")
def list_tools():
    return {"tools": TOOL_DEFS, "count": len(TOOL_DEFS)}

# ── Streaming agent run ────────────────────────────────────────────────────────

@app.post("/run/stream")
async def run_stream(req: RunRequest):
    """Stream agent output as Server-Sent Events."""
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()  # capture loop before spawning thread

    def stream_cb(event: dict):
        # Safe cross-thread enqueue using the captured loop
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def generate():
        def agent_thread():
            try:
                client = get_client(req.provider, req.api_key, req.model)
                # Warn if provider doesn't support tools
                from core.providers import BaseClient
                if not getattr(client, "supports_tools", False):
                    loop.call_soon_threadsafe(queue.put_nowait, {
                        "type": "warning",
                        "message": (
                            f"{req.provider} does not fully support tool calling. "
                            "The agent will respond in text-only mode. "
                            "Use Anthropic, OpenAI, or Groq for autonomous tool use."
                        )
                    })
                result = run_agent(req.task, client, db=db, stream_cb=stream_cb)
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "done", "result": result})
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error": str(e)})

        t = threading.Thread(target=agent_thread, daemon=True)
        t.start()

        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in ("done", "error"):
                break

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── Non-streaming run ─────────────────────────────────────────────────────────

@app.post("/run")
def run(req: RunRequest):
    """Run agent and return complete response."""
    try:
        client = get_client(req.provider, req.api_key, req.model)
        events = []
        def cb(e): events.append(e)
        result = run_agent(req.task, client, db=db, stream_cb=cb)

        if req.session_id:
            db.save_message(req.session_id, "user", req.task)
            db.save_message(req.session_id, "assistant", result)

        return {"result": result, "events": events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Single tool execution ─────────────────────────────────────────────────────

@app.post("/tool")
def run_tool(req: ToolRequest):
    """Execute a single tool directly (for testing)."""
    result = execute_tool(req.name, req.input, db=db)
    return {"result": result}

# ── Sessions ──────────────────────────────────────────────────────────────────

@app.post("/sessions")
def create_session(req: SessionCreate):
    sid = db.create_session(req.project_id, req.title, req.provider, req.model)
    return {"session_id": sid}

@app.get("/sessions")
def get_sessions(project_id: Optional[int] = None):
    return {"sessions": db.get_sessions(project_id) or []}

@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: int):
    return {"messages": db.get_messages(session_id) or []}

# ── Projects ──────────────────────────────────────────────────────────────────

@app.post("/projects")
def create_project(req: ProjectCreate):
    pid = db.create_project(req.name, req.path)
    return {"project_id": pid}

@app.get("/projects")
def get_projects():
    return {"projects": db.get_projects() or []}

# ── Config ────────────────────────────────────────────────────────────────────

@app.post("/config")
def set_config(req: ConfigSet):
    db.set_config(req.key, req.value)
    return {"ok": True}

@app.get("/config/{key}")
def get_config(key: str):
    val = db.get_config(key)
    return {"key": key, "value": val}

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "db": bool(db.conn), "tools": len(TOOL_DEFS)}

# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    db.init_schema()
    print("Starting Codeably API on http://127.0.0.1:8765")
    print(f"UI available at http://127.0.0.1:8765/ui")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")

# ── Google OAuth 2.0 auth ─────────────────────────────────────────────────────
# Required env vars (set in .env):
#   GOOGLE_CLIENT_ID      — from console.cloud.google.com
#   GOOGLE_CLIENT_SECRET  — from console.cloud.google.com
#
# In Google Cloud Console:
#   Authorised redirect URI → http://127.0.0.1:8765/auth/google/callback
#   (The desktop app also registers codeably://auth as a deep-link, but the
#    callback hits this local server so we avoid the PKCE/loopback complexity.)
#
# Endpoints:
#   GET  /auth/google/url       → { url: "https://accounts.google.com/o/oauth2/v2/auth?..." }
#   GET  /auth/google/callback  → handles redirect from Google, stores session
#   GET  /auth/google/status    → { user: {...} | null }  — polled by UI
#   POST /auth/google/signout   → clears session

import secrets, hashlib
import httpx
from urllib.parse import urlencode

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL  = "https://www.googleapis.com/oauth2/v3/userinfo"
REDIRECT_URI     = "http://127.0.0.1:8765/auth/google/callback"
SCOPES           = "openid email profile"

# In-memory session (single-user desktop app — no multi-tenant concern)
_oauth_state:   str  = ""
_current_user:  dict = {}   # { email, name, picture, sub }


def _client_id()     -> str: return os.environ.get("GOOGLE_CLIENT_ID", "")
def _client_secret() -> str: return os.environ.get("GOOGLE_CLIENT_SECRET", "")


@app.get("/auth/google/url")
def google_auth_url():
    if not _client_id():
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not set in .env")

    global _oauth_state
    _oauth_state = secrets.token_urlsafe(32)

    params = {
        "client_id":     _client_id(),
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         SCOPES,
        "state":         _oauth_state,
        "access_type":   "online",
        "prompt":        "select_account",   # let user pick account like Codex does
    }
    return {"url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}


@app.get("/auth/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = ""):
    """Google redirects here after consent. Exchanges code → token → user info."""
    global _current_user

    if error:
        return _html_result("error", f"Google sign-in denied: {error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing code")

    if state != _oauth_state:
        raise HTTPException(status_code=400, detail="State mismatch — possible CSRF")

    # Exchange auth code for tokens
    async with httpx.AsyncClient(timeout=15) as client:
        tok_res = await client.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        })
        if tok_res.status_code != 200:
            raise HTTPException(status_code=502, detail="Token exchange failed")

        tokens = tok_res.json()
        access_token = tokens.get("access_token", "")
        if not access_token:
            raise HTTPException(status_code=502, detail="No access token in response")

        # Fetch user profile
        user_res = await client.get(
            GOOGLE_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_res.status_code != 200:
            raise HTTPException(status_code=502, detail="Could not fetch user info")

        user = user_res.json()
        _current_user = {
            "email":   user.get("email", ""),
            "name":    user.get("name", ""),
            "picture": user.get("picture", ""),
            "sub":     user.get("sub", ""),
        }

    return _html_result("success", _current_user["email"])


@app.get("/auth/google/status")
def google_status():
    """Polled by the UI every 1.5 s while waiting for the browser flow."""
    return {"user": _current_user if _current_user else None}


@app.post("/auth/google/signout")
def google_signout():
    global _current_user
    _current_user = {}
    return {"ok": True}


def _html_result(kind: str, detail: str) -> "HTMLResponse":
    """Minimal page shown in the browser after the OAuth redirect."""
    from fastapi.responses import HTMLResponse
    if kind == "success":
        body = (
            f"<h2 style='color:#4caf50'>✓ Signed in as {detail}</h2>"
            "<p>You can close this tab and return to Codeably.</p>"
            "<script>setTimeout(()=>window.close(),2000)</script>"
        )
    else:
        body = (
            f"<h2 style='color:#f44336'>Sign-in failed</h2>"
            f"<p>{detail}</p>"
            "<p>Close this tab and try again in Codeably.</p>"
        )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:sans-serif;display:flex;flex-direction:column;"
        "align-items:center;justify-content:center;height:100vh;margin:0;"
        "background:#0d0d0f;color:#e0e0e0}</style></head>"
        f"<body>{body}</body></html>"
    )
    return HTMLResponse(html)
