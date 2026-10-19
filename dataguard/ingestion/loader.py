"""Idempotent, incremental file ingestion.

Guarantees
----------
* **Run twice -> no duplicates.** Each file is fingerprinted (SHA-256); already-ingested
  files are skipped. Staging writes are upserts keyed on the business key.
* **Fail halfway -> safe resume.** Every file is committed in its own transaction
  (raw + staging + audit record together). A rerun skips committed files and retries
  the rest; a failed file leaves no partial rows.
* **Late data handled.** Upserts only overwrite when the incoming ``updated_at`` is newer,
  so an older, late-arriving file never clobbers fresher data.
"""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from dataguard.common.logging import get_logger
from dataguard.ingestion.config import SourceConfig

log = get_logger(__name__)


@dataclass
class IngestResult:
    run_id: uuid.UUID
    source: str
    files_loaded: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    rows_in: int = 0
    rows_out: int = 0
    duplicates_in_batch: int = 0
    extra_columns: set[str] = field(default_factory=set)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_rows(path: Path) -> tuple[list[dict], list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [{k: (v if v != "" else None) for k, v in r.items()} for r in reader]
        return rows, list(reader.fieldnames or [])


def dedupe_latest(rows: list[dict], key: str) -> tuple[list[dict], int]:
    """Keep one row per key (latest updated_at). Returns (rows, duplicates_removed)."""
    best: dict[str, dict] = {}
    for r in rows:
        k = r[key]
        if k not in best or (r["updated_at"] or "") >= (best[k]["updated_at"] or ""):
            best[k] = r
    return list(best.values()), len(rows) - len(best)


def build_upsert_sql(cfg: SourceConfig) -> str:
    cols = cfg.columns
    insert_cols = ", ".join([*cols, "_run_id"])
    values = ", ".join([*(f":{c}" for c in cols), ":_run_id"])
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in [*cols, "_run_id"] if c != cfg.key
    )
    return (
        f"INSERT INTO {cfg.target} AS t ({insert_cols}) VALUES ({values}) "
        f"ON CONFLICT ({cfg.key}) DO UPDATE SET {updates}, _loaded_at = now() "
        f"WHERE t.updated_at <= EXCLUDED.updated_at"
    )


def _start_run(conn: Connection, run_id: uuid.UUID, pipeline: str) -> None:
    conn.execute(
        text("INSERT INTO audit.pipeline_runs (run_id, pipeline_name, status) "
             "VALUES (:r, :p, 'running')"),
        {"r": run_id, "p": pipeline},
    )


def _finish_run(conn: Connection, res: IngestResult, status: str, err: str | None) -> None:
    conn.execute(
        text("UPDATE audit.pipeline_runs SET status=:s, finished_at=now(), rows_in=:i, "
             "rows_out=:o, error_message=:e WHERE run_id=:r"),
        {"s": status, "i": res.rows_in, "o": res.rows_out, "e": err, "r": res.run_id},
    )


def _load_file(conn: Connection, cfg: SourceConfig, path: Path, digest: str,
               res: IngestResult) -> None:
    rows, header = read_rows(path)
    res.extra_columns |= set(header) - set(cfg.columns)

    if rows:
        conn.execute(
            text("INSERT INTO raw.landing (source_name, file_name, run_id, payload) "
                 "VALUES (:s, :f, :r, CAST(:p AS JSONB))"),
            [{"s": cfg.name, "f": path.name, "r": res.run_id, "p": json.dumps(r)}
             for r in rows],
        )

    unique, dupes = dedupe_latest(rows, cfg.key)
    params = [{**{c: r.get(c) for c in cfg.columns}, "_run_id": res.run_id} for r in unique]
    if params:
        conn.execute(text(build_upsert_sql(cfg)), params)

    conn.execute(
        text("INSERT INTO audit.ingested_files (source_name, file_hash, file_name, run_id, "
             "row_count) VALUES (:s, :h, :f, :r, :n)"),
        {"s": cfg.name, "h": digest, "f": path.name, "r": res.run_id, "n": len(rows)},
    )
    res.rows_in += len(rows)
    res.rows_out += len(unique)
    res.duplicates_in_batch += dupes


def _update_checkpoint(conn: Connection, cfg: SourceConfig, run_id: uuid.UUID) -> None:
    conn.execute(
        text(f"""
            INSERT INTO audit.checkpoints (source_name, watermark, last_run_id)
            SELECT :s, max(updated_at), :r FROM {cfg.target} HAVING max(updated_at) IS NOT NULL
            ON CONFLICT (source_name) DO UPDATE
              SET watermark = GREATEST(audit.checkpoints.watermark, EXCLUDED.watermark),
                  last_run_id = EXCLUDED.last_run_id, updated_at = now()
        """),
        {"s": cfg.name, "r": run_id},
    )


def ingest_source(engine: Engine, cfg: SourceConfig, base_dir: Path = Path(".")) -> IngestResult:
    res = IngestResult(run_id=uuid.uuid4(), source=cfg.name)
    with engine.begin() as conn:
        _start_run(conn, res.run_id, f"ingest_{cfg.name}")

    files = sorted((base_dir / cfg.path).glob(cfg.pattern))
    try:
        for path in files:
            digest = file_hash(path)
            with engine.begin() as conn:  # one transaction per file = checkpoint
                seen = conn.execute(
                    text("SELECT 1 FROM audit.ingested_files "
                         "WHERE source_name=:s AND file_hash=:h"),
                    {"s": cfg.name, "h": digest},
                ).first()
                if seen:
                    res.files_skipped.append(path.name)
                    continue
                _load_file(conn, cfg, path, digest, res)
                res.files_loaded.append(path.name)
            log.info("file_ingested", source=cfg.name, file=path.name, run_id=str(res.run_id))

        with engine.begin() as conn:
            _update_checkpoint(conn, cfg, res.run_id)
            _finish_run(conn, res, "success", None)
    except Exception as exc:
        with engine.begin() as conn:
            status = "partial" if res.files_loaded else "failed"
            _finish_run(conn, res, status, str(exc)[:2000])
        log.error("ingest_failed", source=cfg.name, run_id=str(res.run_id), error=str(exc))
        raise

    log.info("ingest_complete", source=cfg.name, run_id=str(res.run_id),
             loaded=len(res.files_loaded), skipped=len(res.files_skipped),
             rows_in=res.rows_in, rows_out=res.rows_out,
             extra_columns=sorted(res.extra_columns))
    return res
