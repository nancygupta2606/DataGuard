"""Simulated source systems (CRM, products, orders, finance) with fault injection.

Usage:
    python -m simulators.generate --out data/landing --batch 2026-10-19 \
        --faults orphan_customer,negative_quantity
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from faker import Faker

FAULTS = {
    "null_email",          # completeness
    "duplicate_order",     # uniqueness
    "orphan_customer",     # referential integrity
    "negative_quantity",   # business constraint
    "new_column",          # schema drift
    "revenue_mismatch",    # reconciliation: payment != order total
    "volume_drop",         # observability: ~90% fewer orders
    "late_data",           # freshness: timestamps from 2 days ago
}


@dataclass
class Batch:
    customers: list[dict] = field(default_factory=list)
    products: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)


def generate_batch(
    batch_date: datetime,
    n_customers: int = 200,
    n_products: int = 50,
    n_orders: int = 1000,
    faults: set[str] | None = None,
    seed: int = 42,
) -> Batch:
    faults = faults or set()
    unknown = faults - FAULTS
    if unknown:
        raise ValueError(f"Unknown faults: {sorted(unknown)}")

    rng = random.Random(seed)
    fake = Faker()
    Faker.seed(seed)
    ts = batch_date - timedelta(days=2) if "late_data" in faults else batch_date
    stamp = lambda: (ts + timedelta(seconds=rng.randint(0, 86_399))).isoformat()  # noqa: E731
    tag = batch_date.strftime("%Y%m%d")

    b = Batch()
    for i in range(n_customers):
        b.customers.append({
            "customer_id": f"C{i:05d}",
            "name": fake.name(),
            "email": None if "null_email" in faults and i % 10 == 0 else fake.email(),
            "country": fake.country_code(),
            "updated_at": stamp(),
        })
    for i in range(n_products):
        b.products.append({
            "product_id": f"P{i:04d}",
            "name": fake.word().title(),
            "category": rng.choice(["electronics", "home", "apparel", "books"]),
            "price": round(rng.uniform(5, 500), 2),
            "updated_at": stamp(),
        })

    if "volume_drop" in faults:
        n_orders = max(1, n_orders // 10)
    for i in range(n_orders):
        product = rng.choice(b.products)
        qty = rng.randint(1, 5)
        cust = rng.choice(b.customers)["customer_id"]
        if "orphan_customer" in faults and i % 50 == 0:
            cust = "C99999"
        if "negative_quantity" in faults and i % 40 == 0:
            qty = -qty
        order = {
            "order_id": f"O{tag}-{i:06d}",
            "customer_id": cust,
            "product_id": product["product_id"],
            "quantity": qty,
            "unit_price": product["price"],
            "order_ts": stamp(),
            "updated_at": stamp(),
        }
        if "new_column" in faults:
            order["discount_code"] = rng.choice([None, "SAVE10", "VIP"])
        b.orders.append(order)

        amount = round(qty * product["price"], 2)
        if "revenue_mismatch" in faults and i % 25 == 0:
            amount = round(amount * 0.9, 2)
        b.payments.append({
            "payment_id": f"PAY{tag}-{i:06d}",
            "order_id": order["order_id"],
            "amount": amount,
            "paid_at": order["order_ts"],
            "updated_at": order["updated_at"],
        })

    if "duplicate_order" in faults:
        b.orders.extend(dict(o) for o in b.orders[:20])
    return b


SOURCE_FILES = {"crm": "customers", "products": "products", "orders": "orders",
                "finance": "payments"}


def write_batch(batch: Batch, out_dir: Path, batch_date: datetime) -> list[Path]:
    written = []
    for source, attr in SOURCE_FILES.items():
        rows = getattr(batch, attr)
        target = out_dir / source / f"{attr}_{batch_date:%Y%m%d}.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(dict.fromkeys(k for r in rows for k in r))
        with target.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        written.append(target)
    return written


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="data/landing")
    p.add_argument("--batch", default=datetime.now(UTC).strftime("%Y-%m-%d"))
    p.add_argument("--orders", type=int, default=1000)
    p.add_argument("--faults", default="", help=f"comma list of {sorted(FAULTS)}")
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    date = datetime.strptime(a.batch, "%Y-%m-%d").replace(tzinfo=UTC)
    faults = {f for f in a.faults.split(",") if f}
    batch = generate_batch(date, n_orders=a.orders, faults=faults, seed=a.seed)
    for path in write_batch(batch, Path(a.out), date):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
