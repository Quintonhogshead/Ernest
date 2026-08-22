"""Ernest's local dashboard — a localhost control panel for config and status.

  python -m dashboard.app                      # http://127.0.0.1:8787 (local, no auth)
  python -m dashboard.app --host 0.0.0.0        # bind all interfaces (Fly.io)

SECURITY MODEL
  * On localhost (127.0.0.1) it serves without a password — safe on your machine.
  * On ANY other host it REQUIRES a password (ERNEST_DASHBOARD_PASSWORD) and
    refuses to start without one (fail closed). It handles credentials, so an
    unauthenticated public instance is never allowed.
  * Deploy behind HTTPS only (Fly.io terminates TLS for you). Even so, anyone
    with the URL + password can read/write your keys — use a strong password and
    keep the app private. See DEPLOY-FLY.md.

Zero extra dependencies: standard-library http.server + HTTP Basic Auth.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import html
import json
import os
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ernest import envfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.environ.get("ERNEST_ENV_PATH") or os.path.join(ROOT, ".env")
PASSWORD = os.environ.get("ERNEST_DASHBOARD_PASSWORD") or ""

# Jobs the dashboard is allowed to launch (all read-only / dry where it matters).
RUNNABLE = {
    "ping": ["jobs.ping"],
    "triage": ["jobs.triage", "--dry-run", "--limit", "15"],
    "canvas": ["jobs.canvas_sync", "--dry-run"],
    "news": ["jobs.news", "--dry-run"],
    "brief": ["jobs.brief", "morning", "--dry-run"],
    "backfill": ["jobs.backfill", "--limit", "40"],
}


# ── status helpers ───────────────────────────────────────────────────────────

def _library_count() -> int | None:
    try:
        from ernest.store import connect

        db = os.environ.get("ERNEST_DB_PATH") or os.path.join(ROOT, "state", "ernest.db")
        conn = connect(db)
        row = conn.execute("SELECT COUNT(*) AS n FROM library").fetchone()
        conn.close()
        return int(row["n"])
    except Exception:
        return None


def _creds_dir() -> str:
    from ernest.config import load

    return load().google_credentials_dir


def _token_files() -> list[str]:
    d = _creds_dir()
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d)
                  if f.startswith(("token_", "ms_token_")) and f.endswith(".json"))


def _valid_token_name(name: str) -> bool:
    return (
        name.endswith(".json")
        and (name.startswith("token_") or name.startswith("ms_token_"))
        and "/" not in name and "\\" not in name and ".." not in name
    )


def _recent_audit(limit: int = 8) -> list[dict]:
    try:
        from ernest.audit import read_events

        return read_events()[-limit:][::-1]
    except Exception:
        return []


# ── HTML rendering ───────────────────────────────────────────────────────────

_CSS = """
:root{
  --bg:#F2F3EC;--surface:#FAFAF5;--ink:#20261F;--muted:#5F685A;--line:#D9DCCD;
  --accent:#1E6B47;--accent-soft:#E2ECE3;--brass:#8A6B24;--danger:#8f2b2b;
  --display:"Iowan Old Style",Georgia,serif;--mono:ui-monospace,"SF Mono",Menlo,monospace;
}
@media(prefers-color-scheme:dark){:root{
  --bg:#141813;--surface:#1B201A;--ink:#E6E4D6;--muted:#9BA391;--line:#2E352B;
  --accent:#5CBE8D;--accent-soft:#1E2C23;--brass:#CBA24E;--danger:#e88;
}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:Georgia,serif;margin:0;
  line-height:1.5;padding:0 1.2rem 4rem}
.wrap{max-width:52rem;margin:0 auto}
header{padding:2.4rem 0 1.2rem;border-bottom:1px solid var(--line);margin-bottom:1.6rem}
h1{font-family:var(--display);font-size:2.4rem;margin:0 0 .3rem;letter-spacing:-.01em}
.sub{color:var(--muted);margin:0}
.warn{background:var(--accent-soft);border-left:3px solid var(--brass);padding:.7rem 1rem;
  margin:1.2rem 0;font-size:.9rem}
.flash{background:var(--accent-soft);border-left:3px solid var(--accent);padding:.7rem 1rem;
  margin:1.2rem 0;font-size:.95rem}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:1.4rem}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--line);border-radius:4px;padding:1.1rem 1.2rem}
.card h2{font-family:var(--display);font-size:1.15rem;margin:0 0 .8rem;font-weight:400}
label{display:block;font-size:.82rem;color:var(--muted);margin:.6rem 0 .2rem}
input{width:100%;padding:.5rem .6rem;border:1px solid var(--line);border-radius:3px;
  background:var(--bg);color:var(--ink);font-family:var(--mono);font-size:.85rem}
input:focus{outline:2px solid var(--accent);outline-offset:1px}
.set{color:var(--accent);font-size:.72rem;font-family:var(--mono);float:right}
button{font-family:inherit;font-size:.95rem;padding:.55rem 1.1rem;border-radius:3px;
  border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
button.ghost{background:transparent;color:var(--accent)}
.save-row{margin:1.6rem 0}
.status dl{margin:0;font-size:.9rem}
.status dt{color:var(--muted);font-size:.78rem;margin-top:.5rem}
.pill{display:inline-block;font-family:var(--mono);font-size:.72rem;padding:.1rem .5rem;
  border-radius:99px;border:1px solid var(--line)}
.ok{color:var(--accent);border-color:var(--accent)}
.no{color:var(--muted)}
.runbar{display:flex;flex-wrap:wrap;gap:.5rem;margin:.6rem 0}
pre{background:var(--bg);border:1px solid var(--line);border-radius:3px;padding:.8rem;
  font-family:var(--mono);font-size:.78rem;overflow-x:auto;white-space:pre-wrap;max-height:22rem}
.audit{font-family:var(--mono);font-size:.76rem;color:var(--muted)}
.audit b{color:var(--ink);font-weight:600}
footer{color:var(--muted);font-size:.8rem;margin-top:2rem;text-align:center}
"""


def _field_html(values: dict[str, str]) -> dict[str, str]:
    groups: dict[str, list[str]] = {}
    for key, label, group, secret, placeholder in envfile.FIELDS:
        current = values.get(key, "")
        if secret:
            badge = '<span class="set">stored</span>' if current else ""
            ph = "•••• leave blank to keep" if current else placeholder
            field = (
                f'<label>{html.escape(label)}{badge}</label>'
                f'<input type="password" name="{key}" placeholder="{html.escape(ph)}" '
                f'autocomplete="off">'
            )
        else:
            field = (
                f'<label>{html.escape(label)}</label>'
                f'<input type="text" name="{key}" value="{html.escape(current)}" '
                f'placeholder="{html.escape(placeholder)}">'
            )
        groups.setdefault(group, []).append(field)
    return {g: "".join(fs) for g, fs in groups.items()}


def render(flash: str = "") -> str:
    values = envfile.read_values(ENV_PATH)
    grouped = _field_html(values)
    lib = _library_count()
    audit = _recent_audit()

    def status_pill(key: str) -> str:
        on = bool(values.get(key))
        return f'<span class="pill {"ok" if on else "no"}">{"set" if on else "unset"}</span>'

    cards = "".join(
        f'<div class="card"><h2>{html.escape(group)}</h2>{fields}</div>'
        for group, fields in grouped.items()
    )

    audit_html = "".join(
        f'<div class="audit"><b>{html.escape(e.get("job",""))}.{html.escape(e.get("action",""))}</b> '
        f'· {html.escape(e.get("ts","")[:19])}</div>'
        for e in audit
    ) or '<div class="audit">no activity logged yet</div>'

    flash_html = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    present = _token_files()
    tokens_present = ", ".join(html.escape(f) for f in present) if present else "none yet"

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ernest — dashboard</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header><h1>🎩 Ernest</h1><p class="sub">Local control panel · config &amp; status</p></header>
<div class="warn">🔒 This page edits <code>.env</code> (your API keys) and can launch
read-only jobs. {"It's <b>password-protected</b> and should only be reachable over HTTPS on your private Fly app." if PASSWORD else "It runs on <b>your machine only</b> (127.0.0.1); no password is needed locally."}
Anyone who can reach it and knows the password can read and change your keys.</div>
{flash_html}
<form method="post" action="/save">
<div class="grid">{cards}</div>
<div class="save-row"><button type="submit">Save configuration</button>
<span class="sub" style="margin-left:1rem">Blank secret fields keep the stored value.</span></div>
</form>

<div class="card">
<h2>Mail tokens</h2>
<p class="sub" style="font-size:.85rem">Move the OAuth token files created by
<code>authorize.py</code> onto this server. On your Mac, open the file (e.g.
<code>state/google/token_work.json</code>), copy its contents, paste below, and save.
Present here: {tokens_present}</p>
<form method="post" action="/token">
<label>File name</label>
<input type="text" name="name" placeholder="token_work.json  or  ms_token_business.json" autocomplete="off">
<label>File contents (JSON)</label>
<textarea name="content" rows="5" style="width:100%;font-family:var(--mono);font-size:.78rem;
  background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:3px;padding:.5rem"
  placeholder='{{"token": "...", "refresh_token": "...", ...}}'></textarea>
<div style="margin-top:.6rem"><button type="submit">Upload token</button></div>
</form>
</div>

<div class="card status">
<h2>Status</h2>
<dl>
<dt>Anthropic key</dt><dd>{status_pill("ANTHROPIC_API_KEY")}</dd>
<dt>OpenAI key</dt><dd>{status_pill("OPENAI_API_KEY")}</dd>
<dt>Discord</dt><dd>{status_pill("ERNEST_DISCORD_TOKEN")} {status_pill("ERNEST_DISCORD_USER_ID")}</dd>
<dt>Canvas</dt><dd>{status_pill("CANVAS_TOKEN")}</dd>
<dt>Library</dt><dd><span class="pill">{lib if lib is not None else "—"} chunks</span></dd>
</dl>
<h2 style="margin-top:1.2rem">Try a job (dry-run)</h2>
<div class="runbar">
<button class="ghost" onclick="run(event,'ping')">Ping me on Discord</button>
<button class="ghost" onclick="run(event,'triage')">Triage</button>
<button class="ghost" onclick="run(event,'canvas')">Canvas</button>
<button class="ghost" onclick="run(event,'news')">News</button>
<button class="ghost" onclick="run(event,'brief')">Morning brief</button>
<button class="ghost" onclick="run(event,'backfill')">Backfill library (40/acct)</button>
</div>
<pre id="out">output appears here…</pre>
<h2 style="margin-top:1.2rem">Recent activity</h2>
{audit_html}
</div>
<footer>Ernest v0.1 · read-only core · stop the server with Ctrl-C</footer>
</div>
<script>
async function run(ev,name){{
  ev.preventDefault();
  const out=document.getElementById('out');
  out.textContent='running '+name+'…';
  try{{
    const r=await fetch('/run?job='+encodeURIComponent(name),{{method:'POST'}});
    const j=await r.json();
    out.textContent=j.output||j.error||'(no output)';
  }}catch(e){{out.textContent='error: '+e;}}
}}
</script>
</body></html>"""


# ── HTTP handler ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def _authed(self) -> bool:
        """True if no password is required, or Basic Auth matches it."""
        if not PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8", "replace")
            _user, _, supplied = decoded.partition(":")
        except Exception:
            return False
        return hmac.compare_digest(supplied, PASSWORD)

    def _require_auth(self) -> bool:
        if self._authed():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Ernest"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_a):  # keep the console quiet (no request logging)
        pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/healthz":  # unauthenticated: Fly health probe
            self._send(200, "ok", "text/plain")
            return
        if not self._require_auth():
            return
        if path == "/":
            self._send(200, render())
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if not self._require_auth():
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/save":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            form = urllib.parse.parse_qs(body, keep_blank_values=True)
            keys = {k for k, *_ in envfile.FIELDS}
            updates = {k: v[0].strip() for k, v in form.items() if k in keys}
            envfile.write_values(ENV_PATH, updates)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
        elif parsed.path == "/token":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            form = urllib.parse.parse_qs(body, keep_blank_values=True)
            name = (form.get("name", [""])[0]).strip()
            content = form.get("content", [""])[0]
            if _valid_token_name(name) and content.strip():
                try:
                    json.loads(content)  # reject non-JSON before writing
                    d = _creds_dir()
                    os.makedirs(d, exist_ok=True)
                    path = os.path.join(d, name)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(content)
                    os.chmod(path, 0o600)
                except Exception:
                    pass  # invalid JSON or write error → silently ignore, page re-renders
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
        elif parsed.path == "/run":
            qs = urllib.parse.parse_qs(parsed.query)
            job = (qs.get("job") or [""])[0]
            self._send(200, json.dumps(self._run(job)), "application/json")
        else:
            self._send(404, "not found", "text/plain")

    def _run(self, job: str) -> dict:
        if job not in RUNNABLE:
            return {"error": f"unknown job: {job}"}
        try:
            proc = subprocess.run(
                [sys.executable, "-m", *RUNNABLE[job]],
                cwd=ROOT, capture_output=True, text=True, timeout=120,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            return {"output": out.strip() or "(no output)"}
        except subprocess.TimeoutExpired:
            return {"error": "job timed out after 120s"}
        except Exception as exc:
            return {"error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8787)))
    parser.add_argument("--host", default="127.0.0.1",
                        help="127.0.0.1 for local (default); 0.0.0.0 to expose (needs a password)")
    args = parser.parse_args()

    is_local = args.host in ("127.0.0.1", "localhost", "::1")
    if not is_local and not PASSWORD:
        sys.exit(
            "REFUSING TO START: binding a non-local host without a password would "
            "expose your API keys.\nSet ERNEST_DASHBOARD_PASSWORD (a strong secret) "
            "and try again. See DEPLOY-FLY.md."
        )

    if os.environ.get("ERNEST_RUN_SCHEDULER"):
        from ernest.scheduler import start_background

        start_background(ROOT)
        print("⏱️  scheduler started (triage + briefs + canvas + news)")

    if os.environ.get("ERNEST_RUN_BOT"):
        from ernest.bot import start_background as start_bot

        start_bot()
        print("💬 interactive Discord bot started (ask / research / status)")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    where = "localhost only" if is_local else f"{args.host} · password-protected"
    print(f"🎩 Ernest dashboard → http://{args.host}:{args.port}  ({where}; Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
