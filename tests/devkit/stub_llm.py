"""Stand-in model: OpenAI-compatible, streaming. Appends every request body to a log.

  python3 stub_llm.py <port> <requests.jsonl>

Point a checkout at it with an env.local (gitignored) in the checkout root:
  OLLAMA_BASE_URL=http://127.0.0.1:<port>
  OLLAMA_MODEL=stub-model
"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
PORT, LOG = int(sys.argv[1]), sys.argv[2]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with open(LOG, "a") as f: f.write(json.dumps(body) + "\n")
        text = "Here is a short plan.\n\n1. Draft the outline.\n2. Review it with the team.\n3. Ship on Friday."
        if body.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for w in text.split(" "):
                self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": w + " "}}]}) + "\n\n").encode()); self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            small = body.get("max_tokens", 999) <= 128
            out = json.dumps({"choices": [{"message": {"role": "assistant", "content": '{"complexity":"low","needs_sympy":false}' if small else text}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
