"""One-prompt app scaffold for OpenIDE Create-App Magic.

Materializes a path-jailed starter under the open workspace (or apps home),
then returns a Cortex seed prompt so the agent completes the vertical slice.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from config import DATA_DIR

from . import workspace_api

APPS_HOME = DATA_DIR / "openide-apps"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, *, fallback: str = "app") -> str:
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:48].strip("-")
    return s or fallback


def _pick_template(prompt: str, template: str) -> str:
    t = (template or "auto").strip().lower()
    if t in ("static", "node-api", "fastapi"):
        return t
    p = (prompt or "").lower()
    if any(w in p for w in ("fastapi", "flask", "uvicorn", "python api")):
        return "fastapi"
    if any(w in p for w in ("api", "backend", "endpoint", "json", "node", "express", "bun")):
        return "node-api"
    return "static"


def _seed_prompt(*, prompt: str, template: str, app_path: str, run_hint: str) -> str:
    return (
        f"Complete the scaffolded app at {app_path} (template={template}).\n\n"
        f"User intent:\n{prompt.strip()}\n\n"
        "Constraints:\n"
        "- Keep the existing file layout; extend don't rewrite from scratch.\n"
        "- Fill TODO / FIXME markers; wire UI to real behavior.\n"
        "- Use .env.example OpenFree placeholders — never invent paid keys; "
        "Key Vault / OpenFree later.\n"
        f"- Make it runnable with: {run_hint}\n"
        "- Prefer offline-local behavior; network only if the prompt requires it.\n\n"
        "First actions:\n"
        "1) Read AGENTS.md and .airgpt/rules.md\n"
        "2) Implement the smallest vertical slice that matches the intent\n"
        "3) Leave README run steps accurate\n"
        "4) When done, say how to preview it"
    )


def _files_static(slug: str, prompt: str) -> dict[str, str]:
    title = slug.replace("-", " ").title()
    return {
        "index.html": f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{title}</title>
  <link rel="stylesheet" href="styles.css"/>
</head>
<body>
  <main class="app">
    <header>
      <p class="brand">OpenIDE</p>
      <h1>{title}</h1>
      <p class="lede">Scaffolded from your prompt — Cortex will finish the slice.</p>
    </header>
    <section id="root" class="panel">
      <p class="todo">TODO: build the experience described in AGENTS.md</p>
      <button type="button" id="action">Get started</button>
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
""",
        "styles.css": """:root{
  --bg:#0b0d12;--panel:#141821;--text:#eef1f6;--muted:#9aa3b5;--accent:#8db4ff;
  --line:rgba(255,255,255,.1);
}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;font-family:ui-sans-serif,system-ui,Segoe UI,sans-serif;
  background:radial-gradient(120% 80% at 50% -10%,#1a2233 0%,var(--bg) 55%);color:var(--text)}
.app{max-width:720px;margin:0 auto;padding:48px 20px 80px}
.brand{margin:0 0 8px;letter-spacing:.14em;text-transform:uppercase;font-size:11px;color:var(--accent)}
h1{margin:0 0 8px;font-size:clamp(28px,5vw,40px);letter-spacing:-.03em}
.lede{margin:0 0 28px;color:var(--muted);line-height:1.5}
.panel{padding:20px;border:1px solid var(--line);border-radius:16px;background:rgba(20,24,33,.9)}
.todo{margin:0 0 16px;color:var(--muted)}
button{appearance:none;border:0;border-radius:999px;padding:10px 16px;font:inherit;font-weight:600;
  background:#fff;color:#0a0a0a;cursor:pointer}
button:hover{filter:brightness(1.05)}
""",
        "app.js": """const btn=document.getElementById('action');
const root=document.getElementById('root');
btn?.addEventListener('click',()=>{
  const note=document.createElement('p');
  note.textContent='Hook this button to real app behavior (see AGENTS.md).';
  note.style.marginTop='12px';
  root?.appendChild(note);
});
// TODO: implement core UX from the user prompt
""",
        "README.md": f"""# {title}

Scaffolded by OpenIDE Create-App.

## Run

```bash
python -m http.server 5173
```

Open http://127.0.0.1:5173/

## Intent

{prompt.strip()}
""",
        ".env.example": (
            "OPENFREE_BASE_URL=http://127.0.0.1:20128/v1\n"
            "OPENFREE_API_KEY=\n"
            "# Paste BYOK in AirGPT Key Vault — never commit secrets.\n"
        ),
        ".airgpt/rules.md": f"# App rules\n\nIntent: {prompt.strip()}\n\nPrefer small diffs. Keep static hosting working.\n",
        "AGENTS.md": f"""# {title}

User asked: {prompt.strip()}

- Template: static
- Fill TODO markers in index.html / app.js / styles.css
- Keep offline-first; OpenFree keys via Key Vault if AI calls are needed
- Preview: python -m http.server 5173
""",
    }


def _files_node_api(slug: str, prompt: str) -> dict[str, str]:
    title = slug.replace("-", " ").title()
    return {
        "package.json": f"""{{
  "name": "{slug}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "start": "node server.js"
  }}
}}
""",
        "server.js": f"""const http=require('http');
const fs=require('fs');
const path=require('path');
const PORT=process.env.PORT||8787;
const publicDir=path.join(__dirname,'public');

const server=http.createServer((req,res)=>{{
  if(req.url==='/health'){{
    res.writeHead(200,{{'Content-Type':'application/json'}});
    res.end(JSON.stringify({{ok:true,app:'{slug}'}}));
    return;
  }}
  if(req.url==='/api/hello'){{
    res.writeHead(200,{{'Content-Type':'application/json'}});
    res.end(JSON.stringify({{message:'Hello from OpenIDE scaffold',todo:true}}));
    return;
  }}
  let file=path.join(publicDir,req.url==='/'?'index.html':req.url.replace(/^\\//,''));
  if(!file.startsWith(publicDir)){{res.writeHead(403);res.end('denied');return}}
  fs.readFile(file,(err,data)=>{{
    if(err){{res.writeHead(404);res.end('not found');return}}
    const ext=path.extname(file);
    const type=ext==='.js'?'text/javascript':ext==='.css'?'text/css':'text/html';
    res.writeHead(200,{{'Content-Type':type}});
    res.end(data);
  }});
}});
server.listen(PORT,()=>console.log('listening on http://127.0.0.1:'+PORT));
// TODO: wire real API routes for the user intent
""",
        "public/index.html": f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title><style>
body{{margin:0;font-family:system-ui;background:#0b0d12;color:#eef1f6;padding:40px 20px}}
main{{max-width:640px;margin:0 auto}} button{{padding:10px 14px;border-radius:999px;border:0;font-weight:600;cursor:pointer}}
#out{{margin-top:16px;color:#9aa3b5}}
</style></head><body><main>
<p style="letter-spacing:.12em;text-transform:uppercase;font-size:11px;color:#8db4ff">OpenIDE</p>
<h1>{title}</h1>
<p>API scaffold — Cortex will implement your intent.</p>
<button id="ping" type="button">Call /api/hello</button>
<pre id="out"></pre>
<script src="app.js"></script>
</main></body></html>
""",
        "public/app.js": """document.getElementById('ping')?.addEventListener('click',async()=>{
  const out=document.getElementById('out');
  try{
    const r=await fetch('/api/hello').then(x=>x.json());
    out.textContent=JSON.stringify(r,null,2);
  }catch(e){out.textContent=String(e)}
});
// TODO: build UI against real endpoints
""",
        "README.md": f"""# {title}

## Run

```bash
npm start
```

Open http://127.0.0.1:8787/

## Intent

{prompt.strip()}
""",
        ".env.example": (
            "PORT=8787\n"
            "OPENFREE_BASE_URL=http://127.0.0.1:20128/v1\n"
            "OPENFREE_API_KEY=\n"
        ),
        ".airgpt/rules.md": f"# App rules\n\nIntent: {prompt.strip()}\n\nExtend server.js routes; keep /health.\n",
        "AGENTS.md": f"""# {title}

User asked: {prompt.strip()}

- Template: node-api
- Implement API + public UI; keep npm start working
- OpenFree via Key Vault if model calls needed
""",
    }


def _files_fastapi(slug: str, prompt: str) -> dict[str, str]:
    title = slug.replace("-", " ").title()
    return {
        "requirements.txt": "fastapi>=0.110\nuvicorn>=0.27\n",
        "app.py": f'''"""{title} — OpenIDE FastAPI scaffold."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="{title}")
STATIC = Path(__file__).resolve().parent / "static"


@app.get("/health")
def health():
    return {{"ok": True, "app": "{slug}"}}


@app.get("/api/hello")
def hello():
    # TODO: replace with real domain logic
    return {{"message": "Hello from OpenIDE FastAPI scaffold", "todo": True}}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8788)
''',
        "static/index.html": f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title><style>
body{{margin:0;font-family:system-ui;background:#0b0d12;color:#eef1f6;padding:40px 20px}}
main{{max-width:640px;margin:0 auto}} button{{padding:10px 14px;border-radius:999px;border:0;font-weight:600}}
#out{{margin-top:16px;color:#9aa3b5}}
</style></head><body><main>
<p style="letter-spacing:.12em;text-transform:uppercase;font-size:11px;color:#8db4ff">OpenIDE</p>
<h1>{title}</h1>
<p>FastAPI scaffold — Cortex will implement your intent.</p>
<button id="ping" type="button">Call /api/hello</button>
<pre id="out"></pre>
<script src="/static/app.js"></script>
</main></body></html>
""",
        "static/app.js": """document.getElementById('ping')?.addEventListener('click',async()=>{
  const out=document.getElementById('out');
  try{
    const r=await fetch('/api/hello').then(x=>x.json());
    out.textContent=JSON.stringify(r,null,2);
  }catch(e){out.textContent=String(e)}
});
""",
        "README.md": f"""# {title}

## Run

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8788/

## Intent

{prompt.strip()}
""",
        ".env.example": (
            "OPENFREE_BASE_URL=http://127.0.0.1:20128/v1\n"
            "OPENFREE_API_KEY=\n"
        ),
        ".airgpt/rules.md": f"# App rules\n\nIntent: {prompt.strip()}\n\nExtend FastAPI routes; keep /health.\n",
        "AGENTS.md": f"""# {title}

User asked: {prompt.strip()}

- Template: fastapi
- Implement routes + static UI; keep `python app.py` working
""",
    }


_BUILDERS = {
    "static": (_files_static, "python -m http.server 5173", "http://127.0.0.1:5173/"),
    "node-api": (_files_node_api, "npm start", "http://127.0.0.1:8787/"),
    "fastapi": (_files_fastapi, "python app.py", "http://127.0.0.1:8788/"),
}


def ensure_apps_workspace() -> dict[str, Any]:
    """Open DATA_DIR/openide-apps as workspace when none is bound."""
    ws = workspace_api.get_workspace()
    if ws.get("ok"):
        return ws
    APPS_HOME.mkdir(parents=True, exist_ok=True)
    return workspace_api.open_workspace(str(APPS_HOME), name="openide-apps")


def scaffold(
    *,
    prompt: str,
    name: str = "",
    template: str = "auto",
    parent: str = "apps",
) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt required"}

    ws = ensure_apps_workspace()
    if not ws.get("ok"):
        return {"ok": False, "error": ws.get("error") or "could not open apps workspace"}

    picked = _pick_template(prompt, template)
    builder, run_hint, preview = _BUILDERS[picked]
    slug = _slugify(name) if name.strip() else _slugify(prompt, fallback="app")
    parent = (parent or "apps").replace("\\", "/").strip("/") or "apps"
    app_rel = f"{parent}/{slug}"

    root = Path(ws["root"]).resolve()
    dest = (root / parent / slug).resolve()
    try:
        dest.relative_to(root)
    except ValueError:
        return {"ok": False, "error": "path escape denied"}
    if dest.exists() and any(dest.iterdir()):
        return {"ok": False, "error": f"app exists: {app_rel}", "app_path": app_rel}

    rel_files = {f"{app_rel}/{rel}": content for rel, content in builder(slug, prompt).items()}
    written = workspace_api.write_tree(rel_files, apply=True)
    if not written.get("ok"):
        return written

    # Prompt-trend memory (one-step-ahead automations)
    trend_hint = ""
    try:
        from . import prompt_trends

        trend = prompt_trends.record_and_advise(prompt)
        if trend.get("advice"):
            trend_hint = "\n\n[automation from your past prompts]\n" + trend["advice"]
    except Exception:
        pass

    seed = _seed_prompt(prompt=prompt, template=picked, app_path=app_rel, run_hint=run_hint) + trend_hint
    return {
        "ok": True,
        "template": picked,
        "slug": slug,
        "app_path": app_rel,
        "abs_path": str(dest),
        "files": sorted(rel_files.keys()),
        "run_hint": run_hint,
        "preview_hint": preview,
        "openfree": {
            "base_url": "http://127.0.0.1:20128/v1",
            "env_keys": ["OPENFREE_BASE_URL", "OPENFREE_API_KEY"],
        },
        "seed_prompt": seed,
        "workspace_root": ws.get("root") or "",
        "workspace_name": ws.get("name") or "",
    }
