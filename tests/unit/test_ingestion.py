from datetime import UTC, datetime
from pathlib import Path

import pytest

from dataguard.ingestion.config import SourceConfig, load_sources
from dataguard.ingestion.loader import build_upsert_sql, dedupe_latest, read_rows
from simulators.generate import generate_batch, write_batch

DATE = datetime(2026, 10, 19, tzinfo=UTC)


def test_clean_batch_has_no_faults():
    b = generate_batch(DATE)
    cust_ids = {c["customer_id"] for c in b.customers}
    assert all(o["customer_id"] in cust_ids for o in b.orders)
    assert all(o["quantity"] > 0 for o in b.orders)
    assert len({o["order_id"] for o in b.orders}) == len(b.orders)


@pytest.mark.parametrize("fault,check", [
    ("orphan_customer", lambda b: any(o["customer_id"] == "C99999" for o in b.orders)),
    ("negative_quantity", lambda b: any(o["quantity"] < 0 for o in b.orders)),
    ("duplicate_order", lambda b: len({o["order_id"] for o in b.orders}) < len(b.orders)),
    ("new_column", lambda b: "discount_code" in b.orders[0]),
    ("volume_drop", lambda b: len(b.orders) == 100),
    ("null_email", lambda b: any(c["email"] is None for c in b.customers)),
])
def test_fault_injection(fault, check):
    assert check(generate_batch(DATE, faults={fault}))


def test_unknown_fault_rejected():
    with pytest.raises(ValueError):
        generate_batch(DATE, faults={"nope"})


def test_generation_is_deterministic():
    assert generate_batch(DATE).orders == generate_batch(DATE).orders


def test_write_and_read_roundtrip(tmp_path: Path):
    write_batch(generate_batch(DATE, n_orders=10), tmp_path, DATE)
    rows, header = read_rows(tmp_path / "orders" / "orders_20261019.csv")
    assert len(rows) == 10 and "order_id" in header


def test_dedupe_keeps_latest():
    rows = [
        {"id": "1", "updated_at": "2026-01-01", "v": "old"},
        {"id": "1", "updated_at": "2026-01-02", "v": "new"},
        {"id": "2", "updated_at": "2026-01-01", "v": "x"},
    ]
    out, removed = dedupe_latest(rows, "id")
    assert removed == 1
    assert {r["v"] for r in out} == {"new", "x"}


def test_upsert_sql_only_overwrites_with_newer_data():
    cfg = load_sources()["orders"]
    sql = build_upsert_sql(cfg)
    assert "ON CONFLICT (order_id)" in sql
    assert "WHERE t.updated_at <= EXCLUDED.updated_at" in sql


def test_config_rejects_unsafe_identifiers():
    with pytest.raises(ValueError):
        SourceConfig(name="x", path=Path("."), pattern="*", target="t; DROP TABLE x",
                     key="id", columns=["id", "updated_at"])
