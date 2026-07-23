"""Thin wrapper — canonical tests live in OpenIDE/tests/."""

from OpenIDE.tests.test_openide_terminal_allowlist import (  # noqa: F401
    test_git_mutating_allowlisted,
    test_git_force_push_blocked,
    test_gh_pr_allowlisted,
    test_shell_metachar_blocked,
)
