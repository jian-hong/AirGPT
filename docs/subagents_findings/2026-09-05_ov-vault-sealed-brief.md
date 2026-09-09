# keywords
openvault_vault_sealed, scheduled_work, ov_brief, FreeRoute, :5000, :8011, gh_pr_list

# main_idea
Live scheduler gh works. The FreeRoute brief POSTs `/v1/chat/completions` with `model=auto` and gets 403 `openvault_vault_sealed` until the founder unseals. Operator facts stay. Do not invent an unseal. Do not kill :8765.

# analog
Reuse Cortex `OpenVaultAdapter` / Crew loopback (no dummy bearer). Not a second orchestrator.

# nearness
`CortexOS/execution/scheduled_work.py` `_ov_brief`. Live `:5000` healthz ok, chat sealed. AirGPT surfaces Cortex routines.

# verify
```
python -c "import httpx; r=httpx.post('http://127.0.0.1:5000/v1/chat/completions', json={'model':'auto','messages':[{'role':'user','content':'ping'}],'max_tokens':8}, timeout=15); print(r.status_code, r.json().get('error',{}).get('type'))"
```
Expect `403 openvault_vault_sealed`. Unseal is founder `POST /api/vault/unseal`.
