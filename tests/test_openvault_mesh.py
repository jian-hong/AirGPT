"""Thin wrapper — canonical tests live in OpenIDE/tests."""

from OpenIDE.tests.test_openvault_bridge import (  # noqa: F401
    test_ensure_local_config,
    test_handshake_live_or_skip,
    test_looks_like_openvault,
    test_mesh_build_check_tree_only,
    test_resolve_openvault_root_prefers_env,
)
