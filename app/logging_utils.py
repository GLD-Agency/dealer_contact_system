"""Logging helpers for the command line pipeline."""

from __future__ import annotations

import logging


def configure_logging() -> None:
    """Configure a consistent logging format for scripts and CLI commands."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for the application."""

    return logging.getLogger(name)

