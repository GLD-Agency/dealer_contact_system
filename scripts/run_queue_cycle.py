"""Helper entry point for one queue-driven pipeline cycle."""

from __future__ import annotations

import sys

from app.cli import main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("run-queue-cycle")
    main()
