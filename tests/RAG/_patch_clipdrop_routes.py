from pathlib import Path

p = Path(r"d:\AirGPT\clipdrop.py")
text = p.read_text(encoding="utf-8")
old = '''        if path.startswith("/api/rag/spaces/") and path.endswith("/demo-variant"):
            try:
                from rag import demo_variants

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                name = str(data.get("variant") or data.get("name") or "").strip()
                if not name:
                    return self._json(200, {"ok": True, **demo_variants.resolve_for_space(sid)})
                out = demo_variants.select_variant(sid, name)
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/archive"):'''
new = '''        if path.startswith("/api/rag/spaces/") and path.endswith("/demo-variant"):
            try:
                from rag import demo_variants

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                name = str(data.get("variant") or data.get("name") or "").strip()
                if not name:
                    return self._json(200, {"ok": True, **demo_variants.resolve_for_space(sid)})
                out = demo_variants.select_variant(sid, name)
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/ontology"):
            try:
                from rag import ontology as rag_ontology

                sid = int(path.split("/")[4])
                data = json.loads(self._body().decode() or "{}")
                out = rag_ontology.ontology_for_space(sid, force=bool(data.get("force")))
                if out.get("ok"):
                    out["artifact"] = str(rag_ontology.save_ontology_artifact(sid))
                return self._json(200 if out.get("ok") else 400, out)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path == "/api/rag/reveal-path":
            try:
                from rag import reveal as rag_reveal

                data = json.loads(self._body().decode() or "{}")
                return self._json(200, rag_reveal.reveal_path(str(data.get("path") or "")))
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)[:200]})

        if path.startswith("/api/rag/spaces/") and path.endswith("/archive"):'''
if old not in text:
    raise SystemExit("needle miss")
p.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched")
