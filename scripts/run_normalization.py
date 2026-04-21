"""Run the normalization pipeline from contact_master into canonical tables."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.cli import main


if __name__ == "__main__":
    main()

