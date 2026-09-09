# keywords
scheduler, scheduled_work, gh pr, ship_gate, smtp, IMAP, S1, update check, workflow traces, Cortex, Crew, OpenVault

# main_idea
2026-09-05 continuation of /goal: Cortex routine dispatch now runs Crew gh/ship-gate and IMAP/SMTP digest instead of echoing the prompt on the minimal DAG. AirGPT surfaces that work (no host clock, no AirGPT-agent requirement). S1 phone HTTP tests expanded. GET /api/update is honest no_update_server until a signed channel exists. Not download-safe.

# analog
No myopencode/9router/OpenManus/zep vendors. gh+ship_gate live in CortexOS/crew. Mail send lives in Cortex scheduled_work; Crew inbox.py still never sends.

# nearness
Cortex `execution/scheduled_work.py` + `routine_scheduler._dispatch` + `_ov_brief`
(`model=auto`). Live `:8011` gh list is 16 PRs; FreeRoute brief is
`openvault_vault_sealed` until founder `POST /api/vault/unseal`. AirGPT
`:8765` S1 403; artifact GET md/docx/pdf/tex for packaged citation-gate run.
`GET /api/update` honest. EXE unsigned. Do not kill `:8765`.

# verify
```
D:\Cortex\.venv\Scripts\python.exe -m pytest tests/dms/test_scheduled_work.py tests/test_crew/test_connectors_import.py tests/dms/test_routine_composer.py tests/dms/test_routine_scheduler.py -q
python -m pytest tests/test_s1_passcode_posture.py tests/test_idea_to_paper.py tests/test_update_check.py tests/test_workflow_engine.py tests/test_routines_control_honesty.py tests/test_d09_shell_gate.py -q
```
Do not kill `:8765`.
