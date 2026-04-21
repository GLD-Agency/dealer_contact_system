"""Convenience entry point for the dealer contact system CLI."""

from __future__ import annotations

import sys


def _print_missing_dependency_help(exc: ModuleNotFoundError) -> None:
    """Print a helpful message when the project venv is not being used."""

    missing_module = getattr(exc, "name", "a required module")
    print(f"Missing dependency: {missing_module}")
    print()
    print("This project should be run from its virtual environment.")
    print("Use one of these commands from the project folder:")
    print(r"  .\.venv\Scripts\python.exe main.py serve-dashboard")
    print(r"  .\.venv\Scripts\python.exe main.py report")
    print()
    print("Or activate the virtual environment first:")
    print(r"  .\.venv\Scripts\Activate.ps1")
    print(r"  python main.py serve-dashboard")
    sys.exit(1)


if __name__ == "__main__":
    try:
        from app.cli import main
    except ModuleNotFoundError as exc:
        _print_missing_dependency_help(exc)
    main()
