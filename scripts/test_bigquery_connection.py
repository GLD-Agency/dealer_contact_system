"""Test the BigQuery connection for the configured project."""

from __future__ import annotations

import sys
from pathlib import Path


# Add the project root so the script can import the local app package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.bigquery_client import get_bigquery_client
from app.config import get_settings


def main() -> None:
    """Run a lightweight query to confirm BigQuery connectivity."""

    settings = get_settings()
    client = get_bigquery_client()
    query = "SELECT 1 AS connection_ok"
    results = list(client.query(query).result())
    print(f"Connected to BigQuery project: {settings.bigquery_project_id}")
    print(f"Dataset configured: {settings.bigquery_dataset}")
    print(f"Source table configured: {settings.source_contact_table_fqn}")
    print(f"Test query result: {results[0].connection_ok}")


if __name__ == "__main__":
    main()
