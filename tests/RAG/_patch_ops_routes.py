from pathlib import Path

p = Path(r"d:\AirGPT\clipdrop.py")
text = p.read_text(encoding="utf-8")
needle = '        if path == "/api/rag/reveal-path":'
if 'path == "/api/rag/ops/' in text:
    print("ops already present")
else:
    insert = '''        if path == "/api/rag/ops/identify":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                out = ops_amend.identify_employee(
                    str(data.get("path") or ""),
                    str(data.get("ask") or data.get("query") or ""),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/ops/confirm-identity":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                out = ops_amend.confirm_identity(
                    str(data.get("token") or ""),
                    bool(data.get("yes")),
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/ops/propose-amend":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                out = ops_amend.propose_amend(
                    str(data.get("token") or ""),
                    new_salary=float(data["new_salary"]) if data.get("new_salary") is not None else None,
                    increment_pct=float(data["increment_pct"]) if data.get("increment_pct") is not None else None,
                )
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/ops/confirm-amend":
            try:
                from rag import ops_amend

                data = json.loads(self._body().decode() or "{}")
                out = ops_amend.confirm_amend(str(data.get("token") or ""), bool(data.get("yes")))
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

'''
    if needle not in text:
        raise SystemExit("reveal needle miss")
    text = text.replace(needle, insert + needle, 1)
    p.write_text(text, encoding="utf-8")
    print("ops routes added")
