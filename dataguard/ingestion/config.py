"""Typed loading of config/sources.yml."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")


class SourceConfig(BaseModel):
    name: str
    path: Path
    pattern: str
    target: str
    key: str
    columns: list[str]

    # Identifiers are interpolated into SQL, so restrict them to safe names.
    @field_validator("target", "key")
    @classmethod
    def _safe_ident(cls, v: str) -> str:
        if not _IDENT.match(v):
            raise ValueError(f"unsafe SQL identifier: {v!r}")
        return v

    @field_validator("columns")
    @classmethod
    def _safe_columns(cls, cols: list[str]) -> list[str]:
        for c in cols:
            cls._safe_ident(c)
        if "updated_at" not in cols:
            raise ValueError("columns must include updated_at")
        return cols


def load_sources(path: str | Path = "config/sources.yml") -> dict[str, SourceConfig]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {name: SourceConfig(name=name, **cfg) for name, cfg in raw["sources"].items()}
