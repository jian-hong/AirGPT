# AirGPT / Netie — Privacy Policy (draft)

> **Not legal advice.** Structure for counsel review (Malaysia PDPA + GDPR-oriented). Effective when VERSION ships.

## Summary

- **Local mode (default):** chat, clipboard, vault, and screenshots stay on your device under the AirGPT `data/` folder.
- **Connected mode (opt-in):** phone tunnel (e.g. Cloudflare) and BYOK model providers only receive what you send after you enable them.
- **We do not train models on your content.**
- **Netie account:** email/session may sync across AirGPT, Netie Space, and netie.ai via a shared local identity file and optional license API.

## Local vs connected

| Mode | What stays local | What may leave the device |
|------|------------------|---------------------------|
| Local | Vault, chats, clipboard history, audit hashes | Nothing by default |
| Tunnel | Same | Encrypted relay for phone↔PC while tunnel is on |
| BYOK | Same | Prompts/files you send to *your* API provider under *your* key |

## Keyboard helpers (optional)

If you enable Copilot-key remap or Win+Space in the installer, a minimal hook inspects only those chords. Keystrokes are not logged, stored, or transmitted. Disable anytime in Settings or uninstall.

## Contact

privacy@netie.ai (placeholder) · https://netie.ai/contact/
