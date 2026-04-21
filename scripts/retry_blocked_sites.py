"""Run the browser-backed blocked-site retry command."""

from __future__ import annotations

import sys

from app.cli import main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv = [sys.argv[0], "retry-blocked-sites"]
    main()
