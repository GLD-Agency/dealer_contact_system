"""Query the total number of contacts in the configured source table."""

from __future__ import annotations

import sys
from pathlib import Path


# Add the project root so the script can import the local app package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.bigquery_client import get_bigquery_client
from app.config import get_settings


def main() -> None:
    """Fetch and print the total contact count."""

    settings = get_settings()
    client = get_bigquery_client()
    query = f"""
    SELECT COUNT(*) AS total_contacts
    FROM `{settings.source_contact_table_fqn}`
    """
    results = list(client.query(query).result())
    print(f"Source table: {settings.source_contact_table_fqn}")
    print(f"Total contacts: {results[0].total_contacts}")


if __name__ == "__main__":
    main()
