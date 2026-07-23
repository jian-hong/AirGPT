# Shared Netie account (AirGPT ↔ Space ↔ netie.ai)

## Local SSOT

`%LOCALAPPDATA%\Netie\account.json`

```json
{
  "schema": 1,
  "email": "user@company.com",
  "session_token": "",
  "products": {
    "airgpt": { "linked": true, "sku": "personal" },
    "space": { "linked": true, "sku": "personal", "via": "airgpt_bundle" },
    "web": { "linked": false, "sku": "personal" }
  }
}
```

## AirGPT APIs

- `GET /api/netie/account` — status
- `POST /api/netie/account` — `{ "action": "link"|"login"|"logout", "email", "password?", "product?" }`
- License activate / set email also calls `netie_id.link_local`

Module: [`netie_id.py`](../netie_id.py)

## Netie Space integration

Space should read/write the same `account.json` on first run. Prefer:

1. If file has email → treat as signed-in host identity
2. If `session_token` set → call Space license-api `/v1/me` with Bearer token
3. On Space login success → write `products.space.linked = true` and share `session_token`

## netie.ai website

Login/register should mint the same session used by Space license-api (`/v1/login`). Download pages:

- `/airgpt/download` → AirGPT-Setup (includes Space)
- `/space/download` → Space-only Setup

## Installer

[`installer/AirGPT.iss`](../installer/AirGPT.iss) task `installspace` (checked by default) copies `dist\bundle\NetieSpace` when present. Run [`scripts/bundle_netie_space.ps1`](../scripts/bundle_netie_space.ps1) after publishing Space.
