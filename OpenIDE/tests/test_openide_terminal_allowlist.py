"""Allowlist coverage for OpenIDE git / gh / Create PR path."""

from __future__ import annotations

from OpenIDE.terminal_pty import _allowed


def test_git_mutating_allowlisted() -> None:
    assert _allowed("git status")
    assert _allowed("git add -A")
    assert _allowed('git commit -m "OpenIDE changes"')
    assert _allowed("git fetch --all --prune")
    assert _allowed("git push origin HEAD")
    assert _allowed("git worktree list")
    assert _allowed("git checkout -b feature/x")


def test_git_force_push_blocked() -> None:
    assert not _allowed("git push --force")
    assert not _allowed("git push -f origin main")


def test_gh_pr_allowlisted() -> None:
    assert _allowed("gh pr create --fill")
    assert _allowed("gh pr status")
    assert _allowed("gh auth status")
    assert not _allowed("gh repo clone x")
    assert not _allowed("gh auth login")


def test_shell_metachar_blocked() -> None:
    assert not _allowed("git status; rm -rf /")
    assert not _allowed("echo hi | cat")
