from pathlib import Path

p = Path(r"D:\AirGPT\index.html")
t = p.read_text(encoding="utf-8")
old = (
    "async function approveJoin(ip,name){\n"
    "  try{\n"
    "    await api('/api/access/approve',{method:'POST',body:JSON.stringify({ip,name:name||''})});\n"
    "    toast('Approved '+ip);pollJoinRequests();\n"
    "  }catch(e){toast('Approve failed')}\n"
    "}"
)
new = (
    "async function approveJoin(ip,name){\n"
    "  try{\n"
    "    await api('/api/access/approve',{method:'POST',body:JSON.stringify({ip,name:name||'',capability:'llm_edit'})});\n"
    "    toast('Allowed · LLM on host (clipboard paste off)');pollJoinRequests();\n"
    "  }catch(e){toast('Approve failed')}\n"
    "}"
)
if old not in t:
    raise SystemExit("approveJoin missing")
p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("approveJoin ok")

c = Path(r"D:\AirGPT\clipdrop.py")
ct = c.read_text(encoding="utf-8")
a = 'access_policy.approve(data.get("ip", ""), data.get("name", ""))'
b = 'access_policy.approve(data.get("ip", ""), data.get("name", ""), capability=str(data.get("capability", "llm_edit") or "llm_edit"))'
a2 = 'access_policy.approve(body.get("ip", ""), body.get("name", ""))'
b2 = 'access_policy.approve(body.get("ip", ""), body.get("name", ""), capability=str(body.get("capability", "llm_edit") or "llm_edit"))'
n = 0
if a in ct:
    ct = ct.replace(a, b)
    n += 1
if a2 in ct:
    ct = ct.replace(a2, b2)
    n += 1
c.write_text(ct, encoding="utf-8")
print("clipdrop replacements", n)
