# AirGPT Business license control plane (optional)
# pip install fastapi uvicorn pydantic
# uvicorn control_plane.app:app --app-dir . --port 8787
#
# Point AirGPT env.local:
#   AIRGPT_API_BASE=http://127.0.0.1:8787
#
# Personal clients work without this server.
