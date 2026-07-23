"""WiFi connectivity debug — run anytime phone cannot connect."""
from __future__ import annotations

import sys

import wifi_access

if __name__ == "__main__":
    sys.exit(wifi_access.print_report(wifi_access.run_diagnostics()))
