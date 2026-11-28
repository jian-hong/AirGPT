---
status: accepted
date: 2026-11-28
accepted: 2026-11-28
decision-makers: READY-03
---

# DR-0008 - AirGPT listens on loopback and the public tunnel is off

## Context and Problem Statement

AirGPT bound `0.0.0.0:8765` and started a public cloudflared tunnel during
boot. `requirements.txt` required `pywin32`, so a Linux or macOS install
could not finish. A stranger who cloned the repo got a process on every
interface plus a URL on the internet, before any passcode step.

## Considered Options

- **A. Keep the public default and document it.** Rejected. The warning
  after the tunnel is already up does not undo the exposure.
- **B. Remove the tunnel.** Rejected. Phones on another network still need
  an explicit opt-in.
- **C. Loopback by default, tunnel off, opt-in prints a warning.** Chosen.

## Decision Outcome

1. `AIRGPT_BIND` defaults to `127.0.0.1`. `0.0.0.0` is an explicit LAN opt-in
   and startup prints `BIND_ALL_WARNING`.
2. The public tunnel does not start unless `AIRGPT_TUNNEL` is `1`, `true`,
   `yes`, or `on`, or the host posts `confirm_public: true` to
   `/api/restart-tunnel`. The response and the button carry
   `TUNNEL_OPT_IN_WARNING`.
3. `pywin32` stays in the lock file with `sys_platform == "win32"`.
   `requirements.lock` is the pinned install. CI runs `pip-audit`.
4. The bundle launcher stores one local service token in the OS keychain
   when that works, and in a mode 0600 file so DMS and OpenVault can read
   it. The token is never printed.

A signed installer is still not download-safe. This decision does not
claim that.
