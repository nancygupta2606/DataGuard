# DataGuard

A data reliability platform: quality checks, pipeline orchestration, SLA monitoring,
source-to-target reconciliation, a FastAPI service and analytics reporting.

## Quick start (Phase 0)
```powershell
copy .env.example .env
docker compose up -d            # Postgres with raw/staging/curated/quarantine/audit schemas
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest -m "not integration"     # unit tests
pytest                          # all tests (needs Postgres running)
```

## Roadmap
- [x] Phase 0 – Setup
- [ ] Phase 1 – Core platform (ingestion, quality, reconciliation)
- [ ] Phase 2 – Airflow, observability, CI/CD
- [ ] Phase 3 – FastAPI + PySpark + benchmarks
- [ ] Phase 4 – Power BI + demo
- [ ] Phase 5 – AI layer
