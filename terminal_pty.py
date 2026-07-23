"""Compatibility shim — OpenIDE terminal lives in OpenIDE.terminal_pty."""
from OpenIDE.terminal_pty import *  # noqa: F401,F403
from OpenIDE.terminal_pty import (  # noqa: F401
    ALLOWED_BINARIES,
    ALLOWED_GIT_SUB,
    _allowed,
    _argv,
    exec_in_session,
    read_session,
    run_command,
    start_session,
)
