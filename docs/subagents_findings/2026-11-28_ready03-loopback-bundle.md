# READY-03 loopback, tunnel off, bundle token

keywords: READY-03, pywin32, 127.0.0.1, cloudflared, AIRGPT_TUNNEL, requirements.lock, pip-audit, bundle token, keyring, 0600, DMS, OpenVault

main_idea: Windows-only pywin32 and a boot-time public tunnel were one install file and one boot function. Split them: marker plus lock file, loopback bind, tunnel only after an explicit warning, token stored and never printed.

## What was true

- `requirements.txt` listed `pywin32>=306` with no marker, so Linux `pip install` failed and CI stayed on Windows only.
- `clipdrop.main` called `_boot_tunnel_threads()` on every start, and `HOST` was `0.0.0.0`.
- `/api/restart-tunnel` started a provider with an empty body. Guests were already blocked by the host-only prefix. The host was not asked to confirm.
- DMS is Cortex with `PACK=dms` on `:8011`. OpenVault is `:5000`. Those checkouts are not in this repo, so the launcher starts them only when `DMS_CMD` or `OPENVAULT_CMD` is set.

## What changed

- `bundle/posture.py` owns the bind and the tunnel flag.
- `bundle/token_store.py` uses keyring, then a mode 0600 file. Callers return `where` and `path`, never the secret.
- `tests/test_ready03_bundle.py` starts three loopback processes and the real HTTP handler. CI job `ready03` runs that file on Ubuntu and Windows and runs `pip-audit`.
