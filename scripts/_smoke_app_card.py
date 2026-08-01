from pathlib import Path
import time

import access_policy
import agent_tools
import apps_hub

html = Path("index.html").read_text(encoding="utf-8")
assert "script,style,iframe,object,embed,form" in html
assert "function renderAppCard" in html
assert "app_card" in html

ld = access_policy.get_ai_lockdown()
assert ld.get("mock") is not True

r = agent_tools.app_scaffold("VDML Sheet Demo", kind="table")
print("scaffold", r.get("ok"), r.get("app_id"), r.get("port"), r.get("error"))
assert r.get("ok"), r
assert r["port"] in apps_hub.allowlisted_ports()

st = apps_hub.start(r["app_id"])
print("start", st.get("ok"), st.get("status"), st.get("error"))
time.sleep(1.2)
app = st.get("app") or {"id": r["app_id"], "port": r["port"], "url": r["url"]}
probe = apps_hub.probe(app)
print("running", probe.get("running"), "port", probe.get("port"))
print("OK")
