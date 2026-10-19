"""Integration tests for the hard cases: rerun, partial failure, late data."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from dataguard.common.config import get_settings
from dataguard.ingestion.config import load_sources
from dataguard.ingestion.loader import ingest_source
from simulators.generate import generate_batch, write_batch

pytestmark = pytest.mark.integration
DATE = datetime(2026, 10, 19, tzinfo=UTC)


@pytest.fixture
def engine():
    eng = create_engine(get_settings().database_url)
    with eng.begin() as c:
        c.execute(text(
            "TRUNCATE raw.landing, staging.customers, staging.products, staging.orders, "
            "staging.payments, audit.ingested_files, audit.checkpoints, "
            "audit.pipeline_runs CASCADE"))
    yield eng
    eng.dispose()


@pytest.fixture
def orders_cfg(tmp_path: Path):
    cfg = load_sources()["orders"]
    return cfg.model_copy(update={"path": tmp_path / "orders"})


def count(engine, sql):
    with engine.connect() as c:
        return c.execute(text(sql)).scalar_one()


def test_running_twice_creates_no_duplicates(engine, orders_cfg, tmp_path):
    write_batch(generate_batch(DATE, n_orders=100), tmp_path, DATE)
    first = ingest_source(engine, orders_cfg)
    second = ingest_source(engine, orders_cfg)

    assert first.rows_out == 100
    assert second.files_skipped == ["orders_20261019.csv"]
    assert count(engine, "SELECT count(*) FROM staging.orders") == 100
    assert count(engine, "SELECT count(*) FROM raw.landing") == 100


def test_duplicates_within_file_are_collapsed(engine, orders_cfg, tmp_path):
    write_batch(generate_batch(DATE, n_orders=100, faults={"duplicate_order"}), tmp_path, DATE)
    res = ingest_source(engine, orders_cfg)
    assert res.duplicates_in_batch == 20
    assert count(engine, "SELECT count(*) FROM staging.orders") == 100


def test_failure_midway_resumes_without_corruption(engine, orders_cfg, tmp_path):
    d2 = datetime(2026, 10, 20, tzinfo=UTC)
    write_batch(generate_batch(DATE, n_orders=50), tmp_path, DATE)
    write_batch(generate_batch(d2, n_orders=50, seed=7), tmp_path, d2)
    bad = tmp_path / "orders" / "orders_20261020.csv"
    good_content = bad.read_text()
    bad.write_text(good_content.replace("2026-10-20T", "not-a-date-", 1))

    with pytest.raises(DBAPIError):
        ingest_source(engine, orders_cfg)
    assert count(engine, "SELECT count(*) FROM staging.orders") == 50  # file 1 kept, file 2 none
    assert count(engine, "SELECT status FROM audit.pipeline_runs") == "partial"

    bad.write_text(good_content)  # source fixed, rerun
    res = ingest_source(engine, orders_cfg)
    assert res.files_skipped == ["orders_20261019.csv"]
    assert count(engine, "SELECT count(*) FROM staging.orders") == 100


def test_late_older_data_does_not_overwrite_newer(engine, orders_cfg, tmp_path):
    write_batch(generate_batch(DATE, n_orders=10), tmp_path, DATE)
    ingest_source(engine, orders_cfg)
    before = count(engine, "SELECT max(updated_at) FROM staging.orders")

    late = tmp_path / "late"
    write_batch(generate_batch(DATE, n_orders=10, faults={"late_data"}), late, DATE)
    (late / "orders" / "orders_20261019.csv").rename(
        tmp_path / "orders" / "orders_20261019_late.csv")
    ingest_source(engine, orders_cfg)

    assert count(engine, "SELECT max(updated_at) FROM staging.orders") == before
    assert count(engine, "SELECT count(*) FROM audit.ingested_files") == 2


def test_new_column_detected_and_preserved_in_raw(engine, orders_cfg, tmp_path):
    write_batch(generate_batch(DATE, n_orders=10, faults={"new_column"}), tmp_path, DATE)
    res = ingest_source(engine, orders_cfg)
    assert res.extra_columns == {"discount_code"}
    assert count(engine, "SELECT count(*) FROM raw.landing WHERE payload ? 'discount_code'") == 10
