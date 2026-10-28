"""Analytics layer: dbt-style SQL models materialised as views.

`models/*.sql` are plain SELECTs with a few macros:

- ``{{ ref("model") }}``          another model (also defines build order)
- ``{{ day("col") }}``            UTC calendar day of a timestamp
- ``{{ ms_between("a", "b") }}``  milliseconds from b to a
- ``{{ json_num("col", "k1", "k2") }}``  numeric value at col.k1.k2 in a JSON column

Macros render per SQL dialect, so the same models run on Postgres (production)
and SQLite (local dev/tests). `build()` drops and recreates every view in
dependency order; it runs on API startup and via ``python -m voix_api.analytics``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from graphlib import TopologicalSorter
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

MODELS_DIR = Path(__file__).parent / "models"
_MACRO = re.compile(r"\{\{\s*(\w+)\(([^)]*)\)\s*\}\}")
_ARG = re.compile(r'"([^"]*)"')


def _day(dialect: str, col: str) -> str:
    return f"CAST(({col} AT TIME ZONE 'UTC') AS DATE)" if dialect == "postgresql" else f"date({col})"


def _ms_between(dialect: str, a: str, b: str) -> str:
    if dialect == "postgresql":
        return f"CAST(EXTRACT(EPOCH FROM ({a} - {b})) * 1000 AS DOUBLE PRECISION)"
    return f"((julianday({a}) - julianday({b})) * 86400000.0)"


def _json_num(dialect: str, col: str, *path: str) -> str:
    if dialect == "postgresql":
        return f"CAST(({col} #>> '{{{','.join(path)}}}') AS DOUBLE PRECISION)"
    return f"CAST(json_extract({col}, '$.{'.'.join(path)}') AS REAL)"


@dataclass(frozen=True)
class Model:
    name: str
    sql: str  # unrendered
    refs: frozenset[str]


def load_models(directory: Path = MODELS_DIR) -> dict[str, Model]:
    models = {}
    for path in sorted(directory.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        refs = frozenset(
            _ARG.findall(args)[0]
            for name, args in _MACRO.findall(sql)
            if name == "ref" and _ARG.findall(args)
        )
        models[path.stem] = Model(path.stem, sql, refs)
    for m in models.values():
        missing = m.refs - models.keys()
        if missing:
            raise ValueError(f"model {m.name} refs unknown model(s): {sorted(missing)}")
    return models


def render(model: Model, dialect: str) -> str:
    def sub(match: re.Match) -> str:
        name, raw = match.group(1), match.group(2)
        args = _ARG.findall(raw)
        if name == "ref":
            return args[0]
        if name == "day":
            return _day(dialect, *args)
        if name == "ms_between":
            return _ms_between(dialect, *args)
        if name == "json_num":
            return _json_num(dialect, *args)
        raise ValueError(f"unknown macro {name!r} in model {model.name}")

    return _MACRO.sub(sub, model.sql).strip().rstrip(";")


def build_order(models: dict[str, Model]) -> list[str]:
    return list(TopologicalSorter({m.name: m.refs for m in models.values()}).static_order())


def drop(conn: Connection, models: dict[str, Model] | None = None) -> None:
    models = models or load_models()
    cascade = " CASCADE" if conn.dialect.name == "postgresql" else ""
    for name in reversed(build_order(models)):
        conn.execute(text(f"DROP VIEW IF EXISTS {name}{cascade}"))


def build(engine: Engine) -> list[str]:
    """(Re)create all analytics views. Returns the build order."""
    models = load_models()
    order = build_order(models)
    with engine.begin() as conn:
        drop(conn, models)
        for name in order:
            conn.execute(text(f"CREATE VIEW {name} AS\n{render(models[name], conn.dialect.name)}"))
    return order
