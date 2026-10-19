-- Layered storage: raw -> staging -> curated, with quarantine and audit.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS curated;
CREATE SCHEMA IF NOT EXISTS quarantine;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.pipeline_runs (
    run_id        UUID PRIMARY KEY,
    pipeline_name TEXT        NOT NULL,
    status        TEXT        NOT NULL CHECK (status IN ('running','success','failed','partial')),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    rows_in       BIGINT,
    rows_out      BIGINT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS audit.checkpoints (
    source_name   TEXT PRIMARY KEY,
    watermark     TIMESTAMPTZ NOT NULL,
    last_run_id   UUID REFERENCES audit.pipeline_runs(run_id),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
