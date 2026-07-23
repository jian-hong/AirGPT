#!/bin/bash
# scroll-world video chain runner (Windows Git Bash / bash 3.2 safe)
# Usage:
#   bash run_chain.sh dive <name>      one dive clip from work/stills/still_<name>.png
#   bash run_chain.sh dives            all six dives (concurrent)
#   bash run_chain.sh frames           extract seam frames from rendered dives
#   bash run_chain.sh conn <i>         one connector (i = 1..5)
#   bash run_chain.sh conns            all five connectors (concurrent)
#   bash run_chain.sh encode           encode everything into ../assets/vid/
# Model via env: VMODEL=seedance_2_0 | seedance_2_0_mini | kling3_0  (default mini = draft tier)

set -u
WORK="$(cd "$(dirname "$0")" && pwd)"
ASSETS="$WORK/../assets"
FFMPEG="/c/Users/OOIJIA~1/AppData/Local/Temp/claude/D--AirGPT/48c787a5-ac58-4599-8ae6-190e5afbeb32/scratchpad/ffmpeg-btbn/ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe"
NAMES="desk bridge vault agents tower hero"
VMODEL="${VMODEL:-seedance_2_0_mini}"

case "$VMODEL" in
  kling3_0)          VOPTS="--mode std --sound off";        DIVE_DUR=10; CONN_DUR=5 ;;
  seedance_2_0_mini) VOPTS="--mode std --resolution 720p";  DIVE_DUR=8;  CONN_DUR=5 ;;
  *)                 VOPTS="--mode std --resolution 1080p"; DIVE_DUR=8;  CONN_DUR=5 ;;
esac

json_url() { python -c "import json,sys; d=json.load(open(sys.argv[1])); d=d[0] if isinstance(d,list) else d; print(d.get('result_url') or '')" "$1" 2>/dev/null; }

gen_dive() { # name
  higgsfield generate create "$VMODEL" --prompt "$(cat "$WORK/prompts/dive_$1.txt")" \
    --start-image "$WORK/stills/still_$1.png" \
    $VOPTS --aspect_ratio 16:9 --duration "$DIVE_DUR" \
    --wait --wait-timeout 20m --json > "$WORK/dive_$1.json" 2> "$WORK/dive_$1.err"
  url=$(json_url "$WORK/dive_$1.json")
  [ -n "$url" ] && curl -fsSL "$url" -o "$WORK/dive_$1.mp4" && echo "dive $1 OK" || { echo "dive $1 FAIL"; tail -2 "$WORK/dive_$1.err"; }
}

gen_conn() { # i startPng endPng
  higgsfield generate create "$VMODEL" --prompt "$(cat "$WORK/prompts/conn_$1.txt")" \
    --start-image "$2" --end-image "$3" \
    $VOPTS --aspect_ratio 16:9 --duration "$CONN_DUR" \
    --wait --wait-timeout 20m --json > "$WORK/conn_$1.json" 2> "$WORK/conn_$1.err"
  url=$(json_url "$WORK/conn_$1.json")
  [ -n "$url" ] && curl -fsSL "$url" -o "$WORK/conn_$1.mp4" && echo "conn $1 OK" || { echo "conn $1 FAIL"; tail -2 "$WORK/conn_$1.err"; }
}

enc()  { "$FFMPEG" -v error -y -i "$1" -an -vf "unsharp=5:5:0.8:5:5:0.0" -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -g 8 -keyint_min 8 -sc_threshold 0 -movflags +faststart "$2" && echo "enc $(basename "$2")"; }

case "${1:-}" in
  dive)  gen_dive "$2" ;;
  dives) for n in $NAMES; do gen_dive "$n" & done; wait; echo "ALL DIVES DONE" ;;
  frames)
    for n in $NAMES; do
      "$FFMPEG" -v error -y -ss 0 -i "$WORK/dive_$n.mp4" -frames:v 1 -q:v 2 "$WORK/first_$n.png"
      "$FFMPEG" -v error -y -sseof -0.15 -i "$WORK/dive_$n.mp4" -frames:v 1 -q:v 2 "$WORK/last_$n.png"
    done; echo "FRAMES DONE"; ls "$WORK"/first_*.png "$WORK"/last_*.png | wc -l ;;
  conn)
    set -- $NAMES; arr=("$@"); i="$2"
    gen_conn "$i" "$WORK/last_${arr[$((i-1))]}.png" "$WORK/first_${arr[$i]}.png" ;;
  conns)
    set -- $NAMES; prev=""; i=0
    for n in "$@"; do
      if [ -n "$prev" ]; then i=$((i+1)); gen_conn "$i" "$WORK/last_$prev.png" "$WORK/first_$n.png" & fi
      prev="$n"
    done; wait; echo "ALL CONNECTORS DONE" ;;
  encode)
    mkdir -p "$ASSETS/vid"
    for n in $NAMES; do [ -f "$WORK/dive_$n.mp4" ] && enc "$WORK/dive_$n.mp4" "$ASSETS/vid/$n.mp4"; done
    i=0; for f in "$WORK"/conn_*.mp4; do [ -f "$f" ] || continue; i=$((i+1)); enc "$f" "$ASSETS/vid/conn$i.mp4"; done
    echo "ENCODE DONE" ;;
  *) echo "usage: run_chain.sh dive <name> | dives | frames | conn <i> | conns | encode" ;;
esac
