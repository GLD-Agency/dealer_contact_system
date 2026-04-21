"""Print a read-only source and canonical table report."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.cli import main


if __name__ == "__main__":
    sys.argv = [sys.argv[0], "report"]
    main()
