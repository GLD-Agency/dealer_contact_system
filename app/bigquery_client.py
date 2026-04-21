"""Helpers for creating a BigQuery client."""

from __future__ import annotations

from google.cloud import bigquery

from app.config import get_settings


def get_bigquery_client() -> bigquery.Client:
    """Create a BigQuery client using the configured project."""

    settings = get_settings()
    return bigquery.Client(project=settings.bigquery_project_id)

