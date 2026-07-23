"""Modular UI stress checks for AirGPT index.html — zero network required."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"


def section(name: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    print("=== AirGPT UI stress check ===\n")
    html = INDEX.read_text(encoding="utf-8")
    fails = 0

    # 1. Composer / send semantics
    ok = "fromPlaceholder" in html and "placeholder" in html and "async function send()" in html
    fails += not section("send-empty uses placeholder", ok)

    # 2. Project chip width + short ML label
    ok = "MODE_CHIP" in html and "max-width:200px" in html and "Engineering" in html
    fails += not section("project chip fits Engineering / ML short", ok)

    fails += not section("stable QOTD cache", "airgpt_qotd" in html and "pickStableQotd" in html)
    fails += not section("pullGen anti-wipe", "pullGen" in html and "adoptSessionId" in html)
    fails += not section("composer-top phone layout", "composer-top" in html and "composer-row" in html)

    # 3. Required IDs present once
    for eid in ("projectBtn", "projectBtnLabel", "aiSwitchWrap", "settingsBtn", "composerRail", "input", "sendBtn", "attachBtn"):
        n = len(re.findall(rf'id="{eid}"', html))
        fails += not section(f"unique id #{eid}", n == 1, f"count={n}")

    # 4. Layout helpers
    fails += not section("layoutComposerChrome", "function layoutComposerChrome" in html)
    fails += not section("questionOfTheDay", "function questionOfTheDay" in html)
    fails += not section("showProjectFocus", "function showProjectFocus" in html)
    fails += not section("wireEngagementSignals", "function wireEngagementSignals" in html)

    # 5. No leftover removed chrome
    for bad in ("id=\"skuChip\"", "id=\"pill\"", "id=\"adminBtn\"", "Ask about a screenshot"):
        fails += not section(f"removed legacy: {bad[:24]}", bad not in html)

    # 6. Glass / mobile breakpoints
    fails += not section("composer-rail mobile", "composer-rail" in html and "max-width:960px" in html)
    fails += not section("safe-area composer", "safe-area-inset-bottom" in html)
    fails += not section("phone-client attach", "phone-attach" in html)

    # 7. Admin auth headers + no token in URL
    admin = (ROOT / "admin.html").read_text(encoding="utf-8")
    fails += not section("admin X-AirGPT-Token", "X-AirGPT-Token" in admin and "adminFetch" in admin)
    fails += not section("admin open without ?token=", "location.href='/admin'" in html and "?token=" not in html)

    # 8. XSS hygiene — esc() used in project focus + hardened
    fails += not section("esc() in project focus", "esc(label)" in html or "esc(MODE_LABELS" in html)
    fails += not section("esc() quotes hardened", "&quot;" in html and "&#39;" in html)

    # 9. Taste prefs local-only
    fails += not section("local taste key", "airgpt_taste" in html and "resetTastePrefs" in html)

    # 10. Enter-to-send wired
    fails += not section("Enter sends", "e.key==='Enter'" in html and "send()" in html)

    # 11. Placeholder send banlist
    fails += not section("placeholder banlist", "banned=" in html and "fromPlaceholder" in html)

    # 12. Nav / hosting poll hygiene (anti-lag)
    fails += not section("leaveOverlayWorkspace", "function leaveOverlayWorkspace" in html)
    fails += not section("stopCortexCrmPoll", "function stopCortexCrmPoll" in html)
    fails += not section(
        "CRM poll guards sideView",
        "views.includes(sideView)" in html or "!views.includes(sideView)" in html,
    )
    fails += not section(
        "quiet hosting early-return",
        "quiet&&sideView!=='hosting'" in html or 'quiet&&sideView!=="hosting"' in html,
    )

    # 13. Memory rail only on project focus
    fails += not section(
        "openSession hides project rail",
        "Memory rail only on project focus" in html or ("setProjectMode(false)" in html and "window.openSession" in html),
    )
    fails += not section("renderProjectRail on focus", "async function showProjectFocus" in html and "renderProjectRail" in html)

    # 14. Welcome home (not blank chat stub)
    fails += not section("airgptWelcome id", 'id="airgptWelcome"' in html or "id='airgptWelcome'" in html)
    fails += not section("invite-card CTAs", "invite-card" in html and "Try something" in html)
    fails += not section(
        "no blank say-hello stub",
        "No messages in this chat yet — say hello" not in html,
    )

    # 15. OpenIDE Cortex|IDE morph switch + Phase 9 surface
    fails += not section("setOpenIDEView", "function setOpenIDEView" in html)
    fails += not section("openide-view-editor", "openide-view-editor" in html)
    fails += not section("Cortex/Editor toggle", "setOpenIDEView('agents')" in html and "setOpenIDEView('editor')" in html)
    fails += not section("Cortex runs hdr", "openide-runs" in html and "New Cortex" in html or "oide-new-cortex" in html)
    fails += not section("toggleOpenIDECortex", "function toggleOpenIDECortex" in html)
    fails += not section("openideEnsureKeys", "function openideEnsureKeys" in html or "async function openideEnsureKeys" in html)
    fails += not section("continueOpenIDEAgent", "continueOpenIDEAgent" in html)
    fails += not section("openideShowHelp", "openideShowHelp" in html)
    fails += not section("kvEnableOmniRoute", "kvEnableOmniRoute" in html)
    fails += not section("openideGitFetch", "openideGitFetch" in html)
    fails += not section("agent bar Folder/Branch", "oideFolderDd" in html and "oideBranchDd" in html and "oideTierDd" in html)
    fails += not section("IDE↗ open rail", "function openOpenIDERightRail" in html and "function closeOpenIDERightRail" in html)
    fails += not section("Run wires to agent", 'onclick="runOpenIDEAgent()"' in html)
    fails += not section("no Cursor/Cloud hdr select", "openideBackend" not in html)
    fails += not section("no Checkpoint button", "Workspace checkpoint" not in html)
    # 16. OpenForge shell
    fails += not section("forge-shell", "forge-shell" in html and "forge-honesty" in html)

    print(f"\n=== {'PASS' if fails == 0 else 'FAIL'} — {fails} failing sector(s) ===")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
