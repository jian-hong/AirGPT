"""Quick regression checks for the reality-check pass."""
from agent_runtime import _parse_tool_call
from terminal_pty import _allowed
from openforge_chip import status

nested = '{"tool":"fs_patch","params":{"path":"a.py","old":"x","new":"y\\nz"}}'
call = _parse_tool_call(nested)
assert call and call["tool"] == "fs_patch" and call["params"]["path"] == "a.py", call

assert _allowed("git status")
assert _allowed("git diff -- README.md")
assert not _allowed('python -c "print(1)"')
assert not _allowed("git status; echo hi")
assert not _allowed("npm install && evil")
assert _allowed("pytest")

st = status()
assert "honesty" in st and "ngspice" in st
print("ALL UNIT OK", st.get("honesty"))
