# Google Flow runbook — AirGPT scroll-world videos

Project: https://labs.google/fx/tools/flow/project/42df9f93-7138-4857-991a-25dc41ccb77b

Use **one model for all 11 clips** (prefer Veo / Frames-to-Video / Ingredients-to-Video).  
Gold stills are identity locks — camera motion only.

## Stills (upload these)

| Scene | File |
|-------|------|
| desk | `work/stills/still_desk.png` |
| bridge | `work/stills/still_bridge.png` |
| vault | `work/stills/still_vault.png` |
| agents | `work/stills/still_agents.png` |
| tower | `work/stills/still_tower.png` |
| hero | `work/stills/still_hero.png` |

Also mirrored at `Landing/netie-agent/public/airgpt/assets/stills/`.

## Dives (6) — Frames / Ingredients to Video

For each scene: upload matching still → paste `work/prompts/dive_{scene}.txt` verbatim → generate → download as `work/masters/{scene}.mp4`.

Order: desk → bridge → vault → agents → tower → hero.

Reject (delete + redo) if: cuts, morphing, new props/text, palette drift, non-#050505 bg.

## Connectors (5)

| Out | Prompt | Start ref | End ref |
|-----|--------|-----------|---------|
| conn1 | `conn_1.txt` | desk end / still_desk | bridge start / still_bridge |
| conn2 | `conn_2.txt` | bridge | vault |
| conn3 | `conn_3.txt` | vault | agents |
| conn4 | `conn_4.txt` | agents | tower |
| conn5 | `conn_5.txt` | tower | hero |

## Encode + wire

```powershell
cd F:\AirGPT\netie-scroll-world\work
.\encode-web.ps1
```

Then enable `clip` + `connectors` in `netie-agent/components/home/airgpt-scroll-world.tsx`.

## Agent automation note

Cursor’s browser and Playwright cannot attach to a live Chrome cookie DB while Chrome is open.  
Either: (1) sign into Flow in the Cursor browser tab, or (2) close Chrome so the profile can be cloned, then re-run Flow automation.
