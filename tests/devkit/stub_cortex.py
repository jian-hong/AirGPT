#!/usr/bin/env python3
"""Stand-in Cortex engine for driving AirGPT's agent UI. Stdlib only.

  python3 stub_cortex.py 8710 [log.jsonl]

Point the app at it (in the checkout's gitignored env.local):
  CORTEX_API_URL=http://127.0.0.1:8710
  CORTEX_AUTOSPAWN=0          # stops cortex_client trying to spawn D:\\Cortex via PowerShell
Cortex "down" = kill this process (pkill -f "^python3 [^ ]*stub_cortex.py 8710").

Answers (shapes read from cortex_client.py):
  GET  /health                       {status:ok, pack:netie}   (no surface=constructor)
  GET  /api/engine/specs|activity|backends, /api/memory/stats
  POST /api/engine/run   NON-streaming, as the real client expects:
        {ok, content, stop_reason, quality_passed, telemetry:{tools:[{tool,ok,summary,ms}]}}
        Prompt keywords steer it: STUBSLOW (sleeps 12 s), STUBFAIL (ok:false),
        STUBEMPTY (ok:true, empty content), STUBTOOLFAIL (one tool ok:false)
  GET/POST /api/routines[/draft], /api/routines/<id>[/pause|resume|run|runs], DELETE
  GET/POST /api/goals, /api/goals/<id>[/seeks|/values], DELETE
  GET  /api/apps
  GET  /api/workflows, /api/workflows/tasks, /api/workflows/task/<id>[/events SSE]
  POST /api/workflows/run|cancel|clear|recognize|hardware
  POST /api/context/assemble|compact
Every request is appended to the log file as one JSON line. State is in memory only.
A workflow task started via /api/workflows/run finishes by itself after 9 s.
"""
import json, sys, time, threading, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8710
LOG = sys.argv[2] if len(sys.argv) > 2 else None
LOCK = threading.Lock()
ROUTINES, GOALS, TASKS = {}, {}, {}


def log(rec):
    if LOG:
        with LOCK, open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")


def run_result(prompt):
    p = prompt or ""
    if "STUBSLOW" in p:
        time.sleep(12)
    if "STUBFAIL" in p:
        return {"ok": False, "error": "engine agent loop failed: model backend refused"}
    okf = "STUBTOOLFAIL" not in p
    tools = [
        {"tool": "web_search", "ok": True, "summary": "5 results for the request", "ms": 840},
        {"tool": "web_fetch", "ok": okf, "summary": "fetched https://example.com/a (12 KB)" if okf else "HTTP 503", "ms": 420},
        {"tool": "vault_read", "ok": True, "summary": "3 notes matched", "ms": 35},
        {"tool": "web_search", "ok": True, "summary": "2 results, second query", "ms": 610},
    ]
    content = "" if "STUBEMPTY" in p else "Here is the plan.\n\n1. Gathered sources.\n2. Cross-checked them.\n3. Wrote this summary."
    return {"ok": True, "content": content, "stop_reason": "quality", "quality_passed": True,
            "telemetry": {"tools": tools, "steps": 4}}


def mk_task(goal, wid="deep_research"):
    tid = "wf_" + uuid.uuid4().hex[:8]
    TASKS[tid] = {"id": tid, "name": wid.replace("_", " ").title(), "kind": "Workflow", "status": "running",
                  "t0": time.time(), "description": goal}
    return tid


def task_view(t):
    el = time.time() - t["t0"]
    done = el > 9
    if done and t["status"] == "running":
        t["status"] = "done"
    st = t["status"]

    def mk(i, s, tk):
        return {"id": f"agent-{i}", "node_id": f"n{i}", "status": s, "tokens": tk, "tool_count": 2,
                "elapsed": min(el, 3 * i + 3), "purpose": f"step {i}", "excerpt": "partial notes...",
                "model": "stub", "tier": "high",
                "tool_detail": [{"tool": "web_search", "ok": True, "ms": 700, "summary": "ok"}]}
    ph = [{"id": "p1", "name": "Plan", "status": "done", "agents": [mk(1, "done", 400)]},
          {"id": "p2", "name": "Research", "status": "done" if done else "running",
           "agents": [mk(2, "done" if done else "running", 900)]}]
    return {"id": t["id"], "name": t["name"], "kind": t["kind"], "status": st, "elapsed": el,
            "description": t["description"],
            "totals": {"agents": 2, "tokens": 1300, "tools": 4, "phases_done": 2 if done else 1, "phases_total": 2},
            "phases": ph}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n).decode() or "{}") if n else {}
        except Exception:
            return {}

    def do_GET(self): self._route("GET")
    def do_POST(self): self._route("POST")
    def do_DELETE(self): self._route("DELETE")

    def _route(self, m):
        path = self.path.split("?")[0].rstrip("/") or "/"
        body = self._body() if m != "GET" else {}
        log({"t": time.time(), "m": m, "path": path, "body": body})
        P = path.split("/")
        if path == "/health":
            return self._send(200, {"status": "ok", "pack": "netie", "stub": True})
        if path == "/api/engine/specs":
            return self._send(200, {"ok": True, "engine": {"name": "stub-cortex"}, "config": {"backend": "stub"}, "backends": []})
        if path == "/api/engine/backends":
            return self._send(200, {"ok": True, "backends": []})
        if path == "/api/engine/activity":
            return self._send(200, {"ok": True, "routines": list(ROUTINES.values()), "workflows": [], "races": [], "apps": []})
        if path == "/api/memory/stats":
            return self._send(200, {"ok": True, "items": 3})
        if path == "/api/context/assemble":
            return self._send(200, {"ok": True, "prompt": "", "meta": {}})
        if path == "/api/context/compact":
            return self._send(200, {"ok": True, "messages": body.get("messages", [])})
        if path == "/api/engine/run" and m == "POST":
            return self._send(200, run_result(str(body.get("prompt") or "")))
        if path == "/api/routines/draft" and m == "POST":
            g = str(body.get("goal") or "")
            return self._send(200, {"ok": True, "draft": {"name": g[:40] or "Routine", "schedule_text": "Every weekday 09:00",
                    "prompt": g, "depth": "basic", "next_run_at": time.time() + 3600, "assumptions": ["UTC+8", "Email on failure"]},
                    "suggestions": []})
        if path == "/api/routines":
            if m == "POST":
                rid = "rt_" + uuid.uuid4().hex[:6]
                g = str(body.get("goal") or "")
                r = {"id": rid, "name": g[:40], "prompt": g, "schedule_text": "Every weekday 09:00", "status": "active",
                     "next_run_at": time.time() + 3600, "agent_id": body.get("agent_id")}
                ROUTINES[rid] = r
                return self._send(200, {"ok": True, "routine": r, "routine_id": rid, "next_run_at": r["next_run_at"]})
            return self._send(200, {"ok": True, "routines": list(ROUTINES.values()), "budget": {"spent_myr": 0.4, "cap_myr": 25}})
        if len(P) >= 4 and P[1:3] == ["api", "routines"]:
            rid = P[3]
            r = ROUTINES.get(rid)
            if not r:
                return self._send(404, {"detail": "no such routine"})
            if m == "DELETE":
                ROUTINES.pop(rid)
                return self._send(200, {"ok": True})
            act = P[4] if len(P) > 4 else ""
            if act == "pause":
                r["status"] = "paused"
            elif act == "resume":
                r["status"] = "active"
            elif act == "run":
                r["next_run_at"] = time.time() + 86400
                return self._send(200, {"ok": True, "routine": r, "run": {"steps": [{"tool": "web_search"}, {"tool": "vault_read"}], "output": "done"}})
            elif act == "runs":
                return self._send(200, {"ok": True, "runs": []})
            return self._send(200, {"ok": True, "routine": r, "next_run_at": r["next_run_at"]})
        if path == "/api/goals":
            if m == "POST":
                gid = "g_" + uuid.uuid4().hex[:6]
                GOALS[gid] = {"id": gid, "statement": body.get("statement", "")}
                return self._send(200, {"ok": True, "goal": GOALS[gid]})
            return self._send(200, {"ok": True, "goals": list(GOALS.values())})
        if len(P) >= 4 and P[1:3] == ["api", "goals"]:
            gid = P[3]
            if m == "DELETE":
                GOALS.pop(gid, None)
                return self._send(200, {"ok": True})
            if len(P) > 4 and P[4] == "seeks":
                return self._send(200, {"ok": True, "history": []})
            if len(P) > 4 and P[4] == "values":
                return self._send(200, {"ok": True, "values": []})
            return self._send(200, {"ok": True, "goal": GOALS.get(gid, {})})
        if path == "/api/apps":
            return self._send(200, {"ok": True, "apps": []})
        if path == "/api/workflows":
            return self._send(200, {"ok": True, "workflows": [{"id": "deep_research", "name": "Deep research"}]})
        if path == "/api/workflows/tasks":
            vs = [task_view(t) for t in list(TASKS.values())]
            return self._send(200, {"ok": True, "running": [v for v in vs if v["status"] == "running"],
                                    "finished": [v for v in vs if v["status"] != "running"]})
        if path == "/api/workflows/run" and m == "POST":
            tid = mk_task(str(body.get("goal") or ""), str(body.get("workflow_id") or "deep_research"))
            return self._send(200, {"ok": True, "task_id": tid, "id": tid})
        if path == "/api/workflows/cancel" and m == "POST":
            t = TASKS.get(body.get("task_id"))
            if t:
                t["status"] = "cancelled"
            return self._send(200, {"ok": True})
        if path == "/api/workflows/clear" and m == "POST":
            for k in [k for k, t in TASKS.items() if t["status"] != "running"]:
                TASKS.pop(k)
            return self._send(200, {"ok": True})
        if path == "/api/workflows/recognize" and m == "POST":
            p = str(body.get("prompt") or "").lower()
            hit = "research" in p and len(p) > 30
            return self._send(200, {"ok": True, "should_run": hit, "template_id": "deep_research" if hit else None})
        if path == "/api/workflows/hardware":
            return self._send(200, {"ok": True})
        if len(P) >= 5 and P[1:4] == ["api", "workflows", "task"]:
            t = TASKS.get(P[4])
            if len(P) > 5 and P[5] == "events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for i in range(6):
                        self.wfile.write(f"data: {json.dumps({'n': i})}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(1.5)
                except Exception:
                    pass
                return
            return self._send(200, {"ok": True, "task": task_view(t) if t else None})
        return self._send(404, {"detail": "stub: not implemented " + path})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
