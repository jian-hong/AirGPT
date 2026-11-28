# Onboarding

AirGPT is the free local app in the Netie bundle, next to DMS and OpenVault.
These steps get all three running on one computer. No account token is typed in.
The wizard creates one and stores it. It is never shown.

## Install on this computer

Install Python 3.11 or newer. In the AirGPT folder run:

```
pip install -r requirements.lock
```

On Windows that also installs pywin32. On Linux and macOS that line is skipped.
Linux builds the `evdev` package for the keyboard hook, so a C compiler and
Python headers must be present (`gcc` and `python3-dev`, or the equivalent).

## Create the local service token

Run:

```
python -m bundle.launch --check
```

Or open the first-run page:

```
python -m bundle.launch --ui
```

Then browse to http://127.0.0.1:8764/ and press **Create local service token**.

The token is stored in the OS keychain when that works (macOS Keychain, Windows
Credential Locker, or the Linux Secret Service). A file with mode 0600 is also
written so DMS and OpenVault, which are separate programs, can read the same
value. The page and the terminal do not print the token.

You can point the file at another path with `NETIE_TOKEN_FILE`. To force the
file and skip the keychain, set `NETIE_TOKEN_STORE=file`.

## Start AirGPT, DMS, and OpenVault

Run:

```
python -m bundle.launch --up
```

- AirGPT listens on http://127.0.0.1:8765.
- DMS (Cortex with `PACK=dms`) listens on http://127.0.0.1:8011 when you set
  `DMS_CMD` or `DMS_ARGV`. `DMS_ROOT` or `CORTEX_ROOT` records the checkout.
  The launcher does not guess a start command.
- OpenVault listens on http://127.0.0.1:5000 when you set `OPENVAULT_CMD` or
  `OPENVAULT_ARGV`. `OPENVAULT_ROOT` records the checkout.

Stop a detached start with `python -m bundle.launch --stop`.

Docker, from the AirGPT folder, after `--check` has written the token file:

```
docker compose -f bundle/docker-compose.yml up --build
```

That starts AirGPT only, bound to 127.0.0.1:8765, with the tunnel off.
When you have DMS and OpenVault images:

```
docker compose -f bundle/docker-compose.yml --profile siblings up
```

Set `DMS_IMAGE` and `OPENVAULT_IMAGE` to those images. The compose file mounts
`NETIE_TOKEN_FILE`. It does not contain the token.

## Set a passcode on this computer

Open http://127.0.0.1:8765. In Settings, then Profile, set a host passcode
before any phone joins.

## Leave the public tunnel off

The tunnel stays off. In Connected Devices, press the tunnel button only after
you read the warning, or set `AIRGPT_TUNNEL=1` before start. That publishes
this computer on the internet through cloudflared or another provider. Anyone
with the URL can reach the sign-in page.

## Open the LAN only if you mean to

The default bind is 127.0.0.1. Set `AIRGPT_BIND=0.0.0.0` only when other
machines on your network should connect. Startup prints a warning.
