"""
cli/main.py
Terminal interface for Codeably — works like Codex CLI.
Usage:
  python -m cli.main                        # interactive REPL
  python -m cli.main "refactor my code"     # one-shot task
  python -m cli.main --provider groq --model llama-3.3-70b-versatile "explain main.py"
"""

import sys, os, argparse, json, threading
from pathlib import Path

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.agent import run_agent
from core.providers import get_client, PROVIDERS, PROVIDER_MODELS, TOOL_CAPABLE_PROVIDERS
from core.database import DB

# ── ANSI colours (disabled on Windows without colorama) ──────────────────────

def _supports_color():
    return sys.stdout.isatty() and os.name != "nt"

RESET  = "\033[0m"  if _supports_color() else ""
BOLD   = "\033[1m"  if _supports_color() else ""
DIM    = "\033[2m"  if _supports_color() else ""
GREEN  = "\033[32m" if _supports_color() else ""
YELLOW = "\033[33m" if _supports_color() else ""
BLUE   = "\033[34m" if _supports_color() else ""
CYAN   = "\033[36m" if _supports_color() else ""
RED    = "\033[31m" if _supports_color() else ""
WHITE  = "\033[37m" if _supports_color() else ""

BANNER = f"""{BOLD}
  ╔═══════════════════════════════════╗
  ║   Codeably — autonomous coding    ║
  ╚═══════════════════════════════════╝{RESET}
{DIM}  type a task and press Enter · /help for commands{RESET}
"""

HELP = f"""
{BOLD}Commands:{RESET}
  /help              show this help
  /provider <name>   switch provider (anthropic, openai, groq, gemini, ...)
  /model <name>      switch model
  /key <value>       set API key for current provider
  /dir <path>        set working directory for the agent
  /tools             list all available tools
  /clear             clear the screen
  /exit              quit

{BOLD}Providers with full tool support:{RESET} {', '.join(TOOL_CAPABLE_PROVIDERS)}
{BOLD}Text-only providers:{RESET} gemini, mistral, cohere, ollama, openrouter
"""

# ── Config persistence ────────────────────────────────────────────────────────

CONFIG_FILE = Path.home() / ".codeably" / "config.json"

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except: pass
    return {"provider": "anthropic", "model": "claude-sonnet-4-6", "keys": {}}

def save_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

# ── Streaming callback ────────────────────────────────────────────────────────

def make_stream_cb():
    """Returns a callback that prints agent events to the terminal."""
    def cb(event):
        t = event.get("type")
        if t == "text":
            print(f"{WHITE}{event['text']}{RESET}", end="", flush=True)
        elif t == "tool_start":
            tool = event["tool"]
            inp  = event.get("input", {})
            # Show a compact summary of the tool call
            hint = ""
            if "path" in inp:   hint = f" {DIM}{inp['path']}{RESET}"
            elif "command" in inp: hint = f" {DIM}{inp['command'][:60]}{RESET}"
            elif "pattern" in inp: hint = f" {DIM}{inp['pattern']}{RESET}"
            print(f"\n{CYAN}▶ {tool}{RESET}{hint} ", end="", flush=True)
        elif t == "tool_end":
            result = str(event.get("result", ""))
            # Show first line of result or ✓
            first = result.strip().splitlines()[0][:80] if result.strip() else "done"
            print(f"{DIM}→ {first}{RESET}", flush=True)
        elif t == "warning":
            print(f"\n{YELLOW}⚠  {event['message']}{RESET}\n")
        elif t == "done":
            print()  # final newline
        elif t == "error":
            print(f"\n{RED}✗ {event['error']}{RESET}")
    return cb

# ── Main REPL ────────────────────────────────────────────────────────────────

def run_repl(args):
    cfg = load_config()

    # CLI flags override saved config
    if args.provider: cfg["provider"] = args.provider
    if args.model:    cfg["model"]    = args.model
    if args.key:      cfg["keys"][cfg["provider"]] = args.key

    db = DB()

    print(BANNER)

    def get_client_safe():
        provider = cfg["provider"]
        model    = cfg["model"]
        api_key  = cfg["keys"].get(provider) or os.environ.get(
            f"{provider.upper()}_API_KEY", "")
        if not api_key and provider != "ollama":
            print(f"{YELLOW}No API key set for {provider}. "
                  f"Use /key <your-key> or set {provider.upper()}_API_KEY env var.{RESET}")
            return None
        try:
            return get_client(provider, api_key, model)
        except Exception as e:
            print(f"{RED}Error creating client: {e}{RESET}")
            return None

    def print_prompt():
        provider = cfg["provider"]
        model    = cfg["model"]
        cwd_short = Path(os.getcwd()).name
        star = "" if provider in TOOL_CAPABLE_PROVIDERS else f"{YELLOW}*{RESET}"
        sys.stdout.write(
            f"\n{DIM}[{cwd_short}]{RESET} {BOLD}{provider}{star}{RESET}{DIM}/{model}{RESET} "
            f"{BOLD}>{RESET} "
        )
        sys.stdout.flush()

    # ── One-shot mode ─────────────────────────────────────────────────────────
    if args.task:
        client = get_client_safe()
        if not client: sys.exit(1)
        cb = make_stream_cb()
        print(f"{DIM}Running: {args.task}{RESET}\n")
        try:
            run_agent(args.task, client, db=db, stream_cb=cb)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Interrupted.{RESET}")
        return

    # ── Interactive REPL ──────────────────────────────────────────────────────
    try:
        import readline  # enables arrow keys / history on Unix
        HIST = Path.home() / ".codeably" / "history"
        HIST.parent.mkdir(parents=True, exist_ok=True)
        if HIST.exists(): readline.read_history_file(str(HIST))
    except ImportError:
        readline = None
        HIST = None

    while True:
        try:
            print_prompt()
            line = input().strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}bye{RESET}")
            break

        if not line:
            continue

        # ── Built-in commands ─────────────────────────────────────────────────
        if line.startswith("/"):
            parts = line.split(None, 1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "/help":
                print(HELP)
            elif cmd == "/exit":
                print(f"{DIM}bye{RESET}")
                break
            elif cmd == "/clear":
                os.system("cls" if os.name == "nt" else "clear")
                print(BANNER)
            elif cmd == "/provider":
                if arg in PROVIDERS:
                    cfg["provider"] = arg
                    # reset to default model for that provider
                    cfg["model"] = PROVIDER_MODELS[arg][0]
                    save_config(cfg)
                    print(f"{GREEN}Provider → {arg}  model → {cfg['model']}{RESET}")
                    if arg not in TOOL_CAPABLE_PROVIDERS:
                        print(f"{YELLOW}Note: {arg} is text-only (no autonomous tool calling).{RESET}")
                else:
                    print(f"{RED}Unknown provider. Choose: {', '.join(PROVIDERS)}{RESET}")
            elif cmd == "/model":
                if arg:
                    cfg["model"] = arg
                    save_config(cfg)
                    print(f"{GREEN}Model → {arg}{RESET}")
                else:
                    models = PROVIDER_MODELS.get(cfg["provider"], [])
                    print(f"Available for {cfg['provider']}: {', '.join(models)}")
            elif cmd == "/key":
                if arg:
                    cfg["keys"][cfg["provider"]] = arg
                    save_config(cfg)
                    print(f"{GREEN}API key saved for {cfg['provider']}.{RESET}")
                else:
                    print(f"{RED}Usage: /key <your-api-key>{RESET}")
            elif cmd == "/dir":
                if arg:
                    p = Path(arg).expanduser().resolve()
                    if p.exists():
                        os.chdir(p)
                        print(f"{GREEN}Working dir → {p}{RESET}")
                    else:
                        print(f"{RED}Path does not exist: {p}{RESET}")
                else:
                    print(f"Current dir: {os.getcwd()}")
            elif cmd == "/tools":
                from core.tools.index import TOOL_DEFS
                print(f"\n{BOLD}Available tools ({len(TOOL_DEFS)}):{RESET}")
                for t in TOOL_DEFS:
                    print(f"  {CYAN}{t['name']:<25}{RESET}{DIM}{t['description'][:60]}{RESET}")
                print()
            else:
                print(f"{RED}Unknown command: {cmd}. Type /help.{RESET}")
            continue

        # ── Run agent task ─────────────────────────────────────────────────
        client = get_client_safe()
        if not client:
            continue

        cb = make_stream_cb()
        print()
        try:
            run_agent(line, client, db=db, stream_cb=cb)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Interrupted.{RESET}")
        except Exception as e:
            print(f"\n{RED}Error: {e}{RESET}")

    # save history
    if readline and HIST:
        try: readline.write_history_file(str(HIST))
        except: pass

    save_config(cfg)

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="codeably",
        description="Codeably — autonomous coding agent",
    )
    parser.add_argument("task", nargs="?", default=None,
                        help="Task to run (omit for interactive REPL)")
    parser.add_argument("--provider", "-p", default=None,
                        choices=list(PROVIDERS.keys()),
                        help="AI provider to use")
    parser.add_argument("--model", "-m", default=None,
                        help="Model name")
    parser.add_argument("--key", "-k", default=None,
                        help="API key for the provider")
    parser.add_argument("--list-tools", action="store_true",
                        help="List all tools and exit")
    parser.add_argument("--list-providers", action="store_true",
                        help="List all providers and exit")
    args = parser.parse_args()

    if args.list_tools:
        from core.tools.index import TOOL_DEFS
        for t in TOOL_DEFS:
            print(f"{t['name']:<25} {t['description']}")
        return

    if args.list_providers:
        for p, models in PROVIDER_MODELS.items():
            tool_tag = "(tools)" if p in TOOL_CAPABLE_PROVIDERS else "(text)"
            print(f"{p:<15} {tool_tag:<10} {', '.join(models)}")
        return

    run_repl(args)

if __name__ == "__main__":
    main()
