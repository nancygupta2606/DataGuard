-- Phase 1: staging entities, raw landing zone and remaining audit tables.

-- RAW: immutable, schema-flexible landing zone (JSONB keeps unknown/new columns).
CREATE TABLE IF NOT EXISTS raw.landing (
    id          BIGSERIAL PRIMARY KEY,
    source_name TEXT        NOT NULL,
    file_name   TEXT        NOT NULL,
    run_id      UUID        NOT NULL REFERENCES audit.pipeline_runs(run_id),
    payload     JSONB       NOT NULL,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- STAGING: typed, deduplicated by business key (upserts make loads idempotent).
CREATE TABLE IF NOT EXISTS staging.customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT,
    email       TEXT,
    country     TEXT,
    updated_at  TIMESTAMPTZ NOT NULL,
    _run_id     UUID NOT NULL,
    _loaded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staging.products (
    product_id  TEXT PRIMARY KEY,
    name        TEXT,
    category    TEXT,
    price       NUMERIC(12, 2),
    updated_at  TIMESTAMPTZ NOT NULL,
    _run_id     UUID NOT NULL,
    _loaded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staging.orders (
    order_id    TEXT PRIMARY KEY,
    customer_id TEXT,
    product_id  TEXT,
    quantity    INTEGER,
    unit_price  NUMERIC(12, 2),
    order_ts    TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ NOT NULL,
    _run_id     UUID NOT NULL,
    _loaded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staging.payments (
    payment_id  TEXT PRIMARY KEY,
    order_id    TEXT,
    amount      NUMERIC(12, 2),
    paid_at     TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ NOT NULL,
    _run_id     UUID NOT NULL,
    _loaded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- AUDIT
CREATE TABLE IF NOT EXISTS audit.ingested_files (
    source_name TEXT NOT NULL,
    file_hash   TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    run_id      UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    row_count   INTEGER NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_name, file_hash)
);

CREATE TABLE IF NOT EXISTS audit.schema_versions (
    source_name TEXT NOT NULL,
    version     INTEGER NOT NULL,
    columns     JSONB NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_name, version)
);

CREATE TABLE IF NOT EXISTS audit.quality_results (
    id           BIGSERIAL PRIMARY KEY,
    run_id       UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    dataset      TEXT NOT NULL,
    rule_name    TEXT NOT NULL,
    rule_type    TEXT NOT NULL,
    severity     TEXT NOT NULL,
    passed       BOOLEAN NOT NULL,
    rows_checked BIGINT NOT NULL,
    rows_failed  BIGINT NOT NULL,
    checked_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit.quality_violations (
    id          BIGSERIAL PRIMARY KEY,
    result_id   BIGINT NOT NULL REFERENCES audit.quality_results(id),
    record_key  TEXT NOT NULL,
    details     JSONB
);

CREATE TABLE IF NOT EXISTS audit.reconciliation_results (
    id            BIGSERIAL PRIMARY KEY,
    run_id        UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    dataset       TEXT NOT NULL,
    check_type    TEXT NOT NULL,   -- count | sum | checksum
    source_value  NUMERIC,
    target_value  NUMERIC,
    matched       BOOLEAN NOT NULL,
    evidence      JSONB,
    checked_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit.metrics (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID REFERENCES audit.pipeline_runs(run_id),
    dataset     TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value       NUMERIC NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit.incidents (
    incident_id  BIGSERIAL PRIMARY KEY,
    dataset      TEXT NOT NULL,
    category     TEXT NOT NULL,   -- quality | freshness | volume | reconciliation | failure | schema
    severity     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
    title        TEXT NOT NULL,
    details      JSONB,
    run_id       UUID REFERENCES audit.pipeline_runs(run_id),
    opened_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ
);
