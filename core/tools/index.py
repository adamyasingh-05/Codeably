"""
core/tools/index.py
All 60 tools for Codeably agent.
TOOL_DEFS  = schemas sent to the LLM
execute_tool = runs the actual operation
"""

import os, shutil, subprocess, hashlib, platform, socket, stat
import json, re, sys, signal, mimetypes
from pathlib import Path
from datetime import datetime

# ── helpers ──────────────────────────────────────────────────────────────────

SKIP = {".git","node_modules","__pycache__",".venv","venv","dist","build",
        ".next","out",".turbo","coverage",".nyc_output"}

def _read(path):
    return Path(path).read_text(errors="replace")

def _write(path, content):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)

def _run(cmd, cwd=None, timeout=30):
    r = subprocess.run(cmd, shell=True, capture_output=True,
                       text=True, cwd=cwd, timeout=timeout)
    out = r.stdout.strip()
    err = r.stderr.strip()
    return (out + ("\n" + err if err else "")).strip()

# ── Tool schemas ──────────────────────────────────────────────────────────────

TOOL_DEFS = [

  # ── File I/O ────────────────────────────────────────────────────────────────
  {"name":"read_file","description":"Read a file and return its full text. Optionally specify line range.",
   "input_schema":{"type":"object","properties":{
     "path":{"type":"string"},"start_line":{"type":"number"},"end_line":{"type":"number"}},"required":["path"]}},

  {"name":"write_file","description":"Write or overwrite a file. Creates parent dirs automatically.",
   "input_schema":{"type":"object","properties":{
     "path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}},

  {"name":"patch_file","description":"Replace an exact unique string in a file.",
   "input_schema":{"type":"object","properties":{
     "path":{"type":"string"},"old_str":{"type":"string"},"new_str":{"type":"string"}},"required":["path","old_str","new_str"]}},

  {"name":"append_file","description":"Append content to end of a file.",
   "input_schema":{"type":"object","properties":{
     "path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}},

  {"name":"insert_lines","description":"Insert lines after a specific line number (0 = top of file).",
   "input_schema":{"type":"object","properties":{
     "path":{"type":"string"},"after_line":{"type":"number"},"content":{"type":"string"}},"required":["path","after_line","content"]}},

  {"name":"delete_lines","description":"Delete a range of lines from a file.",
   "input_schema":{"type":"object","properties":{
     "path":{"type":"string"},"start_line":{"type":"number"},"end_line":{"type":"number"}},"required":["path","start_line","end_line"]}},

  {"name":"copy_file","description":"Copy a file or directory to a new location.",
   "input_schema":{"type":"object","properties":{
     "src":{"type":"string"},"dest":{"type":"string"}},"required":["src","dest"]}},

  {"name":"move_file","description":"Move or rename a file or directory.",
   "input_schema":{"type":"object","properties":{
     "src":{"type":"string"},"dest":{"type":"string"}},"required":["src","dest"]}},

  {"name":"delete_file","description":"Delete a single file. Requires confirm_delete to be called first.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},

  {"name":"delete_files_bulk","description":"Delete multiple files by glob pattern. Must call confirm_delete first.",
   "input_schema":{"type":"object","properties":{
     "pattern":{"type":"string"},"base_dir":{"type":"string"}},"required":["pattern"]}},

  {"name":"make_dir","description":"Create a directory (and parents).",
   "input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},

  # ── Navigation ──────────────────────────────────────────────────────────────
  {"name":"list_files","description":"Recursively list all files in a directory.",
   "input_schema":{"type":"object","properties":{
     "path":{"type":"string","default":"."},"depth":{"type":"number","default":3}},"required":[]}},

  {"name":"list_dir","description":"List immediate contents of a directory with sizes.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string","default":"."}},"required":[]}},

  # ── Search ──────────────────────────────────────────────────────────────────
  {"name":"search_code","description":"Search for a pattern across all files in a directory.",
   "input_schema":{"type":"object","properties":{
     "pattern":{"type":"string"},"path":{"type":"string","default":"."},
     "file_glob":{"type":"string"}},"required":["pattern"]}},

  {"name":"find_files","description":"Find files by name pattern.",
   "input_schema":{"type":"object","properties":{
     "pattern":{"type":"string"},"path":{"type":"string","default":"."}},"required":["pattern"]}},

  {"name":"grep_replace","description":"Replace a regex pattern across multiple files.",
   "input_schema":{"type":"object","properties":{
     "pattern":{"type":"string"},"replacement":{"type":"string"},
     "path":{"type":"string","default":"."},"file_glob":{"type":"string"}},"required":["pattern","replacement"]}},

  {"name":"find_duplicates","description":"Find duplicate files in a directory by content hash.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string","default":"."}},"required":[]}},

  # ── Execution ───────────────────────────────────────────────────────────────
  {"name":"run_command","description":"Run a shell command and return output.",
   "input_schema":{"type":"object","properties":{
     "command":{"type":"string"},"cwd":{"type":"string"},"timeout":{"type":"number"}},"required":["command"]}},

  {"name":"run_script","description":"Write and run a temporary script (bash/python/node).",
   "input_schema":{"type":"object","properties":{
     "language":{"type":"string","enum":["bash","python","node"]},"code":{"type":"string"},
     "cwd":{"type":"string"}},"required":["language","code"]}},

  {"name":"check_port","description":"Check if a TCP port is open on a host.",
   "input_schema":{"type":"object","properties":{
     "host":{"type":"string","default":"localhost"},"port":{"type":"number"}},"required":["port"]}},

  {"name":"run_tests","description":"Run test suite (auto-detects pytest/jest/mocha).",
   "input_schema":{"type":"object","properties":{"cwd":{"type":"string","default":"."}},"required":[]}},

  {"name":"lint_code","description":"Lint a file or directory (auto-detects eslint/pylint/ruff).",
   "input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},

  {"name":"format_code","description":"Format code with prettier/black/gofmt.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},

  # ── Analysis ────────────────────────────────────────────────────────────────
  {"name":"diff_files","description":"Show unified diff between two files.",
   "input_schema":{"type":"object","properties":{
     "file_a":{"type":"string"},"file_b":{"type":"string"}},"required":["file_a","file_b"]}},

  {"name":"file_stats","description":"Return size, line count, hash, and mime type of a file.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},

  {"name":"count_lines","description":"Count lines of code by language in a directory.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string","default":"."}},"required":[]}},

  {"name":"detect_language","description":"Detect the programming language of a file.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},

  {"name":"read_env","description":"Read environment variables from a .env file.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string","default":".env"}},"required":[]}},

  {"name":"code_coverage","description":"Run tests with coverage and return report.",
   "input_schema":{"type":"object","properties":{"cwd":{"type":"string","default":"."}},"required":[]}},

  {"name":"system_info","description":"Return OS, CPU, RAM, disk, Python, Node versions.",
   "input_schema":{"type":"object","properties":{},"required":[]}},

  # ── Git ─────────────────────────────────────────────────────────────────────
  {"name":"git_status","description":"Show git status of working directory.",
   "input_schema":{"type":"object","properties":{"cwd":{"type":"string","default":"."}},"required":[]}},

  {"name":"git_diff","description":"Show git diff (staged or unstaged).",
   "input_schema":{"type":"object","properties":{
     "cwd":{"type":"string","default":"."},"staged":{"type":"boolean","default":False}},"required":[]}},

  {"name":"git_log","description":"Show recent git commits.",
   "input_schema":{"type":"object","properties":{
     "cwd":{"type":"string","default":"."},"n":{"type":"number","default":10}},"required":[]}},

  {"name":"git_commit","description":"Stage all changes and commit with a message.",
   "input_schema":{"type":"object","properties":{
     "message":{"type":"string"},"cwd":{"type":"string","default":"."}},"required":["message"]}},

  {"name":"git_push","description":"Push current branch to remote origin.",
   "input_schema":{"type":"object","properties":{"cwd":{"type":"string","default":"."}},"required":[]}},

  {"name":"git_branch","description":"List, create, or switch git branches.",
   "input_schema":{"type":"object","properties":{
     "action":{"type":"string","enum":["list","create","switch"]},
     "name":{"type":"string"},"cwd":{"type":"string","default":"."}},"required":["action"]}},

  # ── Packages ────────────────────────────────────────────────────────────────
  {"name":"npm_info","description":"Get npm package info and latest version.",
   "input_schema":{"type":"object","properties":{"package":{"type":"string"}},"required":["package"]}},

  {"name":"pip_install","description":"Install Python packages via pip.",
   "input_schema":{"type":"object","properties":{
     "packages":{"type":"string"},"cwd":{"type":"string"}},"required":["packages"]}},

  {"name":"npm_install","description":"Install npm packages.",
   "input_schema":{"type":"object","properties":{
     "packages":{"type":"string"},"cwd":{"type":"string"},"dev":{"type":"boolean"}},"required":["packages"]}},

  {"name":"list_dependencies","description":"List all dependencies from package.json or requirements.txt.",
   "input_schema":{"type":"object","properties":{"cwd":{"type":"string","default":"."}},"required":[]}},

  {"name":"audit_packages","description":"Run security audit on npm or pip packages.",
   "input_schema":{"type":"object","properties":{"cwd":{"type":"string","default":"."}},"required":[]}},

  # ── Network ─────────────────────────────────────────────────────────────────
  {"name":"url_fetch","description":"Fetch a URL and return the response body.",
   "input_schema":{"type":"object","properties":{
     "url":{"type":"string"},"method":{"type":"string","default":"GET"},
     "headers":{"type":"object"},"body":{"type":"string"}},"required":["url"]}},

  {"name":"api_test","description":"Test a REST API endpoint and return status + body.",
   "input_schema":{"type":"object","properties":{
     "url":{"type":"string"},"method":{"type":"string","default":"GET"},
     "headers":{"type":"object"},"body":{"type":"object"}},"required":["url"]}},

  {"name":"ping_host","description":"Ping a host and return latency.",
   "input_schema":{"type":"object","properties":{"host":{"type":"string"}},"required":["host"]}},

  {"name":"download_file","description":"Download a file from URL to local path.",
   "input_schema":{"type":"object","properties":{
     "url":{"type":"string"},"dest":{"type":"string"}},"required":["url","dest"]}},

  {"name":"check_ssl","description":"Check SSL certificate info for a domain.",
   "input_schema":{"type":"object","properties":{"host":{"type":"string"}},"required":["host"]}},

  # ── System ──────────────────────────────────────────────────────────────────
  {"name":"process_list","description":"List running processes (filter by name).",
   "input_schema":{"type":"object","properties":{"filter":{"type":"string"}},"required":[]}},

  {"name":"kill_process","description":"Kill a process by PID or name.",
   "input_schema":{"type":"object","properties":{
     "pid":{"type":"number"},"name":{"type":"string"}},"required":[]}},

  {"name":"cron_add","description":"Add a cron job (unix only).",
   "input_schema":{"type":"object","properties":{
     "schedule":{"type":"string"},"command":{"type":"string"}},"required":["schedule","command"]}},

  {"name":"env_set","description":"Set environment variables in a .env file.",
   "input_schema":{"type":"object","properties":{
     "key":{"type":"string"},"value":{"type":"string"},
     "path":{"type":"string","default":".env"}},"required":["key","value"]}},

  {"name":"disk_usage","description":"Show disk usage of a directory.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string","default":"."}},"required":[]}},

  # ── Database ────────────────────────────────────────────────────────────────
  {"name":"db_query","description":"Run a SQL query on the configured PostgreSQL database.",
   "input_schema":{"type":"object","properties":{"sql":{"type":"string"}},"required":["sql"]}},

  {"name":"db_schema","description":"Show tables and columns in the database.",
   "input_schema":{"type":"object","properties":{"table":{"type":"string"}},"required":[]}},

  {"name":"db_migrate","description":"Run pending database migrations.",
   "input_schema":{"type":"object","properties":{"cwd":{"type":"string","default":"."}},"required":[]}},

  {"name":"db_backup","description":"Dump the PostgreSQL database to a file.",
   "input_schema":{"type":"object","properties":{"dest":{"type":"string"}},"required":["dest"]}},

  # ── AI Powered ──────────────────────────────────────────────────────────────
  {"name":"explain_code","description":"Ask the AI to explain a file or code snippet.",
   "input_schema":{"type":"object","properties":{
     "path":{"type":"string"},"snippet":{"type":"string"}},"required":[]}},

  {"name":"review_code","description":"Ask the AI to review code for bugs and improvements.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},

  {"name":"generate_tests","description":"Ask the AI to generate tests for a file.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},

  {"name":"fix_bug","description":"Ask the AI to fix a bug given an error message.",
   "input_schema":{"type":"object","properties":{
     "error":{"type":"string"},"path":{"type":"string"}},"required":["error"]}},

  {"name":"explain_error","description":"Ask the AI to explain an error message.",
   "input_schema":{"type":"object","properties":{"error":{"type":"string"}},"required":["error"]}},

  # ── Control ─────────────────────────────────────────────────────────────────
  {"name":"confirm_delete","description":"Approve pending destructive delete operation. Must be called before delete_file or delete_files_bulk.",
   "input_schema":{"type":"object","properties":{"reason":{"type":"string"}},"required":["reason"]}},

  {"name":"done","description":"Signal that the task is complete.",
   "input_schema":{"type":"object","properties":{"summary":{"type":"string"}},"required":["summary"]}},

  {"name":"set_working_dir","description":"Set the current working directory for the session.",
   "input_schema":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}},

  {"name":"get_config","description":"Get current session config (provider, model, working dir).",
   "input_schema":{"type":"object","properties":{},"required":[]}},
]

# ── State ────────────────────────────────────────────────────────────────────

_state = {"cwd": os.getcwd(), "delete_approved": False}

def set_working_dir(path): _state["cwd"] = str(Path(path).resolve())
def get_cwd(): return _state["cwd"]

# ── Executor ─────────────────────────────────────────────────────────────────

def execute_tool(name: str, inp: dict, db=None, ai_client=None) -> str:
    cwd = inp.get("cwd") or _state["cwd"]

    try:
        # ── File I/O ────────────────────────────────────────────────────────
        if name == "read_file":
            lines = Path(inp["path"]).read_text(errors="replace").splitlines()
            s, e = inp.get("start_line"), inp.get("end_line")
            if s: lines = lines[(int(s)-1):(int(e) if e else None)]
            return "\n".join(lines)

        if name == "write_file":
            _write(inp["path"], inp["content"])
            return f"Written: {inp['path']}"

        if name == "patch_file":
            txt = _read(inp["path"])
            if inp["old_str"] not in txt:
                return "ERROR: old_str not found in file"
            if txt.count(inp["old_str"]) > 1:
                return "ERROR: old_str is not unique in file"
            _write(inp["path"], txt.replace(inp["old_str"], inp["new_str"], 1))
            return f"Patched: {inp['path']}"

        if name == "append_file":
            with open(inp["path"], "a") as f: f.write(inp["content"])
            return f"Appended to: {inp['path']}"

        if name == "insert_lines":
            lines = Path(inp["path"]).read_text(errors="replace").splitlines(True)
            after = int(inp["after_line"])
            lines.insert(after, inp["content"] if inp["content"].endswith("\n") else inp["content"]+"\n")
            Path(inp["path"]).write_text("".join(lines))
            return f"Inserted after line {after}"

        if name == "delete_lines":
            lines = Path(inp["path"]).read_text(errors="replace").splitlines(True)
            s, e = int(inp["start_line"])-1, int(inp["end_line"])
            del lines[s:e]
            Path(inp["path"]).write_text("".join(lines))
            return f"Deleted lines {inp['start_line']}-{inp['end_line']}"

        if name == "copy_file":
            src, dst = Path(inp["src"]), Path(inp["dest"])
            if src.is_dir(): shutil.copytree(src, dst)
            else: shutil.copy2(src, dst)
            return f"Copied {src} → {dst}"

        if name == "move_file":
            shutil.move(inp["src"], inp["dest"])
            return f"Moved {inp['src']} → {inp['dest']}"

        # ── Safety gate for destructive operations ───────────────────────────
        if name == "delete_file":
            if not _state["delete_approved"]:
                return (f"BLOCKED: delete_file requires confirm_delete to be called first. "
                        f"Call confirm_delete with a reason, then retry delete_file for: {inp['path']}")
            _state["delete_approved"] = False
            Path(inp["path"]).unlink()
            return f"Deleted: {inp['path']}"

        if name == "delete_files_bulk":
            import glob
            base = inp.get("base_dir", _state["cwd"])
            files = glob.glob(os.path.join(base, inp["pattern"]), recursive=True)
            if not _state["delete_approved"]:
                return (f"Found {len(files)} files. Call confirm_delete with a reason to proceed:\n"
                        + "\n".join(files[:20]))
            for f in files: os.remove(f)
            _state["delete_approved"] = False
            return f"Deleted {len(files)} files."

        if name == "make_dir":
            Path(inp["path"]).mkdir(parents=True, exist_ok=True)
            return f"Created: {inp['path']}"

        # ── Navigation ───────────────────────────────────────────────────────
        if name == "list_files":
            root = Path(inp.get("path") or _state["cwd"])
            depth = int(inp.get("depth") or 3)
            result = []
            def walk(p, d):
                if d < 0 or p.name in SKIP: return
                result.append(str(p))
                if p.is_dir():
                    for c in sorted(p.iterdir()): walk(c, d-1)
            walk(root, depth)
            return "\n".join(result)

        if name == "list_dir":
            p = Path(inp.get("path") or _state["cwd"])
            lines = []
            for item in sorted(p.iterdir()):
                size = item.stat().st_size if item.is_file() else 0
                kind = "dir" if item.is_dir() else "file"
                lines.append(f"{kind:4}  {size:>10}  {item.name}")
            return "\n".join(lines)

        # ── Search ───────────────────────────────────────────────────────────
        if name == "search_code":
            pat = inp["pattern"]
            root = Path(inp.get("path") or _state["cwd"])
            glob_pat = inp.get("file_glob", "*")
            results = []
            for fp in root.rglob(glob_pat):
                if any(s in fp.parts for s in SKIP) or not fp.is_file(): continue
                try:
                    for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                        if re.search(pat, line):
                            results.append(f"{fp}:{i}: {line.strip()}")
                except: pass
            return "\n".join(results[:200]) or "No matches found."

        if name == "find_files":
            root = Path(inp.get("path") or _state["cwd"])
            pat = inp["pattern"]
            matches = [str(p) for p in root.rglob(pat) if not any(s in p.parts for s in SKIP)]
            return "\n".join(matches) or "No files found."

        if name == "grep_replace":
            root = inp.get("path") or _state["cwd"]
            glob_pat = inp.get("file_glob","**/*")
            changed = []
            for fp in Path(root).rglob(glob_pat):
                if not fp.is_file() or any(s in fp.parts for s in SKIP): continue
                try:
                    txt = fp.read_text(errors="replace")
                    new = re.sub(inp["pattern"], inp["replacement"], txt)
                    if new != txt:
                        fp.write_text(new)
                        changed.append(str(fp))
                except: pass
            return f"Replaced in {len(changed)} files:\n" + "\n".join(changed)

        if name == "find_duplicates":
            root = Path(inp.get("path") or _state["cwd"])
            hashes = {}
            for fp in root.rglob("*"):
                if not fp.is_file() or any(s in fp.parts for s in SKIP): continue
                h = hashlib.md5(fp.read_bytes()).hexdigest()
                hashes.setdefault(h, []).append(str(fp))
            dupes = {h: fs for h, fs in hashes.items() if len(fs) > 1}
            if not dupes: return "No duplicates found."
            lines = []
            for h, fs in dupes.items():
                lines.append(f"[{h[:8]}] " + ", ".join(fs))
            return "\n".join(lines)

        # ── Execution ────────────────────────────────────────────────────────
        if name == "run_command":
            return _run(inp["command"], cwd=cwd, timeout=inp.get("timeout", 60))

        if name == "run_script":
            import tempfile
            lang = inp["language"]
            ext = {"bash":".sh","python":".py","node":".js"}[lang]
            runner = {"bash":"bash","python":"python3","node":"node"}[lang]
            with tempfile.NamedTemporaryFile(suffix=ext, mode="w", delete=False) as f:
                f.write(inp["code"]); fname = f.name
            out = _run(f"{runner} {fname}", cwd=inp.get("cwd", cwd), timeout=30)
            os.unlink(fname)
            return out

        if name == "check_port":
            host = inp.get("host","localhost")
            port = int(inp["port"])
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3)
                open_ = s.connect_ex((host, port)) == 0
            return f"Port {port} on {host}: {'OPEN' if open_ else 'CLOSED'}"

        if name == "run_tests":
            p = Path(cwd)
            if (p/"pytest.ini").exists() or (p/"setup.cfg").exists() or list(p.rglob("test_*.py")):
                return _run("python -m pytest -v", cwd=cwd, timeout=120)
            if (p/"package.json").exists():
                return _run("npm test", cwd=cwd, timeout=120)
            return "Could not detect test framework."

        if name == "lint_code":
            p = Path(inp["path"])
            if p.suffix == ".py":
                out = _run(f"python -m ruff check {p}")
                if "ruff: not found" in out or "No module" in out:
                    out = _run(f"python -m pylint {p}")
                return out
            return _run(f"npx eslint {p}")

        if name == "format_code":
            p = Path(inp["path"])
            if p.suffix == ".py":
                return _run(f"python -m black {p}")
            if p.suffix in {".js",".ts",".jsx",".tsx",".json",".css",".html"}:
                return _run(f"npx prettier --write {p}")
            if p.suffix == ".go":
                return _run(f"gofmt -w {p}")
            return f"No formatter found for {p.suffix}"

        # ── Analysis ─────────────────────────────────────────────────────────
        if name == "diff_files":
            return _run(f"diff -u {inp['file_a']} {inp['file_b']}")

        if name == "file_stats":
            p = Path(inp["path"])
            st = p.stat()
            content = p.read_bytes()
            return json.dumps({
                "size_bytes": st.st_size,
                "lines": len(content.decode(errors="replace").splitlines()),
                "md5": hashlib.md5(content).hexdigest(),
                "mime": mimetypes.guess_type(str(p))[0] or "unknown",
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat()
            }, indent=2)

        if name == "count_lines":
            root = Path(inp.get("path") or _state["cwd"])
            counts = {}
            for fp in root.rglob("*"):
                if not fp.is_file() or any(s in fp.parts for s in SKIP): continue
                ext = fp.suffix or "other"
                try: counts[ext] = counts.get(ext, 0) + len(fp.read_text(errors="replace").splitlines())
                except: pass
            return "\n".join(f"{ext:12} {n:>8} lines" for ext, n in sorted(counts.items(), key=lambda x: -x[1]))

        if name == "detect_language":
            ext_map = {
                ".py":"Python",".js":"JavaScript",".ts":"TypeScript",".jsx":"React JSX",
                ".tsx":"React TSX",".go":"Go",".rs":"Rust",".java":"Java",".c":"C",
                ".cpp":"C++",".cs":"C#",".rb":"Ruby",".php":"PHP",".swift":"Swift",
                ".kt":"Kotlin",".sh":"Bash",".html":"HTML",".css":"CSS",".sql":"SQL",
                ".md":"Markdown",".json":"JSON",".yaml":"YAML",".toml":"TOML"
            }
            ext = Path(inp["path"]).suffix
            return ext_map.get(ext, f"Unknown ({ext})")

        if name == "read_env":
            p = Path(inp.get("path") or ".env")
            if not p.exists(): return f"{p} not found"
            result = {}
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    result[k.strip()] = v.strip()
            return json.dumps(result, indent=2)

        if name == "code_coverage":
            return _run("python -m pytest --cov=. --cov-report=term-missing", cwd=cwd, timeout=120)

        if name == "system_info":
            try:
                import psutil
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage("/")
                ram_gb = round(mem.total / 1e9, 2)
                ram_pct = mem.percent
                disk_gb = round(disk.total / 1e9, 2)
                disk_free = round(disk.free / disk.total * 100, 1)
            except ImportError:
                ram_gb = ram_pct = disk_gb = disk_free = "psutil not installed"
            return json.dumps({
                "os": platform.system(),
                "os_version": platform.version(),
                "arch": platform.machine(),
                "cpu_cores": os.cpu_count(),
                "ram_gb": ram_gb,
                "ram_used_pct": ram_pct,
                "disk_gb": disk_gb,
                "disk_free_pct": disk_free,
                "python": sys.version.split()[0],
                "node": _run("node --version"),
            }, indent=2)

        # ── Git ──────────────────────────────────────────────────────────────
        if name == "git_status":  return _run("git status", cwd=cwd)
        if name == "git_diff":
            flag = "--staged" if inp.get("staged") else ""
            return _run(f"git diff {flag}", cwd=cwd)
        if name == "git_log":
            n = inp.get("n", 10)
            return _run(f"git log --oneline -n {n}", cwd=cwd)
        if name == "git_commit":
            _run("git add -A", cwd=cwd)
            return _run(f'git commit -m "{inp["message"]}"', cwd=cwd)
        if name == "git_push":
            return _run("git push", cwd=cwd)
        if name == "git_branch":
            action, name_ = inp["action"], inp.get("name","")
            if action == "list":   return _run("git branch -a", cwd=cwd)
            if action == "create": return _run(f"git checkout -b {name_}", cwd=cwd)
            if action == "switch": return _run(f"git checkout {name_}", cwd=cwd)

        # ── Packages ─────────────────────────────────────────────────────────
        if name == "npm_info":
            return _run(f"npm info {inp['package']} name version description")

        if name == "pip_install":
            return _run(f"pip install {inp['packages']}", cwd=cwd, timeout=120)

        if name == "npm_install":
            flag = "--save-dev" if inp.get("dev") else ""
            return _run(f"npm install {flag} {inp['packages']}", cwd=cwd, timeout=120)

        if name == "list_dependencies":
            p = Path(cwd)
            if (p/"package.json").exists():
                data = json.loads((p/"package.json").read_text())
                deps = {**data.get("dependencies",{}), **data.get("devDependencies",{})}
                return "\n".join(f"{k}: {v}" for k, v in deps.items())
            if (p/"requirements.txt").exists():
                return (p/"requirements.txt").read_text()
            return "No package.json or requirements.txt found."

        if name == "audit_packages":
            p = Path(cwd)
            if (p/"package.json").exists(): return _run("npm audit", cwd=cwd)
            if (p/"requirements.txt").exists(): return _run("pip-audit", cwd=cwd)
            return "No package file found."

        # ── Network ──────────────────────────────────────────────────────────
        if name == "url_fetch":
            import urllib.request
            req = urllib.request.Request(
                inp["url"], method=inp.get("method","GET"),
                headers=inp.get("headers",{}))
            if inp.get("body"):
                req.data = inp["body"].encode()
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode(errors="replace")[:8000]

        if name == "api_test":
            import urllib.request, urllib.error
            url = inp["url"]
            method = inp.get("method","GET")
            body = json.dumps(inp["body"]).encode() if inp.get("body") else None
            headers = {"Content-Type":"application/json", **(inp.get("headers") or {})}
            req = urllib.request.Request(url, data=body, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    return f"Status: {r.status}\n{r.read().decode(errors='replace')[:4000]}"
            except urllib.error.HTTPError as e:
                return f"Status: {e.code}\n{e.read().decode(errors='replace')[:2000]}"

        if name == "ping_host":
            flag = "-n" if platform.system() == "Windows" else "-c"
            return _run(f"ping {flag} 3 {inp['host']}")

        if name == "download_file":
            import urllib.request
            urllib.request.urlretrieve(inp["url"], inp["dest"])
            return f"Downloaded to: {inp['dest']}"

        if name == "check_ssl":
            import ssl
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(socket.socket(), server_hostname=inp["host"]) as s:
                s.connect((inp["host"], 443))
                cert = s.getpeercert()
            return json.dumps({
                "subject": dict(x[0] for x in cert["subject"]),
                "issuer": dict(x[0] for x in cert["issuer"]),
                "expires": cert["notAfter"]
            }, indent=2)

        # ── System ───────────────────────────────────────────────────────────
        if name == "process_list":
            try:
                import psutil
                procs = []
                for p in psutil.process_iter(["pid","name","cpu_percent","memory_info"]):
                    try:
                        if inp.get("filter") and inp["filter"].lower() not in p.info["name"].lower():
                            continue
                        procs.append(f"{p.info['pid']:6}  {p.info['name']:<30}  {p.info['cpu_percent']:5.1f}%  {p.info['memory_info'].rss//1024//1024}MB")
                    except: pass
                return "\n".join(procs[:50])
            except ImportError:
                return _run("ps aux | head -50")

        if name == "kill_process":
            if inp.get("pid"):
                os.kill(int(inp["pid"]), signal.SIGTERM)
                return f"Sent SIGTERM to PID {inp['pid']}"
            if inp.get("name"):
                return _run(f"pkill -f {inp['name']}")
            return "Provide pid or name."

        if name == "cron_add":
            existing = _run("crontab -l 2>/dev/null || echo ''")
            new_cron = f"{existing}\n{inp['schedule']} {inp['command']}\n"
            proc = subprocess.run(["crontab","-"], input=new_cron, text=True, capture_output=True)
            return "Cron job added." if proc.returncode == 0 else proc.stderr

        if name == "env_set":
            p = Path(inp.get("path") or ".env")
            lines = p.read_text().splitlines() if p.exists() else []
            key = inp["key"]
            new_line = f'{key}={inp["value"]}'
            for i, line in enumerate(lines):
                if line.startswith(f"{key}="):
                    lines[i] = new_line
                    break
            else:
                lines.append(new_line)
            p.write_text("\n".join(lines) + "\n")
            return f"Set {key} in {p}"

        if name == "disk_usage":
            return _run(f"du -sh {inp.get('path') or _state['cwd']}/* 2>/dev/null | sort -rh | head -20")

        # ── Database ─────────────────────────────────────────────────────────
        if name == "db_query":
            if not db: return "No database connection configured."
            rows = db.execute(inp["sql"])
            return json.dumps([dict(r) for r in rows], indent=2, default=str)

        if name == "db_schema":
            if not db: return "No database connection configured."
            if inp.get("table"):
                rows = db.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{inp['table']}'")
            else:
                rows = db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            return json.dumps([dict(r) for r in rows], indent=2)

        if name == "db_migrate":
            return _run("alembic upgrade head", cwd=cwd)

        if name == "db_backup":
            dest = inp["dest"]
            db_url = os.environ.get("DATABASE_URL","")
            return _run(f"pg_dump {db_url} > {dest}")

        # ── AI Powered ───────────────────────────────────────────────────────
        if name in {"explain_code","review_code","generate_tests","fix_bug","explain_error"}:
            if name == "explain_code":
                content = _read(inp["path"]) if inp.get("path") else inp.get("snippet","")
                return f"__AI_TASK__:explain this code:\n\n{content}"
            if name == "review_code":
                return f"__AI_TASK__:review this code for bugs and improvements:\n\n{_read(inp['path'])}"
            if name == "generate_tests":
                return f"__AI_TASK__:generate comprehensive tests for this code:\n\n{_read(inp['path'])}"
            if name == "fix_bug":
                extra = f"\n\nFile:\n{_read(inp['path'])}" if inp.get("path") else ""
                return f"__AI_TASK__:fix this bug: {inp['error']}{extra}"
            if name == "explain_error":
                return f"__AI_TASK__:explain this error and how to fix it: {inp['error']}"

        # ── Control ──────────────────────────────────────────────────────────
        if name == "confirm_delete":
            _state["delete_approved"] = True
            reason = inp.get("reason", "no reason given")
            return f"Delete approved. Reason: {reason}. Now call the delete tool."

        if name == "done":
            return f"✓ {inp['summary']}"

        if name == "set_working_dir":
            p = Path(inp["path"]).resolve()
            if not p.exists(): return f"Path does not exist: {p}"
            _state["cwd"] = str(p)
            return f"Working dir set to: {p}"

        if name == "get_config":
            return json.dumps(_state, indent=2)

        return f"Unknown tool: {name}"

    except Exception as e:
        return f"ERROR in {name}: {type(e).__name__}: {e}"
