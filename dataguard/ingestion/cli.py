"""CLI: python -m dataguard.ingestion.cli [--source orders]"""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine

from dataguard.common.config import get_settings
from dataguard.common.logging import configure_logging
from dataguard.ingestion.config import load_sources
from dataguard.ingestion.loader import ingest_source

# Parents before children so referential checks later see complete data.
ORDER = ["crm", "products", "orders", "finance"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", help="single source to ingest (default: all)")
    p.add_argument("--config", default="config/sources.yml")
    a = p.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    sources = load_sources(a.config)
    names = [a.source] if a.source else [n for n in ORDER if n in sources]
    for name in names:
        ingest_source(engine, sources[name])


if __name__ == "__main__":
    main()
