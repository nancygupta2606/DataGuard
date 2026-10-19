import pytest
from sqlalchemy import create_engine, text

from dataguard.common.config import get_settings


@pytest.mark.integration
def test_audit_schema_exists():
    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT schema_name FROM information_schema.schemata"))
        schemas = {r[0] for r in rows}
    assert {"raw", "staging", "curated", "quarantine", "audit"} <= schemas
