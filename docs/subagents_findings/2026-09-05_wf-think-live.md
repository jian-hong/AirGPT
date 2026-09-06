# keywords
workflow, think, tool_detail, wf_tool_calls, :8011 reload, :8765, deep_research, litellm

# main_idea
Old Background cards had zero `wf_tool_calls` because the live engine predates think recording and LLM auth failed with empty tools. Same `agent_task.py` via `netie`. Reload `:8011` only. New `deep_research` `wf_a563c9a4cb1d` shows four `think` rows on GET `:8765 /api/workflows/tasks`. Cost ceiling 0.2 MYR aborts with no traces; use >=5.

# analog
No OpenManus clone. Cortex workflow_runner + store.

# nearness
`tests/test_workflow_runner.py` asserts think+web_search on stubbed smoothness. Live hops still Anthropic-missing / OpenAI 500 until OV unseal. Do not kill `:8765`.

# verify
```
D:\Cortex\.venv\Scripts\python.exe -m pytest tests/test_workflow_runner.py -q
python -c "import json,urllib.request; d=json.loads(urllib.request.urlopen('http://127.0.0.1:8765/api/workflows/tasks').read()); print([(t.get('id'),[x.get('tool') for p in t.get('phases') or [] for a in p.get('agents') or [] for x in a.get('tool_detail') or []]) for t in (d.get('finished') or [])[:3]])"
```
