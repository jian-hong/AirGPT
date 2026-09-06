# keywords
research artifact, idea-to-paper, stage, think traces, OpenForge, ship-gate, package_run, not one lucky run

# main_idea
D11 leftover is HTTP + measurable stages across more than one packaged run. Live `:8765` now serves three citation-gate packages (014649 / 112219 / 183237). Stub 289-char md was leftover `paper.md`; `package_run` rebuilds long md from tex. Cortex `agent_task` records `think` per step; AirGPT `finish_run` keeps those steps so Background cards can show them. OpenForge 3d is Crew ship-gate, not a second orchestrator.

# analog
No paper clone. No myopencode/OpenManus workflow clone. OpenForge stays in the Crew catalog.

# nearness
Handler GET `/api/research/artifact` + `/api/research/runs` `stage`. Live 200 for three ids. Constructor workflow history still has empty `tool_detail` on old Deep research cards. OV vault sealed. Unsigned EXE.

# verify
```
python -m pytest tests/test_idea_to_paper.py tests/test_workflow_engine.py tests/test_cortex_agent_loop.py tests/test_s1_passcode_posture.py tests/test_paper_export.py -q
# live, do not kill :8765
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8765/api/research/artifact?id=20260828_014649-a-local-citation-gate-should-dro&name=paper.md').status)"
```
Do not close #73/#74 from the implementer session.
