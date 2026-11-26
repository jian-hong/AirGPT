"""Start AirGPT from any checkout on its own port and data dir, for parallel dev.

  python3 run_app.py --root /path/to/checkout --port 8771 --data /path/to/datadir

Product code is untouched: the port and the free-tier AI rate limit (1 request a
minute without keys) are set on the imported module, for this process only.
"""
import argparse, os, sys
ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--port", type=int, required=True); ap.add_argument("--data", required=True)
a = ap.parse_args()
os.makedirs(a.data, exist_ok=True)
os.environ["AIRGPT_DATA_DIR"] = a.data
os.environ["AIRGPT_NO_BROWSER"] = "1"
os.chdir(a.root); sys.path.insert(0, a.root)
import clipdrop
clipdrop.PORT = a.port
clipdrop.AI_RATE_LIMIT_SEC = 0
clipdrop.main()
